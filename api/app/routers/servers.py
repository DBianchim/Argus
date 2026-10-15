"""
servers.py — Consultas e gestão de servidores

    GET    /api/v1/servers                    — lista os servidores registrados     (viewer+)
    POST   /api/v1/servers                    — registra um servidor, gera o token  (operator+)
    GET    /api/v1/servers/{id}/latest        — último payload de cada pilar        (viewer+)
    PATCH  /api/v1/servers/{id}               — apelido / ativar-desativar          (operator+)
    DELETE /api/v1/servers/{id}               — remove o servidor (cascade)         (operator+)
    GET    /api/v1/servers/{id}/config        — config do agente (editor)          (viewer+)
    PUT    /api/v1/servers/{id}/config        — substitui a config                  (operator+)
    POST   /api/v1/servers/{id}/alerts/ack    — reconhece o alerta (pilar, item)    (viewer+, sessão de usuário)

Leitura exige apenas sessão válida (require_dashboard); edição/remoção exige
papel operator ou admin (require_operator) — ver app.auth para a hierarquia.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..auth import get_current_user, require_dashboard, require_operator
from ..database import get_session
from ..schemas import (
    AlertAckIn,
    AlertAckOut,
    MetricOut,
    ServerConfigOut,
    ServerConfigUpdate,
    ServerCreate,
    ServerCreateOut,
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


@router.post(
    "/servers", response_model=ServerCreateOut, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_operator)],
)
async def create_server(body: ServerCreate, session: AsyncSession = Depends(get_session)):
    """Registra um servidor pelo dashboard — equivalente a `manage.py create-server`.
    O token só existe em claro nesta resposta; o agente se autentica com ele."""
    server, token = await crud.create_server(
        session,
        hostname=body.hostname,
        os_family=body.os_family,
        display_name=body.display_name,
    )
    return ServerCreateOut(server=ServerOut.model_validate(server), token=token)


@router.get("/servers/{server_id}/latest", response_model=list[MetricOut])
async def server_latest(
    server_id: int,
    session: AsyncSession = Depends(get_session),
):
    await _get_or_404(session, server_id)
    return await crud.latest_per_pilar(session, server_id)


@router.patch(
    "/servers/{server_id}", response_model=ServerOut,
    dependencies=[Depends(require_operator)],
)
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


@router.delete(
    "/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_operator)],
)
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


@router.put(
    "/servers/{server_id}/config", response_model=ServerConfigOut,
    dependencies=[Depends(require_operator)],
)
async def put_server_config(
    server_id: int,
    body: ServerConfigUpdate,
    session: AsyncSession = Depends(get_session),
):
    server = await _get_or_404(session, server_id)
    server = await crud.put_server_config(session, server, body.config)
    return ServerConfigOut(config=server.config, config_version=server.config_version)


@router.post("/servers/{server_id}/alerts/ack", response_model=AlertAckOut)
async def ack_alert(
    server_id: int,
    body: AlertAckIn,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Reconhece o alerta ativo (pilar, item) de um servidor. Não silencia — o
    alerta some da lista quando a métrica normaliza, não quando reconhecido."""
    await _get_or_404(session, server_id)
    _, user = current
    ack = await crud.upsert_ack(
        session,
        server_id=server_id,
        pilar=body.pilar,
        item=body.item,
        acked_by=user.display_name or user.username,
    )
    return AlertAckOut(acked_by=ack.acked_by, acked_at=ack.acked_at)
