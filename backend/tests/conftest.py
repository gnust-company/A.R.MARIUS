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

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

from armarius.infrastructure.adapters.echo import EchoAdapter  # noqa: E402
from armarius.infrastructure.database import engine as engine_mod  # noqa: E402
from armarius.infrastructure.database.engine import (  # noqa: E402
    enforce_sqlite_foreign_keys,
)
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
    # Wakes are fire-and-forget: a run started by the test just finished may still be
    # writing. Let it land before the next test drops the schema out from under it,
    # otherwise the reset races those writes and SQLite reports a locked database.
    await container.wake_engine.drain()


@pytest_asyncio.fixture
async def uow_factory(tmp_path) -> AsyncIterator[Callable[[], SqlAlchemyUnitOfWork]]:
    db_path = tmp_path / "test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}", connect_args={"timeout": 30}
    )
    # Same pragma the app engine sets: a foreign key the deployed database would refuse
    # must be refused here too, or a whole class of bug only ever shows up in production.
    enforce_sqlite_foreign_keys(engine)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    def factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(sessionmaker)

    yield factory
    await engine.dispose()


# ── A real Postgres, for the tests SQLite cannot answer (T025) ──────────────────
#
# Everything above runs on SQLite, and for the vast majority of this suite that is the
# right trade: it is fast, it needs nothing running, and the behaviour under test does not
# depend on the engine.
#
# Claiming a run is the exception. Exactly-once claiming rests on `SELECT … FOR UPDATE SKIP
# LOCKED`, which SQLite does not have — it serialises writers with a single database-wide
# lock instead. A claim test on SQLite therefore proves that one writer at a time works,
# which was never the question; the race it is meant to catch cannot even be staged. So
# those tests run against the same `postgres:16-alpine` the stack deploys on, or they do
# not run at all — and they say which, rather than passing quietly on the wrong engine.

_TEST_DB_URL_ENV = "TEST_DATABASE_URL"

_HOW_TO_GET_ONE = f"""{_TEST_DB_URL_ENV} is not set, so this test has nothing real to run on.

Either point it at the stack's own database, once:

    docker compose up -d db
    docker compose exec db createdb -U armarius armarius_test
    export {_TEST_DB_URL_ENV}=postgresql+psycopg://armarius:armarius@localhost:5434/armarius_test

or at a throwaway one that disappears with the container:

    docker run -d --rm --name armarius-pgtest -p 5434:5432 \\
        -e POSTGRES_USER=armarius -e POSTGRES_PASSWORD=armarius \\
        -e POSTGRES_DB=armarius_test postgres:16-alpine
    export {_TEST_DB_URL_ENV}=postgresql+psycopg://armarius:armarius@localhost:5434/armarius_test
"""


@pytest_asyncio.fixture
async def postgres_engine() -> AsyncIterator[AsyncEngine]:
    """A real Postgres with an empty schema, or a skip that says how to get one."""
    url = os.environ.get(_TEST_DB_URL_ENV, "").strip()
    if not url:
        pytest.skip(_HOW_TO_GET_ONE)

    # This fixture drops every table it can see. Pointing it at the database the stack
    # actually runs on would wipe real work, and the compose database is one `export` typo
    # away — so the name has to say out loud that it is disposable.
    database = url.rsplit("/", 1)[-1].split("?", 1)[0]
    if not database.endswith("_test"):
        raise AssertionError(
            f"{_TEST_DB_URL_ENV} points at {database!r}, and this fixture drops every "
            "table in it. Point it at a database whose name ends in `_test`."
        )

    # No connection pool. The tests this exists for open several connections on purpose to
    # make them contend; a pool that hands the same connection back twice would quietly
    # turn that race into a queue, and the test would pass having proved nothing.
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def postgres_uow_factory(
    postgres_engine: AsyncEngine,
) -> Callable[[], SqlAlchemyUnitOfWork]:
    """A unit-of-work factory over that Postgres.

    A *factory*, not a unit of work: the tests this exists for need several of them racing
    each other, and handing out one shared session would serialise exactly the contention
    they are trying to create.
    """
    sessionmaker = async_sessionmaker(
        postgres_engine, expire_on_commit=False, class_=AsyncSession
    )
    return lambda: SqlAlchemyUnitOfWork(sessionmaker)
