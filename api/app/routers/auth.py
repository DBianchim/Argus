"""
auth.py (router) — Entrada do usuário no dashboard

    POST   /api/v1/auth/login             — credenciais → token de sessão (12h)
    POST   /api/v1/auth/logout            — revoga a sessão atual
    GET    /api/v1/auth/me                — dados do usuário logado
    PATCH  /api/v1/auth/me                — edita o próprio nome de exibição
    GET    /api/v1/auth/sessions          — sessões ativas do usuário logado
    DELETE /api/v1/auth/sessions/{id}     — revoga uma sessão (própria)

Segurança:
    - Erro de login é sempre genérico ("credenciais inválidas") — não revela
      se o usuário existe.
    - O token de sessão é opaco e armazenado apenas como sha256; revogável.
"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..auth import get_current_user, verify_password, _extract_bearer
from ..database import get_session
from ..schemas import LoginIn, LoginOut, PasswordChange, SelfProfilePatch, SessionOut, UserOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_GENERIC_401 = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Credenciais inválidas",
)


@router.post("/login", response_model=LoginOut)
async def login(body: LoginIn, session: AsyncSession = Depends(get_session)):
    user = await crud.get_user_by_username(session, body.username)

    # Mensagem idêntica para usuário inexistente, inativo ou senha errada —
    # não dar pistas sobre quais contas existem.
    if user is None or not user.is_active:
        raise _GENERIC_401
    if not verify_password(body.password, user.password_hash):
        logger.warning("Login falhou | username=%s", body.username)
        raise _GENERIC_401

    token, user_session = await crud.create_user_session(session, user)
    logger.info("Login bem-sucedido | username=%s", user.username)

    return LoginOut(
        token=token,
        expires_at=user_session.expires_at,
        user=UserOut.model_validate(user),
    )


@router.post("/logout")
async def logout(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
):
    token = _extract_bearer(authorization)
    await crud.revoke_session_by_token(session, token)
    # Sempre 200 — revogar sessão inexistente não é erro (idempotente)
    return {"status": "ok"}


@router.get("/me", response_model=UserOut)
async def me(current=Depends(get_current_user)):
    _, user = current
    return UserOut.model_validate(user)


@router.patch("/me", response_model=UserOut)
async def patch_me(
    body: SelfProfilePatch,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Autoatendimento — edita só o próprio nome de exibição (papel/ativo exigem admin)."""
    _, user = current
    user = await crud.update_own_display_name(session, user, body.display_name)
    return UserOut.model_validate(user)


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    current_session, user = current
    active = await crud.list_active_sessions(session, user.id)
    return [
        SessionOut(
            id=s.id, created_at=s.created_at, expires_at=s.expires_at,
            is_current=s.id == current_session.id,
        )
        for s in active
    ]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: int,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    _, user = current
    found = await crud.revoke_session_by_id(session, user.id, session_id)
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sessão não encontrada",
        )


@router.post("/change-password", response_model=LoginOut)
async def change_password(
    body: PasswordChange,
    current=Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Troca a própria senha. Revoga todas as sessões e emite uma nova para
    quem acabou de trocar (evita deslogar quem fez a ação)."""
    _, user = current
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Senha atual incorreta",
        )
    await crud.set_password(session, user, body.new_password)
    token, user_session = await crud.create_user_session(session, user)
    logger.info("Senha alterada | username=%s", user.username)
    return LoginOut(
        token=token,
        expires_at=user_session.expires_at,
        user=UserOut.model_validate(user),
    )
