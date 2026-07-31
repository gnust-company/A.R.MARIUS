"""Async SQLAlchemy engine + session factory + schema bootstrap.

SQLite is the default for zero-setup local dev; point DATABASE_URL at Postgres for
production. `init_db` (create_all) is a TEST/dev bootstrap only — the deployed stack
migrates exclusively through `alembic upgrade head` in docker-entrypoint.sh, so every
model change MUST ship with an Alembic migration (issue #38 is what happens otherwise;
tests/test_migration_schema_parity.py enforces it).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from armarius.infrastructure.database.models import Base
from armarius.shared.config import settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def enforce_sqlite_foreign_keys(engine: AsyncEngine) -> None:
    """Make SQLite reject broken foreign keys, the way PostgreSQL always has.

    SQLite ships with FK enforcement **off**. That is not a harmless difference: an
    insert-ordering bug that PostgreSQL refuses outright is swallowed silently here, so a
    fully green test suite can hide a defect that only surfaces on the composed stack —
    which is exactly how the plan-item insert bug of Đợt 1 reached a real run. Turning the
    pragma on makes the test database behave like the deployed one.
    """
    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragma(dbapi_connection: Any, _record: Any) -> None:  # noqa: ANN401
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _build_engine() -> AsyncEngine:
    url = settings.database_url
    connect_args: dict = {}
    if url.startswith("sqlite"):
        # Allow cross-task use and wait on the write lock instead of erroring out.
        connect_args = {"timeout": 30}
    engine = create_async_engine(url, future=True, connect_args=connect_args)
    if url.startswith("sqlite"):
        enforce_sqlite_foreign_keys(engine)
    return engine


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _sessionmaker


async def init_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        if settings.database_url.startswith("sqlite"):
            await conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
        await conn.run_sync(Base.metadata.create_all)
