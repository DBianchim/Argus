"""
models.py — Modelos ORM (SQLAlchemy 2.0)

    Server — registro e autenticação de cada servidor monitorado
    Metric — cada payload recebido (envelope + bloco metrics como JSON)

A coluna `metrics` usa JSONB no PostgreSQL e JSON no SQLite (testes), via variant —
mantendo portabilidade sem perder a indexação JSONB em produção.
"""

import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# JSONB no Postgres, JSON no SQLite (testes)
_JSON = JSON().with_variant(JSONB, "postgresql")


class Server(Base):
    __tablename__ = "servers"

    id:           Mapped[int] = mapped_column(primary_key=True)
    hostname:     Mapped[str] = mapped_column(String(255), index=True)
    os_family:    Mapped[str] = mapped_column(String(16))
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # sha256 do token (64 hex) — nunca o token em claro
    api_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    is_active:    Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at:   Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Último status avaliado pelo motor de análise — memória para detectar
    # transições (e notificar só na mudança, não a cada ciclo).
    last_status:            Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_status_changed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    metrics: Mapped[list["Metric"]] = relationship(
        back_populates="server", cascade="all, delete-orphan"
    )


class User(Base):
    """Usuário do dashboard (entrada via tela de login)."""
    __tablename__ = "users"

    id:            Mapped[int] = mapped_column(primary_key=True)
    username:      Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Formato: scrypt$n$r$p$salt_hex$hash_hex (ver app.auth.hash_password)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name:  Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active:     Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at:    Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSession(Base):
    """Sessão de login — token opaco armazenado apenas como sha256."""
    __tablename__ = "user_sessions"

    id:         Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id:    Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked:    Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped["User"] = relationship(back_populates="sessions")


class Metric(Base):
    __tablename__ = "metrics"

    id:        Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[int] = mapped_column(
        ForeignKey("servers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    pilar:     Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    os_family: Mapped[str] = mapped_column(String(16), nullable=False)

    collected_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    received_at:  Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    request_id:   Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Versão do agente que gerou o payload (NULL = agente antigo, pré-1.0).
    # Essencial para depurar frotas com versões misturadas (ver CONTRATO.md).
    agent_version: Mapped[str | None] = mapped_column(String(20), nullable=True)

    metrics:      Mapped[dict] = mapped_column(_JSON, nullable=False)

    server: Mapped["Server"] = relationship(back_populates="metrics")

    __table_args__ = (
        # Suporta "último estado por pilar" e histórico filtrado por servidor.
        # Há também um índice GIN (jsonb_path_ops) sobre `metrics`, definido apenas
        # na migração 0002 — é específico do PostgreSQL (SQLite dos testes não tem GIN).
        Index("ix_metrics_server_pilar_collected", "server_id", "pilar", "collected_at"),
    )


class NotificationLog(Base):
    """
    Registro de cada transição de estado de um servidor — fonte da verdade
    dos alertas. Alimenta o pop-up do dashboard e uma futura central de alertas.
    """
    __tablename__ = "notification_log"

    id:          Mapped[int] = mapped_column(primary_key=True)
    server_id:   Mapped[int] = mapped_column(
        ForeignKey("servers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    severity:    Mapped[str] = mapped_column(String(8), nullable=False)   # warn|crit|info
    pilar:       Mapped[str | None] = mapped_column(String(20), nullable=True)
    item:        Mapped[str | None] = mapped_column(String(80), nullable=True)
    title:       Mapped[str] = mapped_column(String(160), nullable=False)
    detail:      Mapped[str] = mapped_column(String(500), default="", nullable=False)
    status_from: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status_to:   Mapped[str] = mapped_column(String(20), nullable=False)
    created_at:  Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
