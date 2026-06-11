"""
metrics.py — Histórico de métricas (protegido pelo token de dashboard)

    GET /api/v1/metrics — histórico com filtros (server_id, pilar, since, until)
                          e paginação (limit/offset).
"""

import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..auth import require_dashboard
from ..database import get_session
from ..schemas import MetricPage, Pilar

router = APIRouter(
    prefix="/api/v1",
    tags=["metrics"],
    dependencies=[Depends(require_dashboard)],
)


@router.get("/metrics", response_model=MetricPage)
async def list_metrics(
    server_id: int | None = None,
    pilar: Pilar | None = None,
    since: datetime.datetime | None = None,
    until: datetime.datetime | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    total, items = await crud.query_metrics(
        session,
        server_id=server_id,
        pilar=pilar,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    return MetricPage(total=total, limit=limit, offset=offset, items=items)
