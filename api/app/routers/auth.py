"""
auth.py (router) — Entrada do usuário no dashboard

    POST /api/v1/auth/login   — credenciais → token de sessão (12h)
    POST /api/v1/auth/logout  — revoga a sessão atual
    GET  /api/v1/auth/me      — dados do usuário logado

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
from ..schemas import LoginIn, LoginOut, UserOut

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
