"""Durable wake coalescing (spec 001 FR-050) — the invariant lives in the database.

At most **one** pending wake and **one** live run per *(agent, task)*. Today that is a
dictionary inside one process, which means two things are untrue the moment reality gets
messy: a second worker process would happily start a second run for the same pair, and a
restart forgets everything it was holding — the first cause to arrive afterwards opens a
duplicate run against an agent that is still mid-turn.

So the tests here refuse to accept an answer that only holds inside one live object:

  * one drives the storage layer directly, so the constraint has to be in the schema;
  * one throws away the engine and builds a **new** one over the same database, which is
    exactly what a restart looks like from the data's point of view.

An implementation that keeps the in-process dictionary passes neither.
"""

from __future__ import annotations

import asyncio

import pytest

from armarius.application.ports.adapter import (
    AdapterCapabilities,
    Diagnostics,
    ExecContext,
    ExecResult,
    MariusAdapter,
)
from armarius.application.use_cases.mariuses import MariusService
from armarius.application.use_cases.tasks import TaskService
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.entities.run import RunStatus, WakeSource
from armarius.domain.entities.wakeup import (
    PENDING_WAKEUP_STATUSES,
    WakePairBusyError,
    WakeupRequest,
    WakeupStatus,
)
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.database.models import WakeupModel
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus
from armarius.shared.clock import utcnow
from tests.support.projects import force_phase


class BlockingAdapter(MariusAdapter):
    """An agent turn that stays open until the test lets it finish.

    Coalescing is only observable while a run is actually in flight; an adapter that
    returns immediately would let every cause open and close its own run in sequence and
    the test would pass against a broken implementation.
    """

    type = "blocking"
    capabilities = AdapterCapabilities(resumable=True, streaming=False, transport="process")

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.started = asyncio.Event()
        self.turns = 0
        self.prompts: list[str] = []

    async def execute(self, ctx: ExecContext) -> ExecResult:
        self.turns += 1
        self.prompts.append(ctx.prompt)
        self.started.set()
        await self.release.wait()
        return ExecResult(status=RunStatus.COMPLETED, session_params={"session_id": "s1"})

    async def test_environment(self, config: dict) -> Diagnostics:
        return Diagnostics(ok=True)


def _engine(uow_factory, adapter: MariusAdapter) -> WakeEngine:
    registry = InMemoryAdapterRegistry()
    registry.register(adapter)
    return WakeEngine(uow_factory, registry, InMemoryEventBus(), run_timeout_seconds=30)


async def _world(uow_factory):
    """A project past the planning gate, one agent, one task assigned to nobody."""
    workspaces = WorkspaceService(uow_factory)
    mariuses = MariusService(uow_factory)
    ws = await workspaces.create_workspace("WS")
    project = await workspaces.create_project(ws.id, "P")
    await force_phase(uow_factory, project.id)
    alice = await mariuses.register(
        workspace_id=ws.id,
        name="Alice",
        role="Backend",
        skills=[],
        adapter_type="blocking",
        adapter_config={},
    )
    tasks = TaskService(uow_factory, _engine(uow_factory, BlockingAdapter()))
    task = await tasks.create(
        project_id=project.id,
        title="Kết xuất báo cáo",
        description="Gom số liệu tháng rồi kết xuất ra tệp bảng tính.",
    )
    # A backlog task with no stated reason draws bounded self-nudges when a run ends, which
    # would add runs these tests never asked for. Give it a reason so the self-wake policy
    # stays quiet and every run counted here is one the test actually caused.
    async with uow_factory() as uow:
        seeded = await uow.tasks.get(task.id)
        assert seeded is not None
        seeded.status_reason = "chờ người phụ trách"
        await uow.tasks.update(seeded)
        await uow.commit()
    return project, alice, task


async def _pending(uow_factory, marius_id, task_id) -> list[WakeupRequest]:
    async with uow_factory() as uow:
        rows = await uow.wakeups.list_active_for(marius_id, task_id)
    return [w for w in rows if w.status in PENDING_WAKEUP_STATUSES]


# ── the invariant is in the schema, not in a running object ─────────────────────


