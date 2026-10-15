"""
users.py — Gerenciamento de usuários do dashboard (admin)

    GET    /api/v1/users                     — lista os usuários
    POST   /api/v1/users                     — cria um usuário
    PATCH  /api/v1/users/{id}                — edita apelido / papel / ativo
    DELETE /api/v1/users/{id}                — remove o usuário
    POST   /api/v1/users/{id}/reset-password — admin define nova senha

Todos os endpoints exigem papel admin (ver app.auth.require_admin). Um admin
não pode se auto-rebaixar/desativar/remover se for o último admin ativo —
isso deixaria o sistema sem ninguém capaz de gerenciar contas.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..auth import require_admin
from ..database import get_session
from ..models import User
from ..schemas import PasswordReset, UserCreate, UserOut, UserPatch

router = APIRouter(
    prefix="/api/v1/users",
    tags=["users"],
    dependencies=[Depends(require_admin)],
)


async def _get_or_404(session: AsyncSession, user_id: int) -> User:
    user = await crud.get_user(session, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado",
        )
    return user


def _would_remove_last_admin(user: User, body: UserPatch) -> bool:
    """True se a mudança tirar o único admin ativo restante do papel/ativo."""
    if user.role != "admin" or not user.is_active:
        return False
    losing_admin = body.role is not None and body.role != "admin"
    losing_active = body.is_active is False
    return losing_admin or losing_active


@router.get("", response_model=list[UserOut])
async def list_users(session: AsyncSession = Depends(get_session)):
    return await crud.list_users(session)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreate, session: AsyncSession = Depends(get_session)):
    if await crud.get_user_by_username(session, body.username) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe um usuário com este nome",
        )
    return await crud.create_user(session, body)


@router.patch("/{user_id}", response_model=UserOut)
async def patch_user(
    user_id: int,
    body: UserPatch,
    session: AsyncSession = Depends(get_session),
):
    user = await _get_or_404(session, user_id)
    if await _blocked_last_admin(session, user, body):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Não é possível remover o último administrador ativo",
        )
    return await crud.update_user(session, user, body)


async def _blocked_last_admin(session: AsyncSession, user: User, body: UserPatch) -> bool:
    if not _would_remove_last_admin(user, body):
        return False
    remaining = await crud.count_active_admins(session, exclude_id=user.id)
    return remaining == 0


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user(user_id: int, session: AsyncSession = Depends(get_session)):
    user = await _get_or_404(session, user_id)
    if user.role == "admin" and user.is_active:
        remaining = await crud.count_active_admins(session, exclude_id=user.id)
        if remaining == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Não é possível remover o último administrador ativo",
            )
    await crud.delete_user(session, user)


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    user_id: int,
    body: PasswordReset,
    session: AsyncSession = Depends(get_session),
):
    user = await _get_or_404(session, user_id)
    await crud.set_password(session, user, body.new_password)
