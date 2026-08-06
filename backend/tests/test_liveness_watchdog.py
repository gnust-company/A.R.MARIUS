"""LivenessWatchdog — the background clock that decays silent agents across workspaces (§10)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from armarius.application.use_cases.liveness import LivenessEngine
from armarius.application.use_cases.liveness_watchdog import LivenessWatchdog
from armarius.domain.entities.marius import Liveness, Marius
from armarius.domain.entities.workspace import Workspace
from armarius.domain.services.liveness_fsm import LivenessConfig
from tests.support.fakes import FakeLivenessProbe, FakeUowFactory

CFG = LivenessConfig()
T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


async def test_tick_all_advances_every_workspace() -> None:
    factory = FakeUowFactory()
    marius_ids = []
    for i in range(2):
        ws = Workspace(name=f"WS{i}", slug=f"ws{i}", owner_user_id=f"u{i}")
        factory.store.workspaces[ws.id] = ws
        m = Marius(
            workspace_id=ws.id, name=f"A{i}", role="r",
            liveness=Liveness.ONLINE, last_seen_at=T0,
        )
        factory.store.mariuses[m.id] = m
        marius_ids.append(m.id)

    engine = LivenessEngine(factory, FakeLivenessProbe(False), cfg=CFG)
    watchdog = LivenessWatchdog(factory, engine, interval_seconds=0.01)

    count = await watchdog.tick_all(now=T0 + CFG.idle_timeout + timedelta(seconds=1))

    assert count == 2
    # A silent agent past T1 is probed; the unanswered probe decays it out of ONLINE.
    for mid in marius_ids:
        assert factory.store.mariuses[mid].liveness == Liveness.CHECKING


async def test_background_loop_starts_and_stops_cleanly() -> None:
    factory = FakeUowFactory()
    ws = Workspace(name="WS", slug="ws", owner_user_id="u")
    factory.store.workspaces[ws.id] = ws
    engine = LivenessEngine(factory, FakeLivenessProbe(False), cfg=CFG)
    watchdog = LivenessWatchdog(factory, engine, interval_seconds=0.01)

    watchdog.start()
    watchdog.start()  # idempotent — no second task
    await asyncio.sleep(0.05)  # let a few ticks fire
    await watchdog.stop()  # cancels + awaits the unwind
    await watchdog.stop()  # a second stop is a no-op


# ── tuyên treo và phục hồi (spec 001 FR-062, Kịch bản 6 bước 1) ──────────────────
#
# A run row that still says RUNNING is the most convincing lie in the schema: every other
# check believes it, so the task under it looks busy forever. These tests are about the one
# loop that refuses to believe it — and, just as importantly, about it *not* killing a run
# that is merely slow.

import pytest  # noqa: E402

from armarius.application.use_cases.mariuses import MariusService  # noqa: E402
from armarius.application.use_cases.projects import ProjectService  # noqa: E402
from armarius.application.use_cases.push_reason import PushReasonService  # noqa: E402
from armarius.application.use_cases.task_log import TaskLogService  # noqa: E402
from armarius.application.use_cases.tasks import TaskService  # noqa: E402
from armarius.application.use_cases.wake_engine import WakeEngine  # noqa: E402
from armarius.application.use_cases.workspaces import WorkspaceService  # noqa: E402
from armarius.domain.entities.project import ProjectThresholds  # noqa: E402
from armarius.domain.entities.run import Run, RunStatus, WakeSource  # noqa: E402
from armarius.domain.entities.task import TaskStatus  # noqa: E402
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry  # noqa: E402
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus  # noqa: E402
from tests.support.projects import force_phase  # noqa: E402

SUSPECT, GRACE = 600, 120

_THRESHOLDS = ProjectThresholds(
    hang_suspect_seconds=SUSPECT,
    hang_grace_seconds=GRACE,
    orchestration_cadence_seconds=900,
    task_silence_seconds=300,
    due_soon_hours=(24, 12, 6, 1),
    patron_reminder_hours=(8, 24, 72),
    level1_recovery_attempts=3,
    rejection_round_cap=3,
    orchestration_wakes_per_hour=4,
)


class RecordingWakes:
    """Stands in for the wake engine — what a wake *does* is proven where it lives."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def enqueue(self, **kwargs) -> None:  # noqa: ANN003
        self.calls.append(kwargs)


