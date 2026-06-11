"""
overview.py — Visão Geral da frota e saúde por servidor

    GET /api/v1/overview             — KPIs + status de todos os servidores + alertas
    GET /api/v1/servers/{id}/health  — saúde detalhada de um servidor (header do detalhe)

Tudo derivado em tempo de consulta pelo motor de análise (app.analysis) sobre
o último payload de cada pilar — sem tabela de alertas na v1.
"""

import datetime
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..analysis import Status, evaluate_server
from ..auth import require_dashboard
from ..config import settings
from ..database import get_session
from ..models import Metric, Server
from ..schemas import (
    AlertOut,
    OverviewKpis,
    OverviewOut,
    ServerHealthOut,
    ServerOverview,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["overview"],
    dependencies=[Depends(require_dashboard)],
)


def _latest_agent_version(metrics: list[Metric]) -> str | None:
    """Versão do agente do payload mais recente entre os pilares do servidor."""
    if not metrics:
        return None
    latest = max(metrics, key=lambda m: m.collected_at)
    return latest.agent_version


def _build_server_view(
    server: Server, server_metrics: list[Metric], now: datetime.datetime
) -> tuple[ServerOverview, list[AlertOut]]:
    pilar_metrics = {m.pilar: m.metrics for m in server_metrics}
    health = evaluate_server(
        pilar_metrics,
        server.last_seen_at,
        offline_after_seconds=settings.offline_after_seconds,
        now=now,
    )
    view = ServerOverview(
        id=server.id,
        hostname=server.hostname,
        os_family=server.os_family,
        display_name=server.display_name,
        status=health.status.value,
        pilar_statuses={p: s.value for p, s in health.pilar_statuses.items()},
        last_seen_at=server.last_seen_at,
        agent_version=_latest_agent_version(server_metrics),
    )
    alerts = [
        AlertOut(
            severity=a.severity, pilar=a.pilar, item=a.item,
            title=a.title, detail=a.detail,
            server_id=server.id, hostname=server.hostname,
        )
        for a in health.alerts
    ]
    return view, alerts


@router.get("/overview", response_model=OverviewOut)
async def overview(session: AsyncSession = Depends(get_session)):
    now = datetime.datetime.now(datetime.timezone.utc)

    servers = await crud.list_servers(session)
    fleet_latest = await crud.latest_per_pilar_all(session)

    by_server: dict[int, list[Metric]] = defaultdict(list)
    for metric in fleet_latest:
        by_server[metric.server_id].append(metric)

    views: list[ServerOverview] = []
    all_alerts: list[AlertOut] = []
    backups_ok = 0
    backups_with_data = 0

    for server in servers:
        view, alerts = _build_server_view(server, by_server.get(server.id, []), now)
        views.append(view)
        all_alerts.extend(alerts)

        backup_status = view.pilar_statuses.get("backup", "unknown")
        if backup_status != "unknown":
            backups_with_data += 1
            if backup_status == "ok":
                backups_ok += 1

    offline = sum(1 for v in views if v.status == Status.OFFLINE.value)
    kpis = OverviewKpis(
        servers_total=len(views),
        online=len(views) - offline,
        offline=offline,
        crit=sum(1 for v in views if v.status == Status.CRIT.value),
        warn=sum(1 for v in views if v.status == Status.WARN.value),
        backups_ok_pct=(
            round(backups_ok * 100 / backups_with_data, 1)
            if backups_with_data else None
        ),
    )

    # Críticos primeiro, depois avisos
    all_alerts.sort(key=lambda a: 0 if a.severity == "crit" else 1)

    return OverviewOut(kpis=kpis, servers=views, alerts=all_alerts, generated_at=now)


@router.get("/servers/{server_id}/health", response_model=ServerHealthOut)
async def server_health(server_id: int, session: AsyncSession = Depends(get_session)):
    server = await crud.get_server(session, server_id)
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Servidor não encontrado",
        )

    now = datetime.datetime.now(datetime.timezone.utc)
    server_metrics = await crud.latest_per_pilar(session, server_id)
    view, alerts = _build_server_view(server, server_metrics, now)

    return ServerHealthOut(
        id=view.id,
        hostname=view.hostname,
        status=view.status,
        pilar_statuses=view.pilar_statuses,
        alerts=alerts,
        last_seen_at=view.last_seen_at,
        agent_version=view.agent_version,
    )
