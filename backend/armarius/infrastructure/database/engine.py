"""Async SQLAlchemy engine + session factory + schema bootstrap.

SQLite is the default for zero-setup local dev; point DATABASE_URL at Postgres for
production. `create_all` is used for the walking skeleton — Alembic migrations are a
Phase-1 follow-up (see ROADMAP).
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from armarius.infrastructure.database.models import Base, WorkspaceModel
from armarius.shared.config import settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _build_engine() -> AsyncEngine:
    url = settings.database_url
    connect_args: dict = {}
    if url.startswith("sqlite"):
        # Allow cross-task use and wait on the write lock instead of erroring out.
        connect_args = {"timeout": 30}
    return create_async_engine(url, future=True, connect_args=connect_args)


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
        await conn.run_sync(_ensure_added_columns)


def _ensure_added_columns(conn) -> None:  # noqa: ANN001 - sync connection via run_sync
    """`create_all` never ALTERs an existing table, so columns added after a DB was
    first created must be shipped by hand until Alembic lands. One entry per
    late-added nullable column; idempotent (checked against the live schema)."""
    added = [("workspaces", WorkspaceModel.__table__.c.workspace_agent_id)]  # #32
    inspector = inspect(conn)
    for table_name, column in added:
        names = {c["name"] for c in inspector.get_columns(table_name)}
        if column.name not in names:
            col_type = column.type.compile(conn.dialect)
            conn.execute(
                text(f"ALTER TABLE {table_name} ADD COLUMN {column.name} {col_type}")
            )
