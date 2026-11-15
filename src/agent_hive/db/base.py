"""Database layer: async engine/session factory and schema bootstrap.

Primary target is PostgreSQL (``postgresql+asyncpg://...``). The exact same
SQLAlchemy models run on SQLite (``sqlite+aiosqlite://...``) so the test
suite and local evaluation require no external infrastructure.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from agent_hive.config.settings import get_settings
from agent_hive.core.logging import get_logger

log = get_logger("agent_hive.db")

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine (created lazily)."""
    global _engine
    if _engine is None:
        url = get_settings().database_url
        _engine = create_async_engine(url, echo=False, pool_pre_ping=True)
        log.info("Database engine created for %s", url.split("://")[0])
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory (created lazily)."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), expire_on_commit=False
        )
    return _session_factory


async def create_all() -> None:
    """Create all tables (idempotent). Alembic manages production migrations."""
    from agent_hive.db import models  # noqa: F401 — ensure metadata is loaded

    async with get_engine().begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
