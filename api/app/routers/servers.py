"""
servers.py — Consultas e gestão de servidores (protegidas pelo token de dashboard)

    GET    /api/v1/servers               — lista os servidores registrados
    GET    /api/v1/servers/{id}/latest   — último payload de cada pilar (estado atual)
    PATCH  /api/v1/servers/{id}          — apelido / ativar-desativar
    DELETE /api/v1/servers/{id}          — remove o servidor (cascade)
    GET    /api/v1/servers/{id}/config   — config do agente (editor)
    PUT    /api/v1/servers/{id}/config   — substitui a config (incrementa a versão)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..auth import require_dashboard
from ..database import get_session
from ..schemas import (
    MetricOut,
    ServerConfigOut,
    ServerConfigUpdate,
    ServerOut,
    ServerPatch,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["servers"],
    dependencies=[Depends(require_dashboard)],
)


async def _get_or_404(session: AsyncSession, server_id: int):
    server = await crud.get_server(session, server_id)
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Servidor não encontrado",
        )
    return server


@router.get("/servers", response_model=list[ServerOut])
async def list_servers(session: AsyncSession = Depends(get_session)):
    return await crud.list_servers(session)


@router.get("/servers/{server_id}/latest", response_model=list[MetricOut])
async def server_latest(
    server_id: int,
    session: AsyncSession = Depends(get_session),
):
    await _get_or_404(session, server_id)
    return await crud.latest_per_pilar(session, server_id)


@router.patch("/servers/{server_id}", response_model=ServerOut)
async def patch_server(
    server_id: int,
    body: ServerPatch,
    session: AsyncSession = Depends(get_session),
):
    server = await _get_or_404(session, server_id)
    return await crud.update_server(
        session, server,
        display_name=body.display_name,
        is_active=body.is_active,
    )


@router.delete("/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_server(
    server_id: int,
    session: AsyncSession = Depends(get_session),
):
    server = await _get_or_404(session, server_id)
    await crud.delete_server(session, server)


@router.get("/servers/{server_id}/config", response_model=ServerConfigOut)
async def get_server_config(
    server_id: int,
    session: AsyncSession = Depends(get_session),
):
    server = await _get_or_404(session, server_id)
    return ServerConfigOut(
        config=crud.effective_config(server),
        config_version=server.config_version,
    )


@router.put("/servers/{server_id}/config", response_model=ServerConfigOut)
async def put_server_config(
    server_id: int,
    body: ServerConfigUpdate,
    session: AsyncSession = Depends(get_session),
):
    server = await _get_or_404(session, server_id)
    server = await crud.put_server_config(session, server, body.config)
    return ServerConfigOut(config=server.config, config_version=server.config_version)
