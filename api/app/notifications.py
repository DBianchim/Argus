"""
notifications.py — Motor de notificações

Detecta transições de estado de um servidor (avaliadas por app.analysis) e
registra um alerta em notification_log. O dashboard lê esse log e dispara o
pop-up. Nenhuma entrega externa (e-mail/webhook) — só registro + pop-up in-app.

Princípios:
    - Notifica na MUDANÇA de estado, nunca a cada ciclo (usa servers.last_status).
    - Piora (→warn/crit/offline) e recuperação (→ok) geram registro; estável não.
    - record_transition NUNCA levanta — falha de notificação não quebra a ingestão.
"""

import datetime
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from .analysis import ServerHealth, Status, evaluate_server
from .models import NotificationLog, Server

logger = logging.getLogger(__name__)

_SEVERITY = {Status.OK: 0, Status.UNKNOWN: 1, Status.WARN: 2, Status.CRIT: 3,
             Status.OFFLINE: 4}

_STATUS_LABEL = {
    Status.OK: "OK",
    Status.WARN: "AVISO",
    Status.CRIT: "CRÍTICO",
    Status.OFFLINE: "OFFLINE",
    Status.UNKNOWN: "SEM DADOS",
}


def should_notify(old: Status | None, new: Status) -> str | None:
    """
    Decide se a transição old→new gera notificação e com qual severidade.

    Returns:
        'crit' | 'warn' | 'info'  → registra
        None                       → não notifica (sem mudança ou irrelevante)
    """
    if old == new:
        return None
    # Primeira avaliação (old None) só notifica se já nasce ruim
    old_sev = _SEVERITY.get(old, 0) if old is not None else 0
    new_sev = _SEVERITY[new]

    if new == Status.OK:
        # Recuperação só importa se vinha de um estado ruim
        return "info" if old_sev >= _SEVERITY[Status.WARN] else None
    if new in (Status.CRIT, Status.OFFLINE):
        return "crit"
    if new == Status.WARN:
        return "warn"
    return None   # transições de/para UNKNOWN não alertam


def _build_message(server: Server, new: Status, health: ServerHealth) -> tuple[str, str]:
    label = _STATUS_LABEL.get(new, new.value.upper())
    name = server.display_name or server.hostname

    if new == Status.OK:
        return f"{name} voltou ao normal", "Todos os pilares OK"

    # Detalhe = alerta de maior severidade do ServerHealth
    top = next((a for a in health.alerts if a.severity == "crit"), None) \
        or (health.alerts[0] if health.alerts else None)
    detail = f"{top.title}{(' — ' + top.detail) if top.detail else ''}" if top else ""
    return f"{name} ficou {label}", detail[:500]


async def record_transition(
    session: AsyncSession,
    server: Server,
    old: Status | None,
    new: Status,
    health: ServerHealth,
) -> NotificationLog | None:
    """
    Registra a transição em notification_log e atualiza o last_status do servidor.
    Idempotente por estado: se old==new, não faz nada. Nunca levanta.
    """
    severity = should_notify(old, new)
    if severity is None:
        # Mesmo sem alerta, mantém o last_status atualizado (ex.: unknown→ok)
        _update_server_state(server, new)
        return None

    title, detail = _build_message(server, new, health)
    top = next((a for a in health.alerts), None)

    entry = NotificationLog(
        server_id=server.id,
        severity=severity,
        pilar=top.pilar if top else None,
        item=top.item if top else None,
        title=title,
        detail=detail,
        status_from=old.value if old else None,
        status_to=new.value,
    )
    session.add(entry)
    _update_server_state(server, new)

    log = logger.warning if severity == "crit" else logger.info
    log("NOTIFICACAO | %s | %s -> %s | %s",
        title, old.value if old else "-", new.value, detail)
    return entry


def _update_server_state(server: Server, new: Status) -> None:
    if server.last_status != new.value:
        server.last_status = new.value
        server.last_status_changed_at = datetime.datetime.now(datetime.timezone.utc)


async def evaluate_and_notify(
    session: AsyncSession,
    server: Server,
    pilar_metrics: dict[str, dict],
    offline_after_seconds: int,
    now: datetime.datetime | None = None,
) -> ServerHealth:
    """
    Reavalia um servidor, registra a transição (se houver) e persiste.

    Orquestra o motor de análise + notificações. Usado pela ingestão (após
    persistir um payload) e pelo loop de offline. Commit incluso.
    """
    old = Status(server.last_status) if server.last_status else None
    health = evaluate_server(pilar_metrics, server.last_seen_at,
                             offline_after_seconds, now, config=server.config)
    await record_transition(session, server, old, health.status, health)
    await session.commit()
    return health
