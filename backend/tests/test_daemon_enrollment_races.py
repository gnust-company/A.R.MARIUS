"""The two races in the link flow, proved on a real Postgres (FR-001).

Both of them are the same shape: read *nobody has done this yet*, then write. Between the
read and the write another caller can do the whole thing, and then both writes land.

  * two approvals at once — a double-click, a client retry, or two people who both know the
    code. The bad outcome is silent: the first approver is told 200 while their machine
    quietly joins the other person's workspace.
  * two polls at once — one daemon retrying a poll it thought had timed out. The bad outcome
    is a second machine row nobody will ever heartbeat for, which shows up on the board as a
    dead machine the operator never installed.

They live here, apart from the rest of the suite, because **SQLite cannot be trusted to
stage them**. It serialises writers behind one database-wide lock, so whether the two
callers actually overlap comes down to where their coroutines happen to yield. Measured,
not assumed: with the guards reverted, the SQLite version of the approval race caught the
bug on one run of the file and missed it on another, depending only on which other tests
ran alongside it. A detector that reports the bug some of the time is not a proof of its
absence, so the proof lives here, where two real connections make the overlap real — on
Postgres the same revert fails every time.

The SQLite twins in `test_daemon_enrollment.py` stay where they are. They can only ever go
red when the bug is genuinely there, so they cost nothing and occasionally catch it early;
they are simply not the thing being relied on.

These talk to the service directly on two connections, and skip with instructions when
there is no Postgres to talk to.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from armarius.domain.entities.user import User
from armarius.domain.entities.workspace import Workspace
from armarius.infrastructure.daemon.enrollment import DaemonEnrollmentService
from armarius.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from armarius.shared.errors import Conflict, NotFound


@pytest_asyncio.fixture
async def sessions(postgres_engine: AsyncEngine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A session factory over the real engine.

    The engine is pooled with `NullPool`, so every session here is its own connection —
    which is the whole point: a pool that handed the same connection to both callers would
    turn the race back into a queue.
    """
    yield async_sessionmaker(postgres_engine, expire_on_commit=False, class_=AsyncSession)


async def _two_patrons(
    sessions: async_sessionmaker[AsyncSession],
) -> tuple[tuple[User, Workspace], tuple[User, Workspace]]:
    """Two people who each own a workspace — the two who might approve the same code."""
    made: list[tuple[User, Workspace]] = []
    uow = SqlAlchemyUnitOfWork(sessions)
    async with uow:
        for name in ("mot", "hai"):
            user = User.create(
                email=f"{name}@example.com",
                username=name,
                full_name=name,
                password="password1234",
            )
            await uow.users.add(user)
            workspace = Workspace(name=name, slug=name, owner_user_id=str(user.id))
            await uow.workspaces.add(workspace)
            made.append((user, workspace))
        await uow.commit()
    return made[0], made[1]


async def test_two_approvals_at_once_leave_exactly_one_approver(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """One 200 and one refusal — never two people each told the machine is theirs."""
    service = DaemonEnrollmentService(sessions)
    (first, first_ws), (second, second_ws) = await _two_patrons(sessions)
    started = await service.start_link(platform="linux", daemon_version="0.1.0", hostname="box")

    async def approve(user: User, workspace: Workspace) -> Workspace | Exception:
        try:
            await service.approve_link(
                started.code, workspace_id=workspace.id, approved_by_user_id=user.id
            )
            return workspace
        except Conflict as refused:
            return refused

    outcomes = await asyncio.gather(
        approve(first, first_ws), approve(second, second_ws), return_exceptions=False
    )
    winners = [o for o in outcomes if isinstance(o, Workspace)]
    refusals = [o for o in outcomes if isinstance(o, Conflict)]
    assert len(winners) == 1, outcomes
    assert len(refusals) == 1, outcomes

    # …and the machine goes to the workspace of whoever was told they approved it.
    issued = await service.poll_link(started.code)
    assert issued is not None
    assert issued.workspace_id == winners[0].id


async def test_two_polls_at_once_mint_exactly_one_token(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """One token and one machine row — a second would be a machine nobody ever installed."""
    service = DaemonEnrollmentService(sessions)
    (patron, workspace), _ = await _two_patrons(sessions)
    started = await service.start_link(platform="linux", daemon_version="0.1.0", hostname="box")
    await service.approve_link(
        started.code, workspace_id=workspace.id, approved_by_user_id=patron.id
    )

    async def poll() -> object:
        try:
            return await service.poll_link(started.code)
        except NotFound as refused:
            return refused

    outcomes = await asyncio.gather(poll(), poll())
    issued = [o for o in outcomes if o is not None and not isinstance(o, NotFound)]
    refused = [o for o in outcomes if isinstance(o, NotFound)]
    assert len(issued) == 1, outcomes
    assert len(refused) == 1, outcomes

    async with sessions() as session:
        from sqlalchemy import func, select

        from armarius.infrastructure.daemon.models import MachineModel

        machines = await session.scalar(select(func.count()).select_from(MachineModel))
    assert machines == 1, "a second machine row is one nobody will ever heartbeat for"

    # The losing poll builds a token and a machine row before it finds out it lost, and only
    # the rollback keeps that pair out of the database. So the one token that was handed out
    # has to be the one that works.
    won = issued[0]
    assert won is not None
    identity = await service.authenticate(won.token)  # type: ignore[union-attr]
    assert identity is not None
    assert identity.machine_id == won.machine_id  # type: ignore[union-attr]


async def test_only_a_token_this_server_issued_opens_anything(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The floor under the race tests: a token that came out of the flow works, and a
    plausible-looking string that did not is nobody."""
    service = DaemonEnrollmentService(sessions)
    (patron, workspace), _ = await _two_patrons(sessions)
    started = await service.start_link(platform="linux", daemon_version="0.1.0", hostname="box")
    await service.approve_link(
        started.code, workspace_id=workspace.id, approved_by_user_id=patron.id
    )
    issued = await service.poll_link(started.code)
    assert issued is not None

    assert await service.authenticate(issued.token) is not None
    assert await service.authenticate(f"armd_{uuid4().hex}") is None