def test_the_pending_wake_constraint_lives_in_the_schema() -> None:
    """The refusal has to come from the database. A check in application code would be
    skipped by anything that writes directly — and by a second process entirely."""
    index = next(
        ix for ix in WakeupModel.__table__.indexes
        if ix.name == "uq_wakeup_pending_per_agent_task"
    )
    assert index.unique
    assert [c.name for c in index.columns] == ["marius_id", "task_id"]
    # Partial: settled wakes must fall outside it, or an agent could be woken for a given
    # task exactly once ever.
    assert index.dialect_options["sqlite"]["where"] is not None
    assert index.dialect_options["postgresql"]["where"] is not None


async def test_the_database_itself_refuses_a_second_pending_wake(uow_factory) -> None:
    """T103. Written against the repository, with no wake engine in the picture: whatever
    guards this has to survive code that does not go through the engine."""
    _project, alice, task = await _world(uow_factory)

    async with uow_factory() as uow:
        await uow.wakeups.add(
            WakeupRequest(
                marius_id=alice.id,
                task_id=task.id,
                source=WakeSource.COMMENT,
                status=WakeupStatus.DISPATCHED,
                created_at=utcnow(),
            )
        )
        await uow.commit()

    with pytest.raises(WakePairBusyError):
        async with uow_factory() as uow:
            await uow.wakeups.add(
                WakeupRequest(
                    marius_id=alice.id,
                    task_id=task.id,
                    source=WakeSource.MENTION,
                    status=WakeupStatus.QUEUED,
                    created_at=utcnow(),
                )
            )
            await uow.commit()


async def test_a_settled_wake_leaves_room_for_the_next_one(uow_factory) -> None:
    """The constraint covers *pending* wakes only. If it covered finished ones too, an
    agent could never be woken twice for the same task in its whole life."""
    _project, alice, task = await _world(uow_factory)

    async with uow_factory() as uow:
        first = await uow.wakeups.add(
            WakeupRequest(
                marius_id=alice.id,
                task_id=task.id,
                source=WakeSource.COMMENT,
                status=WakeupStatus.DISPATCHED,
                created_at=utcnow(),
            )
        )
        await uow.commit()

    async with uow_factory() as uow:
        first.status = WakeupStatus.DONE
        first.updated_at = utcnow()
        await uow.wakeups.update(first)
        await uow.commit()

    async with uow_factory() as uow:
        await uow.wakeups.add(
            WakeupRequest(
                marius_id=alice.id,
                task_id=task.id,
                source=WakeSource.MENTION,
                status=WakeupStatus.QUEUED,
                created_at=utcnow(),
            )
        )
        await uow.commit()

    assert len(await _pending(uow_factory, alice.id, task.id)) == 1


async def test_three_causes_at_once_produce_one_run_naming_all_three(uow_factory) -> None:
    """Quickstart scenario 4 step 2. The agent must see one wake, and that wake must not
    hide the other two causes — losing them is how a mention silently becomes a comment."""
    _project, alice, task = await _world(uow_factory)
    adapter = BlockingAdapter()
    engine = _engine(uow_factory, adapter)

    first = await engine.enqueue(
        marius_id=alice.id, task_id=task.id, source=WakeSource.COMMENT,
        reason="Bob bình luận trên đầu việc",
    )
    await asyncio.wait_for(adapter.started.wait(), timeout=5)
    second, third = await asyncio.gather(
        engine.enqueue(
            marius_id=alice.id, task_id=task.id, source=WakeSource.MENTION,
            reason="Bob nhắc tên bạn",
        ),
        engine.enqueue(
            marius_id=alice.id, task_id=task.id, source=WakeSource.IDLE_REMINDER,
            reason="đầu việc im quá lâu",
        ),
    )

    assert second == first and third == first, "mỗi cớ mở một lượt chạy riêng"

    async with uow_factory() as uow:
        runs = await uow.runs.list_by_task(task.id)
    assert len(runs) == 1, [str(r.wake_source) for r in runs]

    merged = (await _pending(uow_factory, alice.id, task.id))[0]
    for cause in ("Bob bình luận trên đầu việc", "Bob nhắc tên bạn", "đầu việc im quá lâu"):
        assert cause in (merged.reason or ""), merged.reason
    # T112: the merged wake carries the strongest cause, not whichever arrived first.
    assert merged.source == WakeSource.MENTION, merged.source

    adapter.release.set()
    await engine.drain()


