"""
crud.py — Operações de banco (camada de acesso a dados)

Mantém o SQL/ORM isolado dos routers: ingestão, registro de servidores e as
consultas do dashboard (lista, último estado por pilar, histórico paginado).
"""

import datetime
import secrets

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import schemas
from .auth import hash_token
from .config import settings
from .models import Metric, NotificationLog, Server, User, UserSession


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


# ── ingestão ──────────────────────────────────────────────────────────────────

async def insert_metric(
    session: AsyncSession,
    server: Server,
    envelope: "schemas.IngestEnvelope",
    request_id: str | None,
) -> Metric:
    """Persiste um payload e atualiza o last_seen_at do servidor (mesma transação)."""
    metric = Metric(
        server_id=server.id,
        pilar=envelope.pilar,
        os_family=envelope.os_family,
        collected_at=envelope.timestamp,
        request_id=request_id,
        agent_version=envelope.agent_version,
        metrics=envelope.metrics,
    )
    session.add(metric)
    server.last_seen_at = _utcnow()
    await session.commit()
    await session.refresh(metric)
    return metric


# ── servidores ────────────────────────────────────────────────────────────────

async def list_servers(session: AsyncSession) -> list[Server]:
    result = await session.execute(select(Server).order_by(Server.hostname))
    return list(result.scalars().all())


async def get_server(session: AsyncSession, server_id: int) -> Server | None:
    return await session.get(Server, server_id)


# ── consultas de métricas ─────────────────────────────────────────────────────

async def latest_per_pilar(session: AsyncSession, server_id: int) -> list[Metric]:
    """
    Último payload de cada pilar para um servidor (estado atual).

    Usa window function (row_number) — portável entre PostgreSQL e SQLite.
    """
    rn = (
        func.row_number()
        .over(
            partition_by=Metric.pilar,
            # id desc desempata payloads com o mesmo collected_at (mesmo segundo)
            order_by=(Metric.collected_at.desc(), Metric.id.desc()),
        )
        .label("rn")
    )
    subq = (
        select(Metric, rn)
        .where(Metric.server_id == server_id)
        .subquery()
    )
    metric_alias = subq
    result = await session.execute(
        select(Metric)
        .join(metric_alias, Metric.id == metric_alias.c.id)
        .where(metric_alias.c.rn == 1)
        .order_by(metric_alias.c.pilar)
    )
    return list(result.scalars().all())


async def latest_per_pilar_all(session: AsyncSession) -> list[Metric]:
    """
    Último payload de cada (servidor, pilar) — frota inteira em 1 query.
    Alimenta o GET /overview sem N+1.
    """
    rn = (
        func.row_number()
        .over(
            partition_by=(Metric.server_id, Metric.pilar),
            order_by=(Metric.collected_at.desc(), Metric.id.desc()),
        )
        .label("rn")
    )
    subq = select(Metric.id, rn).subquery()
    result = await session.execute(
        select(Metric).join(subq, Metric.id == subq.c.id).where(subq.c.rn == 1)
    )
    return list(result.scalars().all())


# ── usuarios e sessoes ────────────────────────────────────────────────────────

async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def create_user_session(
    session: AsyncSession, user: User
) -> tuple[str, UserSession]:
    """Cria uma sessão e retorna (token em claro, sessão). O token não é armazenado."""
    token = secrets.token_urlsafe(32)
    expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        hours=settings.session_ttl_hours
    )
    user_session = UserSession(
        token_hash=hash_token(token), user_id=user.id, expires_at=expires
    )
    session.add(user_session)
    await session.commit()
    await session.refresh(user_session)
    return token, user_session


async def revoke_session_by_token(session: AsyncSession, token: str) -> bool:
    result = await session.execute(
        select(UserSession).where(UserSession.token_hash == hash_token(token))
    )
    user_session = result.scalar_one_or_none()
    if user_session is None:
        return False
    user_session.revoked = True
    await session.commit()
    return True


# ── notificacoes ──────────────────────────────────────────────────────────────

async def list_notifications(
    session: AsyncSession, *, limit: int = 50, since_id: int | None = None
) -> list[NotificationLog]:
    stmt = select(NotificationLog).order_by(NotificationLog.id.desc())
    if since_id is not None:
        stmt = stmt.where(NotificationLog.id > since_id)
    stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def servers_for_offline_check(session: AsyncSession) -> list[Server]:
    """Servidores já vistos ao menos uma vez (candidatos a virar OFFLINE)."""
    result = await session.execute(
        select(Server).where(Server.last_seen_at.is_not(None))
    )
    return list(result.scalars().all())


async def query_metrics(
    session: AsyncSession,
    *,
    server_id: int | None = None,
    pilar: str | None = None,
    since: datetime.datetime | None = None,
    until: datetime.datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[Metric]]:
    """Histórico filtrado e paginado. Retorna (total, itens da página)."""
    conditions = []
    if server_id is not None:
        conditions.append(Metric.server_id == server_id)
    if pilar is not None:
        conditions.append(Metric.pilar == pilar)
    if since is not None:
        conditions.append(Metric.collected_at >= since)
    if until is not None:
        conditions.append(Metric.collected_at <= until)

    count_stmt = select(func.count()).select_from(Metric)
    page_stmt = select(Metric).order_by(Metric.collected_at.desc())
    for cond in conditions:
        count_stmt = count_stmt.where(cond)
        page_stmt = page_stmt.where(cond)

    total = (await session.execute(count_stmt)).scalar_one()
    page_stmt = page_stmt.limit(limit).offset(offset)
    items = list((await session.execute(page_stmt)).scalars().all())
    return total, items
