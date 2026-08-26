"""One machine asking twice, proved on a real Postgres (T045, FR-054, FR-054a, FR-055e).

FR-054b names the race precisely, and the precision matters: it is **not** two machines
fighting over one run. Every agent is bound to one place, so no two machines ever see the
same work. It is one machine asking twice, and there are exactly three ways that happens — a
push landing on top of a poll, a reply lost on the way back so the daemon repeats itself, and
two daemons alive for a moment during an upgrade. All three ask with the same eyes, over the
same workplaces, at nearly the same instant.

`SELECT` the free work, then `UPDATE` it to yours, and both asks read the same row as free
before either writes. Both come back holding it; the machine starts the same work twice, in
two working directories, with two agents writing to one task.

**Why this file is Postgres-only.** SQLite serialises writers behind one database-wide lock,
so whether the two asks overlap at all comes down to where their coroutines happen to yield.
A detector that stages the race only sometimes is not a proof that the race is closed. Two
real connections on a real Postgres make the overlap real, and `FOR UPDATE SKIP LOCKED` — the
half of the statement SQLite has no equivalent for — is the half being tested. The suite's
SQLite twin in `test_run_claim_door.py` asks the sequential version of the same question and
stays where it is; it is simply not what the guarantee rests on.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from armarius.domain.entities.run import RunStatus
from armarius.domain.entities.user import User
from armarius.domain.entities.workspace import Workspace
from armarius.infrastructure.daemon.claim import DaemonClaimService
from armarius.infrastructure.daemon.enrollment import MachineIdentity
from armarius.infrastructure.daemon.models import (
    MachineModel,
    RunClaimModel,
    WorkplaceModel,
)
from armarius.infrastructure.database.models import RunModel
from armarius.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from armarius.shared.clock import utcnow


@pytest_asyncio.fixture
async def sessions(
    postgres_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A session factory over the real engine.

    The engine is pooled with `NullPool`, so every session here is its own connection —
    which is the whole point: a pool handing the same connection to both askers would turn
    the race back into a queue and the test would prove nothing.
    """
    yield async_sessionmaker(postgres_engine, expire_on_commit=False, class_=AsyncSession)


async def _one_machine(
    sessions: async_sessionmaker[AsyncSession], *, waiting: int, ceiling: int
) -> tuple[MachineIdentity, UUID, list[UUID]]:
    """A workspace with one machine, one workplace on it, and `waiting` runs on the shelf."""
    uow = SqlAlchemyUnitOfWork(sessions)
    async with uow:
        person = User.create(
            email="patron@example.com",
            username="patron",
            full_name="Patron",
            password="password1234",
        )
        await uow.users.add(person)
        workspace = Workspace(name="WS", slug="ws", owner_user_id=str(person.id))
        await uow.workspaces.add(workspace)
        await uow.commit()

    workspace_id = UUID(str(workspace.id))
    machine_id, workplace_id = uuid4(), uuid4()
    now = utcnow()
    runs: list[UUID] = []
    async with sessions() as session:
        session.add(
            MachineModel(
                id=machine_id,
                workspace_id=workspace_id,
                owner_user_id=UUID(str(person.id)),
                display_name="box",
                token_hash=f"test-{uuid4().hex}",
                max_concurrent=ceiling,
                last_heartbeat_at=now,
                created_at=now,
            )
        )
        session.add(
            WorkplaceModel(
                id=workplace_id,
                workspace_id=workspace_id,
                machine_id=machine_id,
                cli_kind="claude_code",
                ready=True,
                created_at=now,
            )
        )
        await session.flush()
        for _ in range(waiting):
            run_id = uuid4()
            runs.append(run_id)
            session.add(
                RunModel(
                    id=run_id,
                    marius_id=uuid4(),
                    adapter_type="daemon",
                    status=RunStatus.QUEUED.value,
                    created_at=now,
                )
            )
        # The runs have to exist before anything can point at them, and `runs` is not a
        # table this module's models declare — so the ordering is written out here rather
        # than left to whatever order the flush happens to pick.
        await session.flush()
        for run_id in runs:
            session.add(
                RunClaimModel(
                    run_id=run_id,
                    workspace_id=workspace_id,
                    workplace_id=workplace_id,
                )
            )
        await session.commit()

    machine = MachineIdentity(
        machine_id=machine_id,
        workspace_id=workspace_id,
        owner_user_id=UUID(str(person.id)),
        token_expires_at=None,
    )
    return machine, workplace_id, runs