async def test_a_restart_does_not_open_a_second_run(uow_factory) -> None:
    """T104. A fresh engine over the same database is exactly what a restart looks like.
    An in-process dictionary is empty here, so a duplicate run is the failure mode."""
    _project, alice, task = await _world(uow_factory)
    adapter = BlockingAdapter()
    before = _engine(uow_factory, adapter)

    run_id = await before.enqueue(
        marius_id=alice.id, task_id=task.id, source=WakeSource.COMMENT,
        reason="Bob bình luận trên đầu việc",
    )
    await asyncio.wait_for(adapter.started.wait(), timeout=5)

    # … the container restarts. Nothing is carried across but the database.
    after = _engine(uow_factory, BlockingAdapter())
    again = await after.enqueue(
        marius_id=alice.id, task_id=task.id, source=WakeSource.MENTION,
        reason="Bob nhắc tên bạn",
    )

    assert again == run_id, "khởi động lại xong là mở lượt chạy thứ hai"
    async with uow_factory() as uow:
        runs = await uow.runs.list_by_task(task.id)
    assert len(runs) == 1
    assert len(await _pending(uow_factory, alice.id, task.id)) == 1

    adapter.release.set()
    await before.drain()
    await after.drain()


async def test_a_cause_that_arrived_mid_run_is_reconsidered_when_the_run_ends(
    uow_factory,
) -> None:
    """FR-050 last clause. The running turn absorbs the cause — but 'absorbed' must not
    mean 'dropped': when the turn ends the system looks again and wakes if it still owes
    one. Otherwise a question asked one second too late is never answered."""
    _project, alice, task = await _world(uow_factory)
    adapter = BlockingAdapter()
    engine = _engine(uow_factory, adapter)

    await engine.enqueue(
        marius_id=alice.id, task_id=task.id, source=WakeSource.COMMENT,
        reason="Bob bình luận trên đầu việc",
    )
    await asyncio.wait_for(adapter.started.wait(), timeout=5)
    await engine.enqueue(
        marius_id=alice.id, task_id=task.id, source=WakeSource.MENTION,
        reason="Bob nhắc tên bạn giữa lúc đang chạy",
    )

    adapter.release.set()
    await engine.drain()

    async with uow_factory() as uow:
        runs = await uow.runs.list_by_task(task.id)
    assert len(runs) == 2, "cớ đến giữa lượt chạy bị nuốt mất"
    follow_up = sorted(runs, key=lambda r: r.created_at or utcnow())[-1]
    assert "Bob nhắc tên bạn giữa lúc đang chạy" in (follow_up.trigger_detail or "")


async def test_the_packet_that_went_out_is_kept(uow_factory) -> None:
    """What an agent was actually told is worth keeping. Rebuilding it later from the
    current code answers a different question — the builder has changed since."""
    _project, alice, task = await _world(uow_factory)
    adapter = BlockingAdapter()
    engine = _engine(uow_factory, adapter)

    await engine.enqueue(
        marius_id=alice.id, task_id=task.id, source=WakeSource.COMMENT,
        reason="Bob bình luận trên đầu việc",
    )
    await asyncio.wait_for(adapter.started.wait(), timeout=5)

    sent = (await _pending(uow_factory, alice.id, task.id))[0].prompt or ""
    assert "## Project context" in sent
    assert "## Where to put your work and how to report status" in sent
    assert "Bob bình luận trên đầu việc" in sent

    adapter.release.set()
    await engine.drain()


