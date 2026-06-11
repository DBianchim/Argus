"""
database.py — Engine async, sessão e base declarativa do SQLAlchemy 2.0

Fornece:
    - Base: classe declarativa raiz dos modelos ORM
    - engine: AsyncEngine conectado ao DATABASE_URL
    - get_session: dependency do FastAPI que entrega uma AsyncSession por request
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    """Base declarativa de todos os modelos ORM."""


engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,   # valida a conexão antes de usar (evita conexões mortas)
)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency: abre uma sessão por request e a fecha ao final."""
    async with SessionLocal() as session:
        yield session
