"""
servers.py — Consultas de servidores (protegidas pelo token de dashboard)

    GET /api/v1/servers              — lista os servidores registrados
    GET /api/v1/servers/{id}/latest  — último payload de cada pilar (estado atual)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..auth import require_dashboard
from ..database import get_session
from ..schemas import MetricOut, ServerOut

router = APIRouter(
    prefix="/api/v1",
    tags=["servers"],
    dependencies=[Depends(require_dashboard)],
)


@router.get("/servers", response_model=list[ServerOut])
async def list_servers(session: AsyncSession = Depends(get_session)):
    return await crud.list_servers(session)


@router.get("/servers/{server_id}/latest", response_model=list[MetricOut])
async def server_latest(
    server_id: int,
    session: AsyncSession = Depends(get_session),
):
    server = await crud.get_server(session, server_id)
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Servidor não encontrado",
        )
    return await crud.latest_per_pilar(session, server_id)