async def test_a_cause_still_coalesces_when_the_run_outlived_its_wake_row(
    uow_factory,
) -> None:
    """The shape the service is left in when it is told to stop mid-turn: the wake was
    settled on the way out, the run it was driving never got to finish.

    Reading only the wake row here says "the pair is free", the engine tries to open a
    second run, and the index refuses it — which turns an ordinary restart into an error
    on the next comment. It has to read the run.
    """
    _project, alice, task = await _world(uow_factory)
    adapter = BlockingAdapter()
    engine = _engine(uow_factory, adapter)

    run_id = await engine.enqueue(
        marius_id=alice.id, task_id=task.id, source=WakeSource.COMMENT,
        reason="Bob bình luận trên đầu việc",
    )
    await asyncio.wait_for(adapter.started.wait(), timeout=5)
    async with uow_factory() as uow:
        for w in await uow.wakeups.list_active_for(alice.id, task.id):
            w.status = WakeupStatus.DONE
            w.updated_at = utcnow()
            await uow.wakeups.update(w)
        await uow.commit()

    again = await engine.enqueue(
        marius_id=alice.id, task_id=task.id, source=WakeSource.MENTION,
        reason="Bob nhắc tên bạn",
    )
    assert again == run_id

    async with uow_factory() as uow:
        runs = await uow.runs.list_by_task(task.id)
        absorbed = await uow.wakeups.list_coalesced_into(run_id)
    assert len(runs) == 1
    # The cause is not lost just because there was no row to merge it into: it is recorded
    # against the run, which is what the end-of-run re-evaluation reads.
    assert [w.reason for w in absorbed] == ["Bob nhắc tên bạn"]

    adapter.release.set()
    await engine.drain()


async def test_a_turn_cut_short_hands_the_pair_back(uow_factory) -> None:
    """Being told to stop mid-turn must not cost the agent that task forever. The run
    never finished, so it has to be recorded as stopped rather than left saying it is
    still running — otherwise every later cause folds into a turn nobody is driving."""
    _project, alice, task = await _world(uow_factory)
    adapter = BlockingAdapter()
    engine = _engine(uow_factory, adapter)

    run_id = await engine.enqueue(
        marius_id=alice.id, task_id=task.id, source=WakeSource.COMMENT,
        reason="Bob bình luận trên đầu việc",
    )
    await asyncio.wait_for(adapter.started.wait(), timeout=5)
    for bg in list(engine._bg):
        bg.cancel()
    await asyncio.sleep(0.2)

    async with uow_factory() as uow:
        stopped = await uow.runs.get(run_id)
    assert stopped is not None
    assert stopped.status == RunStatus.STOPPED
    assert not await _pending(uow_factory, alice.id, task.id)

    # And the pair really is free: the next cause opens a fresh run rather than erroring.
    adapter.release.set()
    fresh = await engine.enqueue(
        marius_id=alice.id, task_id=task.id, source=WakeSource.MENTION,
        reason="Bob nhắc tên bạn",
    )
    assert fresh != run_id
    await engine.drain()


async def test_a_cause_that_lands_before_the_turn_starts_reaches_the_packet(
    uow_factory, monkeypatch
) -> None:
    """The window between opening a run and the turn actually starting.

    A cause landing here is folded into the run itself, precisely so the packet names it
    (quickstart scenario 4 step 2). And it is deliberately excluded from the end-of-run
    re-evaluation, because it is *supposed* to have been in the packet — so if the fold
    does not stick, the cause is in neither place and is gone for good.

    Every other test here waits for the turn to start before firing the second cause, so
    none of them ever touches this branch.
    """
    _project, alice, task = await _world(uow_factory)
    adapter = BlockingAdapter()
    engine = _engine(uow_factory, adapter)
    # Hold the run at *queued*: open it, but do not let the turn begin.
    monkeypatch.setattr(engine, "_spawn", lambda *args: None)

    run_id = await engine.enqueue(
        marius_id=alice.id, task_id=task.id, source=WakeSource.COMMENT,
        reason="Bob bình luận trên đầu việc",
    )
    await engine.enqueue(
        marius_id=alice.id, task_id=task.id, source=WakeSource.MENTION,
        reason="Bob nhắc tên bạn",
    )

    async with uow_factory() as uow:
        queued = await uow.runs.get(run_id)
    assert queued is not None
    assert queued.wake_source == WakeSource.MENTION, queued.wake_source
    assert "Bob nhắc tên bạn" in (queued.trigger_detail or ""), queued.trigger_detail

    # End to end, read off the adapter: this is the text the agent was actually handed.
    adapter.release.set()
    await engine._execute_run(run_id, alice.id, task.id)

    assert adapter.prompts, "lượt chạy không hề khởi động"
    assert "Bob nhắc tên bạn" in adapter.prompts[0], adapter.prompts[0]
    assert "Bob bình luận trên đầu việc" in adapter.prompts[0]
