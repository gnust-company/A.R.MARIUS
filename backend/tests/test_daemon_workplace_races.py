"""Two workplace syncs from the same machine at the same time, on a real Postgres (FR-002).

A daemon that retried a sync it thought had timed out has two of them in flight over the same
machine. Both read "this machine has no workplaces yet", both insert `claude_code`, and without
the unique index over `(machine_id, cli_kind)` the machine ends up with the same CLI listed
twice — two workplaces an agent could be bound to, only one of which anyone updates again.

Here as its own file, not in `test_daemon_workplaces.py`, for the reason written out at the top
of `test_daemon_enrollment_races.py`: SQLite serialises writers behind one database-wide lock,
so whether two callers actually overlap depends on where their coroutines yield. A detector
that catches the bug some of the time proves nothing about the runs where it did not. Two real
connections make the overlap real.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from armarius.domain.entities.user import User
from armarius.domain.entities.workspace import Workspace
from armarius.infrastructure.daemon.enrollment import (
    DaemonEnrollmentService,
    MachineIdentity,
)
from armarius.infrastructure.daemon.models import WorkplaceModel
from armarius.infrastructure.daemon.workplaces import (
    DaemonWorkplaceService,
    ReportedWorkplace,
)
from armarius.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork


@pytest_asyncio.fixture
async def sessions(
    postgres_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A session factory over the real engine — `NullPool`, so each session is its own
    connection. A pool handing both callers the same one would turn the race into a queue."""
    yield async_sessionmaker(
        postgres_engine, expire_on_commit=False, class_=AsyncSession
    )


async def _a_linked_machine(
    sessions: async_sessionmaker[AsyncSession],
) -> MachineIdentity:
    """One machine, admitted through the real device flow rather than inserted by hand."""
    uow = SqlAlchemyUnitOfWork(sessions)
    async with uow:
        user = User.create(
            email="mot@example.com",
            username="mot",
            full_name="mot",
            password="password1234",
        )
        await uow.users.add(user)
        workspace = Workspace(name="mot", slug="mot", owner_user_id=str(user.id))
        await uow.workspaces.add(workspace)
        await uow.commit()

    enrollment = DaemonEnrollmentService(sessions)
    started = await enrollment.start_link(
        platform="linux", daemon_version="0.1.0", hostname="box"
    )
    await enrollment.approve_link(
        started.code, workspace_id=workspace.id, approved_by_user_id=user.id
    )
    issued = await enrollment.poll_link(started.code)
    assert issued is not None
    identity = await enrollment.authenticate(issued.token)
    assert identity is not None
    return identity


async def test_two_syncs_at_once_leave_one_workplace_per_cli(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    machine = await _a_linked_machine(sessions)
    service = DaemonWorkplaceService(sessions)
    reported = [
        ReportedWorkplace(cli_kind="claude_code", cli_version="2.1.226"),
        ReportedWorkplace(cli_kind="gemini", cli_version="0.56.0"),
    ]

    async def sync() -> list:
        return await service.sync(machine, reported=reported, symlink_capable=True)

    both = await asyncio.gather(sync(), sync())

    async with sessions() as session:
        rows = await session.scalar(select(func.count()).select_from(WorkplaceModel))
    assert rows == 2, "one workplace per CLI, however many syncs arrived at once"

    # And both callers were answered — a losing sync retries and succeeds, it does not fail.
    for answered in both:
        assert sorted(w.cli_kind for w in answered) == ["claude_code", "gemini"]
        assert all(w.ready for w in answered)