async def _hung_world(uow_factory, *, silent_for: timedelta, now: datetime):
    """A task being worked on, whose run last said anything ``silent_for`` ago."""
    workspaces = WorkspaceService(uow_factory)
    ws = await workspaces.create_workspace("WS")
    project = await workspaces.create_project(ws.id, "P")
    await force_phase(uow_factory, project.id)
    alice = await MariusService(uow_factory).register(
        workspace_id=ws.id, name="Alice", role="Backend", skills=[],
        adapter_type="echo", adapter_config={},
    )
    tasks = TaskService(
        uow_factory,
        WakeEngine(uow_factory, InMemoryAdapterRegistry(), InMemoryEventBus(),
                   run_timeout_seconds=30),
    )
    task = await tasks.create(
        project_id=project.id, title="Việc đang làm dở",
        description="Gom số liệu tháng rồi kết xuất ra tệp bảng tính.",
    )
    async with uow_factory() as uow:
        stored = await uow.tasks.get(task.id)
        assert stored is not None
        stored.status = TaskStatus.IN_PROGRESS
        stored.assigned_marius_id = alice.id
        stored.next_action = "Viết xong phần kết xuất bảng tính"
        await uow.tasks.update(stored)
        await uow.runs.add(
            Run(
                project_id=project.id, marius_id=alice.id, task_id=task.id,
                adapter_type="echo", wake_source=WakeSource.ASSIGNMENT,
                status=RunStatus.RUNNING,
                last_output_at=now - silent_for, created_at=now - silent_for,
            )
        )
        await uow.commit()
    return project, alice, task


def _reaper(uow_factory, wakes) -> LivenessWatchdog:
    return LivenessWatchdog(
        uow_factory,
        LivenessEngine(uow_factory, FakeLivenessProbe(False), cfg=CFG),
        interval_seconds=0.01,
        hang_suspect_seconds=SUSPECT,
        hang_grace_seconds=GRACE,
        wakes=wakes,
        task_log=TaskLogService(uow_factory),
        push_reasons=PushReasonService(uow_factory, ProjectService(uow_factory, _THRESHOLDS)),
    )


@pytest.mark.asyncio
async def test_a_run_silent_past_grace_is_declared_hung_and_the_work_resumes(
    uow_factory,
) -> None:
    now = T0 + timedelta(hours=2)
    _, alice, task = await _hung_world(
        uow_factory, silent_for=timedelta(seconds=SUSPECT + GRACE + 60), now=now
    )
    wakes = RecordingWakes()

    assert await _reaper(uow_factory, wakes).reap_hung_runs(now=now) == 1

    async with uow_factory() as uow:
        stored = await uow.tasks.get(task.id)
        runs = list(await uow.runs.list_by_task(task.id))
    assert stored is not None
    assert stored.status is TaskStatus.TODO, "đầu việc vẫn kẹt ở đang làm sau khi tuyên treo"
    assert [r.status for r in runs] == [RunStatus.TIMED_OUT], "lượt chạy ma vẫn còn sống"

    assert len(wakes.calls) == 1, "tuyên treo xong mà không ai được gọi lại"
    call = wakes.calls[0]
    assert call["marius_id"] == alice.id, "gọi nhầm người — phải đúng người phụ trách cũ"
    assert call["task_id"] == task.id
    assert "kết xuất bảng tính" in call["reason"], (
        "gọi lại mà không trỏ vào việc kế tiếp đã lưu, nên phần đã làm coi như mất"
    )


@pytest.mark.asyncio
async def test_a_run_that_is_merely_slow_is_left_alone(uow_factory) -> None:
    """Past suspicion but inside grace. An agent that thinks for four minutes between tool
    calls is working, and a reaper that kills those is a reaper somebody switches off."""
    now = T0 + timedelta(hours=2)
    _, _, task = await _hung_world(
        uow_factory, silent_for=timedelta(seconds=SUSPECT + 30), now=now
    )
    wakes = RecordingWakes()

    assert await _reaper(uow_factory, wakes).reap_hung_runs(now=now) == 0

    async with uow_factory() as uow:
        stored = await uow.tasks.get(task.id)
        runs = list(await uow.runs.list_by_task(task.id))
    assert stored is not None and stored.status is TaskStatus.IN_PROGRESS
    assert [r.status for r in runs] == [RunStatus.RUNNING]
    assert wakes.calls == []


@pytest.mark.asyncio
async def test_a_run_that_spoke_up_between_the_scan_and_the_kill_is_spared(
    uow_factory,
) -> None:
    """The scan and the decision are two transactions apart, and a run can come back to
    life in between. Reaping it then would kill work in progress — the one mistake this
    watchdog must never make — so the deadline is re-checked inside the write."""
    now = T0 + timedelta(hours=2)
    _, _, task = await _hung_world(
        uow_factory, silent_for=timedelta(seconds=SUSPECT + GRACE + 60), now=now
    )
    reaper = _reaper(uow_factory, RecordingWakes())

    async with uow_factory() as uow:  # the run speaks, right after the scan would have seen it
        run = list(await uow.runs.list_by_task(task.id))[0]
        run.last_output_at = now
        await uow.runs.update(run)
        await uow.commit()

    assert await reaper.reap_hung_runs(now=now) == 0
    async with uow_factory() as uow:
        assert [r.status for r in await uow.runs.list_by_task(task.id)] == [RunStatus.RUNNING]
