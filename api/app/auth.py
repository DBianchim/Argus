"""
auth.py — Autenticação por token (agentes, usuários e serviço)

Três identidades:
    - Agentes (ingest): token por servidor → sha256 vs servers.api_token_hash.
    - Usuários (dashboard): login → sessão opaca (token sha256 em user_sessions).
    - Serviço: settings.dashboard_token — para integrações/automação.

Os endpoints de consulta aceitam sessão de usuário VÁLIDA ou o token de serviço.
Token inválido → HTTP 401 (o agente trata 401 como definitivo e descarta).

Senhas: hashlib.scrypt (stdlib) com salt aleatório por usuário, formato
'scrypt$n$r$p$salt_hex$hash_hex'; comparação em tempo constante.
"""

import datetime
import hashlib
import hmac
import secrets

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import get_session
from .models import Server, User, UserSession


# ── tokens (sha256) ───────────────────────────────────────────────────────────

def hash_token(token: str) -> str:
    """sha256 hex do token. Usado para tokens de agente e de sessão."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ── senhas (scrypt, stdlib) ───────────────────────────────────────────────────

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, hash_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=32,
        )
        return hmac.compare_digest(digest.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


# ── helpers ───────────────────────────────────────────────────────────────────

def _extract_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cabeçalho Authorization ausente ou malformado",
        )
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token vazio",
        )
    return token


def _ensure_aware(dt: datetime.datetime) -> datetime.datetime:
    """SQLite (testes) devolve datetimes naive — assume UTC."""
    return dt.replace(tzinfo=datetime.timezone.utc) if dt.tzinfo is None else dt


async def _resolve_session(
    session: AsyncSession, token: str
) -> tuple[UserSession, User] | None:
    """Retorna (sessão, usuário) se o token corresponder a uma sessão válida."""
    result = await session.execute(
        select(UserSession, User)
        .join(User, UserSession.user_id == User.id)
        .where(UserSession.token_hash == hash_token(token))
    )
    row = result.first()
    if row is None:
        return None
    user_session, user = row
    now = datetime.datetime.now(datetime.timezone.utc)
    if user_session.revoked or _ensure_aware(user_session.expires_at) <= now:
        return None
    if not user.is_active:
        return None
    return user_session, user


# ── dependencies ──────────────────────────────────────────────────────────────

async def authenticate_agent(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> Server:
    """Resolve o servidor a partir do token Bearer. 401 se inválido/ inativo."""
    token_hash = hash_token(_extract_bearer(authorization))
    result = await session.execute(
        select(Server).where(Server.api_token_hash == token_hash)
    )
    server = result.scalar_one_or_none()
    if server is None or not server.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou servidor inativo",
        )
    return server


async def require_dashboard(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> None:
    """
    Protege os endpoints de consulta: aceita sessão de usuário válida
    OU o token de serviço (DASHBOARD_TOKEN).
    """
    token = _extract_bearer(authorization)
    if hmac.compare_digest(token, settings.dashboard_token):
        return
    if await _resolve_session(session, token) is not None:
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sessão inválida ou expirada",
    )


async def get_current_user(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> tuple[UserSession, User]:
    """Exige uma sessão de usuário (token de serviço NÃO é aceito aqui)."""
    token = _extract_bearer(authorization)
    resolved = await _resolve_session(session, token)
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessão inválida ou expirada",
        )
    return resolved
