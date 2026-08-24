"""Keeping the real-Postgres fixture honest (T025).

`postgres_uow_factory` exists for one reason: exactly-once claiming rests on `SELECT … FOR
UPDATE SKIP LOCKED`, and SQLite has no such thing. A fixture that quietly hands back the
wrong engine — or one whose schema is missing the tables feature 002 added — would let the
claim tests pass while proving nothing, which is worse than not having them.

So the fixture gets its own check: is this really Postgres, are the new tables really
there, and does the lock the whole design rests on really work. Three questions, asked once
here, so T072 can spend its assertions on the race itself.

Skipped when `TEST_DATABASE_URL` is unset — the skip message says how to get one.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from armarius.domain.entities.workspace import Workspace
from armarius.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork


async def test_the_fixture_hands_back_a_real_postgres(
    postgres_engine: AsyncEngine,
) -> None:
    async with postgres_engine.connect() as conn:
        version = await conn.execute(text("SELECT version()"))
        assert "PostgreSQL" in version.scalar_one()


async def test_the_schema_has_the_tables_feature_002_added(
    postgres_engine: AsyncEngine,
) -> None:
    """`create_all` only builds what is registered on the metadata. The daemon models are
    imported at the bottom of `database/models.py` for exactly that reason, and this is the
    check that notices if that import ever goes away."""
    async with postgres_engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")
        )
        tables = {r[0] for r in rows}
    assert {
        "machines",
        "workplaces",
        "run_claims",
        "agent_workplace_bindings",
        "daemon_link_codes",
        "run_event_blobs",
    } <= tables


async def test_the_lock_the_claim_design_rests_on_actually_works(
    postgres_engine: AsyncEngine,
) -> None:
    """The one statement SQLite cannot express. Asked as a plain question of the engine, so
    a failure here points at the database rather than at claim logic that does not exist
    yet."""
    async with postgres_engine.connect() as conn:
        await conn.execute(
            text("SELECT run_id FROM run_claims LIMIT 1 FOR UPDATE SKIP LOCKED")
        )


async def test_the_factory_hands_out_units_of_work_that_really_write(
    postgres_uow_factory: Callable[[], SqlAlchemyUnitOfWork],
) -> None:
    """The rest of the chain: entity → mapper → model → Postgres, and back.

    Two units of work, not one, because that is how T072 will use it — the second only sees
    the row if the first genuinely committed to a shared database rather than to a session
    of its own.
    """
    workspace = Workspace(name="Xưởng thử", slug="xuong-thu")
    async with postgres_uow_factory() as uow:
        await uow.workspaces.add(workspace)
        await uow.commit()

    async with postgres_uow_factory() as uow:
        again = await uow.workspaces.get(workspace.id)
    assert again is not None and again.slug == "xuong-thu"