async def test_two_asks_at_the_same_instant_take_the_work_once(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """One grant and one empty hand — never the same run in two answers."""
    machine, workplace_id, runs = await _one_machine(sessions, waiting=1, ceiling=4)
    service = DaemonClaimService(sessions)

    both = await asyncio.gather(
        service.claim(machine, workplace_ids=[workplace_id], free_slots=4),
        service.claim(machine, workplace_ids=[workplace_id], free_slots=4),
    )

    granted = [g.run_id for answer in both for g in answer]
    assert granted == runs, both
    assert len(granted) == 1, "cùng một lượt chạy được trao hai lần"


async def test_taking_several_at_once_never_hands_the_same_one_twice(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """FR-055e: asking for many is the same statement as asking for one.

    Read the free slots, pick N, then assign them, and the race that asking for one closed
    is reopened by asking for three — the two askers pick overlapping sets before either
    writes. Six waiting, two askers wanting three each: six grants, all different.
    """
    machine, workplace_id, runs = await _one_machine(sessions, waiting=6, ceiling=6)
    service = DaemonClaimService(sessions)

    both = await asyncio.gather(
        service.claim(machine, workplace_ids=[workplace_id], free_slots=3),
        service.claim(machine, workplace_ids=[workplace_id], free_slots=3),
    )

    granted = [g.run_id for answer in both for g in answer]
    assert len(granted) == len(set(granted)), "một lượt chạy lọt vào hai câu trả lời"
    assert set(granted) <= set(runs)


async def test_no_run_is_ever_left_answering_to_two_machines(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The invariant behind all of it, checked in the storage rather than in the answers.

    A run is either free or held by exactly one machine, with a deadline. Never both, and
    never held with no deadline before it has started — that state would be a grip nothing
    can ever loosen.
    """
    machine, workplace_id, _ = await _one_machine(sessions, waiting=4, ceiling=4)
    service = DaemonClaimService(sessions)

    await asyncio.gather(
        *[
            service.claim(machine, workplace_ids=[workplace_id], free_slots=2)
            for _ in range(4)
        ]
    )

    async with sessions() as session:
        rows = (await session.execute(select(RunClaimModel))).scalars().all()
        held = await session.scalar(
            select(func.count())
            .select_from(RunClaimModel)
            .where(RunClaimModel.machine_id.is_not(None))
        )
    assert held == 4, "bốn việc chờ, bốn chỗ trống — máy phải cầm hết"
    for row in rows:
        assert (row.machine_id is None) == (row.claim_expires_at is None), (
            "vừa rảnh vừa có chủ, hoặc có chủ mà không có hạn"
        )


async def test_the_ceiling_holds_even_when_every_ask_arrives_together(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Four asks, each honestly reporting room, on a machine allowed two.

    The ceiling is only worth having if it survives the moment it is most likely to be
    breached: several asks in flight at once, each reading a machine that still looked
    half-empty when it started.
    """
    machine, workplace_id, _ = await _one_machine(sessions, waiting=8, ceiling=2)
    service = DaemonClaimService(sessions)

    answers = await asyncio.gather(
        *[
            service.claim(machine, workplace_ids=[workplace_id], free_slots=8)
            for _ in range(4)
        ]
    )

    granted = [g.run_id for answer in answers for g in answer]
    assert len(granted) <= 2, f"trần là 2 mà máy cầm {len(granted)}"


async def test_offering_the_same_run_twice_at_once_leaves_one_row(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """Đặt việc lên kệ hai lần cùng lúc chỉ được ra một dòng, và không được nổ.

    Chỗ đặt việc đọc trước rồi mới ghi, mà giữa hai bước ấy có khe. Khoá chính là thứ
    thật sự phân xử: ai tới trước giữ dòng, người tới sau được cơ sở dữ liệu nói cho biết
    và lui ra lặng lẽ — chứ không phải ném lỗi lên đường gửi việc.
    """
    machine, workplace_id, _ = await _one_machine(sessions, waiting=0, ceiling=4)
    service = DaemonClaimService(sessions)
    run_id = uuid4()
    async with sessions() as session:
        session.add(
            RunModel(
                id=run_id,
                marius_id=uuid4(),
                adapter_type="daemon",
                status=RunStatus.QUEUED.value,
                created_at=utcnow(),
            )
        )
        await session.commit()

    await asyncio.gather(
        *[
            service.offer(
                run_id=run_id,
                workspace_id=machine.workspace_id,
                workplace_id=workplace_id,
            )
            for _ in range(4)
        ]
    )

    async with sessions() as session:
        rows = await session.scalar(
            select(func.count())
            .select_from(RunClaimModel)
            .where(RunClaimModel.run_id == run_id)
        )
    assert rows == 1, f"một lượt chạy mà có {rows} dòng trên kệ"

    granted = await service.claim(machine, workplace_ids=[workplace_id], free_slots=4)
    assert [g.run_id for g in granted] == [run_id], (
        "đặt trùng làm việc biến mất khỏi kệ hoặc được phát ra hai lần"
    )
