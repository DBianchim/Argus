"""
notifications.py (router) — Histórico de alertas para o dashboard

    GET /api/v1/notifications?limit=50&since_id=N

O frontend guarda o maior `id` já visto (since_id) para detectar os novos e
disparar o pop-up. Protegido pelo token de dashboard/sessão.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..auth import require_dashboard
from ..database import get_session
from ..schemas import NotificationOut, NotificationPage

router = APIRouter(
    prefix="/api/v1",
    tags=["notifications"],
    dependencies=[Depends(require_dashboard)],
)


@router.get("/notifications", response_model=NotificationPage)
async def list_notifications(
    limit: int = Query(50, ge=1, le=200),
    since_id: int | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    items = await crud.list_notifications(session, limit=limit, since_id=since_id)
    return NotificationPage(
        items=[NotificationOut.model_validate(item) for item in items]
    )
