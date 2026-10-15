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
from .auth import hash_password, hash_token
from .config import settings
from .config_defaults import default_config
from .models import AlertAck, Metric, NotificationLog, Server, User, UserSession


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


async def create_server(
    session: AsyncSession, *, hostname: str, os_family: str, display_name: str | None
) -> tuple[Server, str]:
    """Registra um servidor e devolve (server, token em claro — só existe agora)."""
    token = secrets.token_urlsafe(32)
    server = Server(
        hostname=hostname,
        os_family=os_family,
        display_name=display_name,
        api_token_hash=hash_token(token),
        is_active=True,
        config=default_config(os_family),
        config_version=1,
    )
    session.add(server)
    await session.commit()
    await session.refresh(server)
    return server, token


async def update_server(
    session: AsyncSession,
    server: Server,
    *,
    display_name: str | None = None,
    is_active: bool | None = None,
) -> Server:
    """Atualiza metadados do servidor (apelido, ativo). Campos None = não mexe."""
    if display_name is not None:
        server.display_name = display_name or None
    if is_active is not None:
        server.is_active = is_active
    await session.commit()
    await session.refresh(server)
    return server


async def delete_server(session: AsyncSession, server: Server) -> None:
    """Remove o servidor (cascade nas métricas e notificações)."""
    await session.delete(server)
    await session.commit()


def effective_config(server: Server) -> dict:
    """Config do servidor; se ainda NULL, devolve o default do seu os_family."""
    return server.config if server.config else default_config(server.os_family)


async def put_server_config(
    session: AsyncSession, server: Server, config: dict
) -> Server:
    """Substitui a config do servidor e incrementa config_version (sinal de sync)."""
    server.config = config
    server.config_version = (server.config_version or 1) + 1
    await session.commit()
    await session.refresh(server)
    return server


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


async def recent_operacional_history(
    session: AsyncSession, *, limit_per_server: int = 16
) -> list[Metric]:
    """
    Últimas N amostras do pilar operacional de cada servidor — frota inteira em
    1 query. Alimenta o sparkline de CPU do GET /overview sem N+1.
    """
    rn = (
        func.row_number()
        .over(
            partition_by=Metric.server_id,
            order_by=(Metric.collected_at.desc(), Metric.id.desc()),
        )
        .label("rn")
    )
    subq = (
        select(Metric.id, rn)
        .where(Metric.pilar == "operacional")
        .subquery()
    )
    result = await session.execute(
        select(Metric)
        .join(subq, Metric.id == subq.c.id)
        .where(subq.c.rn <= limit_per_server)
    )
    return list(result.scalars().all())


# ── reconhecimento de alertas ──────────────────────────────────────────────────

async def acks_for_servers(session: AsyncSession, server_ids: list[int]) -> list[AlertAck]:
    """Todos os reconhecimentos da frota visível — 1 query, sem N+1 no overview."""
    if not server_ids:
        return []
    result = await session.execute(
        select(AlertAck).where(AlertAck.server_id.in_(server_ids))
    )
    return list(result.scalars().all())


async def upsert_ack(
    session: AsyncSession, *, server_id: int, pilar: str, item: str, acked_by: str
) -> AlertAck:
    """Reconhece (server_id, pilar, item) — substitui um reconhecimento anterior."""
    result = await session.execute(
        select(AlertAck).where(
            AlertAck.server_id == server_id, AlertAck.pilar == pilar, AlertAck.item == item,
        )
    )
    ack = result.scalar_one_or_none()
    now = _utcnow()
    if ack is None:
        ack = AlertAck(server_id=server_id, pilar=pilar, item=item, acked_by=acked_by, acked_at=now)
        session.add(ack)
    else:
        ack.acked_by = acked_by
        ack.acked_at = now
    await session.commit()
    await session.refresh(ack)
    return ack


async def latest_bad_notification(session: AsyncSession, server_ids: list[int]) -> list[NotificationLog]:
    """
    Última transição para um estado não-OK de cada servidor — aproximação de
    "desde quando" o alerta ativo está em curso (ver notifications.py: o log
    registra só o alerta de topo por transição, não por item individual).
    """
    if not server_ids:
        return []
    rn = (
        func.row_number()
        .over(
            partition_by=NotificationLog.server_id,
            order_by=NotificationLog.created_at.desc(),
        )
        .label("rn")
    )
    subq = (
        select(NotificationLog.id, rn)
        .where(NotificationLog.server_id.in_(server_ids), NotificationLog.status_to != "ok")
        .subquery()
    )
    result = await session.execute(
        select(NotificationLog)
        .join(subq, NotificationLog.id == subq.c.id)
        .where(subq.c.rn == 1)
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


async def list_active_sessions(session: AsyncSession, user_id: int) -> list[UserSession]:
    """Sessões não revogadas e não expiradas do usuário, mais recente primeiro."""
    result = await session.execute(
        select(UserSession)
        .where(
            UserSession.user_id == user_id,
            UserSession.revoked.is_(False),
            UserSession.expires_at > _utcnow(),
        )
        .order_by(UserSession.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke_session_by_id(session: AsyncSession, user_id: int, session_id: int) -> bool:
    """Revoga uma sessão do próprio usuário. True se encontrou e revogou."""
    result = await session.execute(
        select(UserSession).where(
            UserSession.id == session_id, UserSession.user_id == user_id,
        )
    )
    user_session = result.scalar_one_or_none()
    if user_session is None:
        return False
    user_session.revoked = True
    await session.commit()
    return True


# ── gerenciamento de usuarios (admin) ─────────────────────────────────────────

async def list_users(session: AsyncSession) -> list[User]:
    result = await session.execute(select(User).order_by(User.username))
    return list(result.scalars().all())


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def count_active_admins(session: AsyncSession, *, exclude_id: int | None = None) -> int:
    """Quantos admins ativos existem (excluindo opcionalmente um id) — evita lockout."""
    stmt = select(func.count()).select_from(User).where(
        User.role == "admin", User.is_active.is_(True)
    )
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    return (await session.execute(stmt)).scalar_one()


async def create_user(
    session: AsyncSession, body: "schemas.UserCreate"
) -> User:
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        role=body.role,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def update_user(
    session: AsyncSession, user: User, body: "schemas.UserPatch"
) -> User:
    if body.display_name is not None:
        user.display_name = body.display_name or None
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    await session.commit()
    await session.refresh(user)
    return user


async def delete_user(session: AsyncSession, user: User) -> None:
    await session.delete(user)
    await session.commit()


async def update_own_display_name(session: AsyncSession, user: User, display_name: str | None) -> User:
    """Autoatendimento (Minha conta) — só o próprio nome de exibição, nunca papel/ativo."""
    user.display_name = display_name or None
    await session.commit()
    await session.refresh(user)
    return user


async def set_password(session: AsyncSession, user: User, new_password: str) -> None:
    """Troca a senha e revoga todas as sessões existentes do usuário."""
    user.password_hash = hash_password(new_password)
    result = await session.execute(
        select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked.is_(False))
    )
    for user_session in result.scalars().all():
        user_session.revoked = True
    await session.commit()


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
