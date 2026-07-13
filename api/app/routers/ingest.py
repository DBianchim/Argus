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
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, notifications
from ..auth import authenticate_agent, require_dashboard
from ..config import settings
from ..database import get_session
from ..ingest_metrics import metrics as ingest_metrics
from ..models import Server
from ..rate_limit import limiter
from ..schemas import IngestEnvelope, IngestResponse, IngestStatsOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["ingest"])

# Circuit breaker, não throttle: precisa folgar acima do reenvio de fila
# inteiro (até 1000 payloads — ver rate_limit.py). Protege contra token
# comprometido/agente em loop, não o uso normal, nem a recuperação de fila.
_INGEST_LIMIT = "1500/minute"


@router.post(
    "/ingest",
    response_model=IngestResponse,
    status_code=status.HTTP_200_OK,
    summary="Recebe um payload de métricas de um agente",
)
@limiter.limit(_INGEST_LIMIT)
async def ingest(
    request: Request,
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

    # Instrumentação: cronometra a persistência (parte crítica do custo de
    # ingestão) e o handler inteiro. perf_counter é monotônico — imune a ajustes
    # de relógio. Registra o evento mesmo em falha, para a taxa de erro ser real.
    handler_start = time.perf_counter()
    try:
        persist_start = time.perf_counter()
        metric = await crud.insert_metric(session, server, envelope, x_request_id)
        persist_ms = (time.perf_counter() - persist_start) * 1000
    except Exception as exc:
        await session.rollback()
        ingest_metrics.record(
            pilar=envelope.pilar,
            total_ms=(time.perf_counter() - handler_start) * 1000,
            persist_ms=(time.perf_counter() - handler_start) * 1000,
            ok=False,
        )
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

    ingest_metrics.record(
        pilar=envelope.pilar,
        total_ms=(time.perf_counter() - handler_start) * 1000,
        persist_ms=persist_ms,
        ok=True,
    )

    # config_version sinaliza ao agente se a config dele mudou (ele rebaixa via
    # GET /agent-config quando a versão diferir da que tem em cache).
    return IngestResponse(
        status="accepted",
        metric_id=metric.id,
        config_version=server.config_version,
    )


@router.get(
    "/ingest/stats",
    response_model=IngestStatsOut,
    dependencies=[Depends(require_dashboard)],
    summary="Estatísticas de desempenho da ingestão (em memória)",
)
async def ingest_stats():
    """Contadores e latências de ingestão desde o último boot da central.

    Efêmero (zera ao reiniciar). Protegido pelo token do dashboard — não é
    dado de agente. Alimenta a evidência de desempenho/carga.
    """
    return ingest_metrics.snapshot()
