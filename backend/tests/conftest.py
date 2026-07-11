from __future__ import annotations

import os
import pathlib
import tempfile
from collections.abc import AsyncIterator, Callable

# ── Test isolation ──────────────────────────────────────────────────────────
# The HTTP-level tests drive the global `armarius.main.app`, whose engine reads
# `settings.database_url` (default `./armarius.db` — a persisted file). Running
# against that file leaks rows between runs (register → 409). Pin every piece of
# global I/O to a throwaway temp dir BEFORE any `armarius` module is imported, so
# `Settings()` freezes onto the isolated paths.
_TMP = pathlib.Path(tempfile.mkdtemp(prefix="armarius-tests-"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP / 'app.db'}"
os.environ["ARTIFACT_STORE_ROOT"] = str(_TMP / "artifacts")
os.environ["SEED_DEMO"] = "false"

import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from armarius.infrastructure.adapters.echo import EchoAdapter  # noqa: E402
from armarius.infrastructure.database import engine as engine_mod  # noqa: E402
from armarius.infrastructure.database.models import Base  # noqa: E402
from armarius.infrastructure.persistence.unit_of_work import (  # noqa: E402
    SqlAlchemyUnitOfWork,
)
from armarius.main import app  # noqa: E402
from armarius.presentation.container import build_container  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def _isolated_app_db() -> AsyncIterator[None]:
    """Reset the global app schema before each test → full HTTP-level isolation.

    Drops + recreates every table on the shared (temp-file) engine and rebuilds the
    composition root, so each test starts from an empty database regardless of what
    ran before it (or in a previous `pytest` invocation).
    """
    engine = engine_mod.get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    container = build_container()
    # The echo runtime emits ~9 events per wake; with the default 0.4s step delay each
    # invite's setup-push would cost ~3.6s. Re-register a zero-delay echo so test invites
    # (adapter_type "echo") stay instant (issue #63).
    container.registry.register(EchoAdapter(step_delay=0.0))
    app.state.container = container
    yield


@pytest_asyncio.fixture
async def uow_factory(tmp_path) -> AsyncIterator[Callable[[], SqlAlchemyUnitOfWork]]:
    db_path = tmp_path / "test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}", connect_args={"timeout": 30}
    )
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(sessionmaker)

    yield factory
    await engine.dispose()
