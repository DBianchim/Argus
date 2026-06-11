"""
conftest.py — Fixtures de teste

Os testes rodam contra SQLite async em memória (StaticPool mantém uma única
conexão, preservando o schema/dados durante o teste). A dependency get_session
é sobrescrita para usar esse banco — a API nunca toca o PostgreSQL nos testes.
"""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth import hash_token
from app.config import settings
from app.database import Base, get_session
from app.main import app
from app.models import Server

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

AGENT_TOKEN = "test-token"
AGENT_HEADERS = {"Authorization": f"Bearer {AGENT_TOKEN}"}
DASHBOARD_HEADERS = {"Authorization": f"Bearer {settings.dashboard_token}"}


def make_envelope(pilar: str = "operacional", timestamp: str = "2026-06-08T22:00:00Z",
                  hostname: str = "test-host") -> dict:
    """Envelope válido mínimo para POST /ingest."""
    metrics_by_pilar = {
        "operacional": {"cpu": {"usage_pct": 12.0}, "memory": {"usage_pct": 40.0}},
        "backup": {"backup": {"status": "OK"}},
        "acesso": {"summary": {"ok": 1}, "total_findings": 1, "findings": []},
        "logs": {"summary": {"ok": 1}, "total_findings": 1, "findings": []},
    }
    return {
        "timestamp": timestamp,
        "hostname": hostname,
        "os_family": "windows",
        "pilar": pilar,
        "metrics": metrics_by_pilar[pilar],
    }


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def server_id(session_factory) -> int:
    """Registra um servidor com o token conhecido AGENT_TOKEN; retorna seu id."""
    async with session_factory() as session:
        server = Server(
            hostname="test-host",
            os_family="windows",
            api_token_hash=hash_token(AGENT_TOKEN),
            is_active=True,
        )
        session.add(server)
        await session.commit()
        await session.refresh(server)
        return server.id
