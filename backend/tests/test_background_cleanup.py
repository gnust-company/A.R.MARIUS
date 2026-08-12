"""T171 — background work that dies must not die in silence.

A wake is fire-and-forget: nobody awaits the task that drives a run, so nobody is there to
be told when it fails. That is fine while the failure is the *agent's* — the run records it
and the screen shows it. It stops being fine when the failure is the **cleanup's**, because
the cleanup is what hands the (agent, task) pair back. Refused once and unretried, the
exception left the task for no one: the run stayed open, every later cause folded into a
turn nobody was driving, and the only trace was a warning at interpreter shutdown.

The refusal itself is ordinary — two turns ending at the same instant both go to write and
one of them loses the lock. So these tests refuse the write on purpose and then ask the
question that matters: **is the pair actually free afterwards?** Not "was something logged".
Every case ends by opening a new run, because that is the thing a wedged pair cannot do.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import OperationalError

from armarius.application.ports.task_trace import TaskTracePublisher
from armarius.application.ports.workspace_trace import WorkspaceTracePublisher
from armarius.application.use_cases.leader_chat import LeaderChatService
from armarius.application.use_cases.liveness import LivenessEngine
from armarius.application.use_cases.liveness_watchdog import LivenessWatchdog
from armarius.application.use_cases.mariuses import MariusService
from armarius.application.use_cases.projects import ProjectService, RoleSpec
from armarius.application.use_cases.tasks import TaskService
from armarius.application.use_cases.wake_engine import WakeEngine, _describe
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.entities.leader_chat import ChatState
from armarius.domain.entities.run import Run, RunStatus, WakeSource
from armarius.domain.entities.wakeup import (
    PENDING_WAKEUP_STATUSES,
    WakeupRequest,
    WakeupStatus,
)
from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus
from armarius.infrastructure.events.topic_bus import TopicEventBus
from armarius.shared.background import settle
from tests.support.fakes import FakeLivenessProbe
from tests.support.projects import force_phase

NOW = datetime(2026, 8, 12, 9, 0, 0, tzinfo=UTC)


# ── refusing writes on purpose ───────────────────────────────────────────────────────
class RefusedWrites:
    """A unit-of-work factory whose commits are refused while it is armed.

    Stands in for the one failure this file is about: a write that loses the race for the
    lock. Which driver said no, and in which words, is the driver's business — what the
    code above has to survive is only that a transaction it expected to land did not.
    """

    def __init__(self, factory) -> None:  # noqa: ANN001 - the real UoW factory
        self._factory = factory
        self.refusals_left = 0
        self.refused = 0

    def arm(self, refusals: int) -> None:
        self.refusals_left = refusals

    def __call__(self):  # noqa: ANN204 - mirrors the factory it wraps
        return _RefusingUow(self._factory(), self)


class _RefusingUow:
    def __init__(self, inner, budget: RefusedWrites) -> None:  # noqa: ANN001
        self._inner = inner
        self._budget = budget

    async def __aenter__(self):  # noqa: ANN204
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *exc_info):  # noqa: ANN002, ANN204
        return await self._inner.__aexit__(*exc_info)

    async def commit(self) -> None:
        if self._budget.refusals_left > 0:
            self._budget.refusals_left -= 1
            self._budget.refused += 1
            raise OperationalError(
                "UPDATE runs SET status=?", {}, Exception("database is locked")
            )
        await self._inner.commit()

    def __getattr__(self, name: str):  # noqa: ANN204 - repositories live on the inner UoW
        return getattr(self._inner, name)


# ── worlds ───────────────────────────────────────────────────────────────────────────
async def _world(uow_factory):  # noqa: ANN201
    """A project past the plan gate, one agent, one task, and a wake engine over them."""
    workspaces = WorkspaceService(uow_factory)
    ws = await workspaces.create_workspace("WS")
    project = await workspaces.create_project(ws.id, "P")
    await force_phase(uow_factory, project.id)
    alice = await MariusService(uow_factory).register(
        workspace_id=ws.id, name="Alice", role="Backend",
        skills=[], adapter_type="echo", adapter_config={},
    )
    task = await TaskService(uow_factory, _engine(uow_factory)).create(
        project_id=project.id,
        title="Dựng cổng đăng nhập",
        description="Dựng cổng đăng nhập bằng thư điện tử và mật khẩu cho ứng dụng.",
    )
    return ws, project, alice, task


def _engine(uow_factory, *, task_trace: TaskTracePublisher | None = None) -> WakeEngine:
    registry = InMemoryAdapterRegistry()
    registry.register(EchoAdapter(step_delay=0.0))
    return WakeEngine(
        uow_factory,
        registry,
        InMemoryEventBus(),
        run_timeout_seconds=30,
        task_trace=task_trace,
    )


async def _open_run(uow_factory, project, alice, task, *, status=RunStatus.RUNNING) -> Run:
    """A run holding the pair, with the pending wake that opened it — the mid-turn picture."""
    run = Run(
        project_id=project.id, marius_id=alice.id, task_id=task.id,
        adapter_type="echo", wake_source=WakeSource.ASSIGNMENT,
        status=status, created_at=NOW, started_at=NOW,
    )
    async with uow_factory() as uow:
        await uow.runs.add(run)
        await uow.wakeups.add(
            WakeupRequest(
                project_id=project.id, marius_id=alice.id, task_id=task.id,
                source=WakeSource.ASSIGNMENT, status=WakeupStatus.DISPATCHED,
                run_id=run.id, created_at=NOW,
            )
        )
        await uow.commit()
    return run


async def _pending(uow_factory, marius_id, task_id) -> list:  # noqa: ANN001
    async with uow_factory() as uow:
        rows = await uow.wakeups.list_active_for(marius_id, task_id)
    return [w for w in rows if w.status in PENDING_WAKEUP_STATUSES]


# ── the retry helper itself ──────────────────────────────────────────────────────────
async def test_a_refused_cleanup_is_retried_until_it_lands() -> None:
    """One refusal must not be the end of it — the write it lost is available a moment on."""
    attempts = 0

    async def flaky() -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OperationalError("UPDATE", {}, Exception("database is locked"))

    assert await settle("hand the pair back", flaky, delay_seconds=0) is True
    assert attempts == 3


async def test_a_cleanup_that_never_lands_is_said_out_loud_not_raised(caplog) -> None:  # noqa: ANN001
    """The whole point. Raising here reaches nobody — the caller is a bare background task —
    so giving up has to leave a line somebody can find, and must not take the caller down
    with it."""

    async def doomed() -> None:
        raise OperationalError("UPDATE", {}, Exception("database is locked"))

    with caplog.at_level(logging.ERROR):
        settled = await settle("hand the pair back", doomed, attempts=2, delay_seconds=0)

    assert settled is False
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "bỏ cuộc mà không nói gì thì đúng là cái lỗi đang vá"
    assert "hand the pair back" in errors[0].getMessage()


# ── the pair comes back ──────────────────────────────────────────────────────────────
async def test_a_release_that_loses_the_write_race_still_hands_the_pair_back(
    uow_factory,
) -> None:
    """The defect, at its own scale: one refused commit used to cost the agent that task."""
    _ws, project, alice, task = await _world(uow_factory)
    run = await _open_run(uow_factory, project, alice, task)

    refusing = RefusedWrites(uow_factory)
    engine = _engine(refusing)
    refusing.arm(1)
    await engine._release_pair(run.id)

    assert refusing.refused == 1, "bài kiểm không thật sự chặn được lượt ghi nào"
    async with uow_factory() as uow:
        settled = await uow.runs.get(run.id)
    assert settled is not None
    assert settled.status == RunStatus.STOPPED
    assert not await _pending(uow_factory, alice.id, task.id)

    # And the pair really is free: a new cause opens its own run rather than folding into
    # a turn nobody is driving. This is the assertion the log line cannot make.
    fresh = await engine.enqueue(
        marius_id=alice.id, task_id=task.id, source=WakeSource.COMMENT, reason="Bob hỏi",
    )
    await engine.drain()
    assert fresh != run.id


async def test_a_release_that_never_lands_leaves_the_pair_to_the_watchdog(
    uow_factory, caplog,  # noqa: ANN001
) -> None:
    """The honest limit. When the write never lands there is nowhere to record anything —
    so the run stays open on purpose, and the reclaim belongs to the watchdog built for it
    (FR-062). What must not happen is the failure vanishing on the way there."""
    _ws, project, alice, task = await _world(uow_factory)
    run = await _open_run(uow_factory, project, alice, task)

    refusing = RefusedWrites(uow_factory)
    engine = _engine(refusing)
    refusing.arm(99)
    with caplog.at_level(logging.ERROR):
        await engine._release_pair(run.id)  # must return, not raise

    assert [r for r in caplog.records if r.levelno >= logging.ERROR]
    async with uow_factory() as uow:
        stuck = await uow.runs.get(run.id)
    assert stuck is not None and stuck.status == RunStatus.RUNNING

    # Now the reclaim. Silence past the suspect window and its grace makes the run hung.
    refusing.arm(0)
    watchdog = LivenessWatchdog(
        uow_factory,
        LivenessEngine(uow_factory, FakeLivenessProbe()),
        hang_suspect_seconds=600,
        hang_grace_seconds=120,
    )
    assert await watchdog.reap_hung_runs(now=NOW + timedelta(hours=1)) == 1

    async with uow_factory() as uow:
        reaped = await uow.runs.get(run.id)
    assert reaped is not None and reaped.status == RunStatus.TIMED_OUT

    # The leftover wake row goes with it: the pair is genuinely free again, not wedged
    # behind a row nothing will ever come back to close.
    fresh = await engine.enqueue(
        marius_id=alice.id, task_id=task.id, source=WakeSource.COMMENT, reason="Bob hỏi",
    )
    await engine.drain()
    assert fresh != run.id
    assert not await _pending(uow_factory, alice.id, task.id)


# ── saying what actually happened ────────────────────────────────────────────────────
class _BrokenTaskTrace(TaskTracePublisher):
    """A tee that fails — infrastructure breaking somewhere the turn does not expect."""

    async def publish(self, task_id, type, data) -> None:  # noqa: A002, ANN001
        raise RuntimeError("kênh sự kiện của đầu việc hỏng")


async def test_a_turn_killed_by_infrastructure_is_recorded_as_failed_with_its_cause(
    uow_factory,
) -> None:
    """*Stopped* means somebody stopped it. A turn that blew up is a different fact, and the
    run row is the only place anyone reads it afterwards — recording a crash as an ordinary
    restart is how a real fault ends up looking like nothing happened."""
    _ws, _project, alice, task = await _world(uow_factory)
    engine = _engine(uow_factory, task_trace=_BrokenTaskTrace())

    run_id = await engine.enqueue(
        marius_id=alice.id, task_id=task.id, source=WakeSource.ASSIGNMENT, reason=None,
    )
    await engine.drain()

    async with uow_factory() as uow:
        run = await uow.runs.get(run_id)
    assert run is not None
    assert run.status == RunStatus.FAILED
    assert run.error and "kênh sự kiện của đầu việc hỏng" in run.error
    assert not await _pending(uow_factory, alice.id, task.id)


async def test_what_killed_a_turn_is_named_without_the_driver_s_paperwork() -> None:
    """This field is read on a screen the patron sees. A database error stringifies into the
    message, then the statement that failed, then a documentation link — only the first says
    anything a reader needs, and the rest puts query text and column names in front of them."""
    described = _describe(
        OperationalError(
            "UPDATE runs SET status=? WHERE id=?", {}, Exception("database is locked")
        )
    )
    assert "database is locked" in described
    assert "UPDATE runs" not in described
    assert "\n" not in described


# ── nothing may throw after the commit it reports ────────────────────────────────────
class _BrokenWorkspaceTrace(WorkspaceTracePublisher):
    """The channel a run announces itself on, broken."""

    async def publish(self, workspace_id, type, data) -> None:  # noqa: A002, ANN001
        raise RuntimeError("kênh workspace hỏng")


async def test_a_broken_channel_does_not_strand_the_run_it_was_announcing(
    uow_factory,
) -> None:
    """``_open_run`` writes its rows, commits, announces — and only *then* does the caller
    spawn the task that drives the run. An announcement that threw used to escape between
    those two, leaving a run committed as *queued* that nobody would ever execute.

    It also broke the property retrying stands on: calling ``enqueue`` again cannot repair
    that, because the second call folds into the run the first one stranded and returns
    before spawning anything either. Telling a screen must not be able to stop work."""
    _ws, _project, alice, task = await _world(uow_factory)
    registry = InMemoryAdapterRegistry()
    registry.register(EchoAdapter(step_delay=0.0))
    engine = WakeEngine(
        uow_factory, registry, InMemoryEventBus(),
        run_timeout_seconds=30, workspace_trace=_BrokenWorkspaceTrace(),
    )

    run_id = await engine.enqueue(
        marius_id=alice.id, task_id=task.id, source=WakeSource.ASSIGNMENT, reason=None,
    )
    await engine.drain()

    async with uow_factory() as uow:
        run = await uow.runs.get(run_id)
    assert run is not None
    assert run.status == RunStatus.COMPLETED, "lượt chạy đã ghi vào kho mà không ai chạy"
    assert not await _pending(uow_factory, alice.id, task.id)


# ── the same shape, one floor up: the Leader chat turn ───────────────────────────────
class _BlockingEcho(EchoAdapter):
    """Echo, but the turn stays open until the test lets it end — so the refusal can be
    armed at the exact moment the turn goes to close itself."""

    def __init__(self) -> None:
        super().__init__(step_delay=0.0)
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def execute(self, ctx):  # noqa: ANN001, ANN201
        self.started.set()
        await self.release.wait()
        return await super().execute(ctx)


async def test_a_leader_chat_turn_that_loses_the_write_race_still_ends(uow_factory) -> None:
    """The same defect one floor up, and it locks the patron out of their own chat: a
    conversation left *thinking* rejects every new message with 409, forever, with no error
    anywhere to say why."""
    bus = TopicEventBus()
    refusing = RefusedWrites(uow_factory)
    adapter = _BlockingEcho()
    registry = InMemoryAdapterRegistry()
    registry.register(adapter)

    workspaces = WorkspaceService(uow_factory)
    projects = ProjectService(uow_factory)
    liveness = LivenessEngine(uow_factory, FakeLivenessProbe(True))
    ws = await workspaces.create_workspace("WS")
    project = await projects.create_project(
        ws.id, "Apollo",
        roles=[
            RoleSpec(key="leader", title="Leader", seats=1, is_leader=True,
                     description="Leads."),
            RoleSpec(key="backend", title="Backend", seats=1, description="Owns the API."),
        ],
    )
    leader = await MariusService(uow_factory).register(
        workspace_id=ws.id, name="Lead", role="Leader",
        skills=[], adapter_type="echo", adapter_config={},
    )
    await projects.grant_seat(project.id, "leader", leader.id, system=True)
    await liveness.record_signal(leader.id)

    chat = LeaderChatService(
        refusing, registry=registry, control_bus=bus,
        liveness=LivenessEngine(refusing, FakeLivenessProbe(True)),
        base_url="http://api", run_timeout_seconds=30,
    )
    view = await chat.send(project_id=project.id, message="Dự án đang tới đâu rồi?")
    assert view.conversation.state == ChatState.THINKING

    # The turn is in flight; refuse the writes it is about to make on its way out.
    await asyncio.wait_for(adapter.started.wait(), timeout=5)
    refusing.arm(2)
    adapter.release.set()

    for _ in range(400):
        settled = await chat.get_or_open(project.id)
        if settled.conversation.state != ChatState.THINKING:
            break
        await asyncio.sleep(0.02)

    assert refusing.refused == 2, "bài kiểm không thật sự chặn được lượt ghi nào"
    assert settled.conversation.state != ChatState.THINKING
