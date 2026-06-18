"""
ingest.py — POST /api/v1/ingest

Recebe o envelope de um agente autenticado e persiste.

Contrato com o agente (agents/core/sender.py):
    200 → aceito (sucesso). DEVE ser exatamente 200.
    401 → token inválido (auth dependency). Agente descarta.
    422 → corpo inválido (validação Pydantic). Agente descarta.
    503 → erro transitório ao persistir. Agente retenta e enfileira.
"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, notifications
from ..auth import authenticate_agent
from ..config import settings
from ..database import get_session
from ..models import Server
from ..schemas import IngestEnvelope, IngestResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["ingest"])


@router.post(
    "/ingest",
    response_model=IngestResponse,
    status_code=status.HTTP_200_OK,
    summary="Recebe um payload de métricas de um agente",
)
async def ingest(
    envelope: IngestEnvelope,
    server: Server = Depends(authenticate_agent),
    session: AsyncSession = Depends(get_session),
    x_request_id: str | None = Header(default=None),
):
    # Divergência de hostname não bloqueia (o token é a identidade), apenas registra.
    if envelope.hostname and envelope.hostname != server.hostname:
        logger.warning(
            "Hostname do payload (%s) difere do servidor registrado (%s)",
            envelope.hostname, server.hostname,
        )

    try:
        metric = await crud.insert_metric(session, server, envelope, x_request_id)
    except Exception as exc:
        await session.rollback()
        logger.error("Falha ao persistir métrica | pilar=%s | erro=%s",
                     envelope.pilar, type(exc).__name__)
        # 503 → transitório: o agente vai retentar e, no limite, enfileirar.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Erro ao persistir o payload — tente novamente",
        )

    # Notificação (best-effort): reavalia o servidor e registra transição de
    # estado. Falha aqui jamais afeta a resposta do ingest (payload já persistido).
    try:
        latest = await crud.latest_per_pilar(session, server.id)
        pilar_metrics = {m.pilar: m.metrics for m in latest}
        await notifications.evaluate_and_notify(
            session, server, pilar_metrics, settings.offline_after_seconds
        )
    except Exception as exc:
        await session.rollback()
        logger.warning("Falha ao avaliar notificacao | pilar=%s | erro=%s",
                       envelope.pilar, type(exc).__name__)

    # config_version sinaliza ao agente se a config dele mudou (ele rebaixa via
    # GET /agent-config quando a versão diferir da que tem em cache).
    return IngestResponse(
        status="accepted",
        metric_id=metric.id,
        config_version=server.config_version,
    )
