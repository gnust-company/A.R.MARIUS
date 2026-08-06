"""The stall watchdog over a real database (spec 001 FR-057, FR-058, FR-068).

The rules are proven pure in `test_push_reason.py`. What cannot be proven there is the part
that only exists once there is storage and a loop: that a dropped task is actually *found*,
that a healthy one is left alone, that the alarm is announced once rather than every minute,
and — the one that matters on the day it matters — that all of it survives a restart.

That last test is the reason this file exists. A drive is a claim about the future, and a
restart invalidates every claim the dead process made. A safety net that forgets what it was
watching when the process dies is exactly no safety net at all, because a process dying is
the failure it was built to catch.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from armarius.application.use_cases.mariuses import MariusService
from armarius.application.use_cases.projects import ProjectService
from armarius.application.use_cases.push_reason import PushReasonService
from armarius.application.use_cases.stall_watchdog import StallWatchdog
from armarius.application.use_cases.task_log import TaskLogService
from armarius.application.use_cases.tasks import TaskService
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.entities.project import ProjectThresholds
from armarius.domain.entities.run import Run, RunStatus, WakeSource
from armarius.domain.entities.task import TaskDrive, TaskStatus
from armarius.domain.entities.task_dependency import TaskDependency
from armarius.domain.entities.task_log import TaskLogKind
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus
from armarius.infrastructure.events.topic_bus import TopicEventBus, project_topic
from armarius.shared.clock import as_utc
from tests.support.projects import force_phase

T0 = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)

THRESHOLDS = ProjectThresholds(
    hang_suspect_seconds=600,
    hang_grace_seconds=120,
    orchestration_cadence_seconds=900,
    task_silence_seconds=300,
    due_soon_hours=(24, 12, 6, 1),
    patron_reminder_hours=(8, 24, 72),
    level1_recovery_attempts=3,
    rejection_round_cap=3,
    orchestration_wakes_per_hour=4,
)


class RecordingLadder:
    """Stands in for the recovery ladder. What it *does* is proven where it lives; the
    watchdog's contract is only that a dropped task is handed over, with a cause."""

    def __init__(self) -> None:
        self.climbs: list[dict] = []

    async def climb(self, task, *, cause: str, now: datetime) -> None:  # noqa: ANN001
        self.climbs.append({"task_id": task.id, "cause": cause, "now": now})


def _watchdog(uow_factory, *, ladder=None, bus=None) -> StallWatchdog:
    return StallWatchdog(
        uow_factory,
        PushReasonService(uow_factory, ProjectService(uow_factory, THRESHOLDS)),
        task_log=TaskLogService(uow_factory),
        control_bus=bus or TopicEventBus(),
        ladder=ladder,
        interval_seconds=0.01,
        clock=lambda: T0,
    )


async def _world(uow_factory):
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
        adapter_type="echo",
        adapter_config={},
    )
    return project, alice


async def _task(uow_factory, project_id, *, title="Việc", **fields):
    tasks = TaskService(
        uow_factory,
        WakeEngine(
            uow_factory,
            InMemoryAdapterRegistry(),
            InMemoryEventBus(),
            run_timeout_seconds=30,
        ),
    )
    task = await tasks.create(
        project_id=project_id,
        title=title,
        description="Gom số liệu tháng rồi kết xuất ra tệp bảng tính.",
    )
    if fields:
        await _set(uow_factory, task.id, **fields)
    return task


async def _set(uow_factory, task_id, **fields):
    async with uow_factory() as uow:
        stored = await uow.tasks.get(task_id)
        assert stored is not None
        for name, value in fields.items():
            setattr(stored, name, value)
        await uow.tasks.update(stored)
        await uow.commit()


async def _get(uow_factory, task_id):
    async with uow_factory() as uow:
        return await uow.tasks.get(task_id)


async def _logs(uow_factory, task_id):
    async with uow_factory() as uow:
        return list(await uow.task_logs.list_by_task(task_id))


# ── bước 2 của Kịch bản 6: mất động cơ → cờ đình trệ ────────────────────────────


@pytest.mark.asyncio
async def test_a_task_with_nothing_moving_it_is_flagged(uow_factory) -> None:
    project, _ = await _world(uow_factory)
    task = await _task(uow_factory, project.id, status=TaskStatus.IN_PROGRESS, drive=None)

    flagged = await _watchdog(uow_factory).sweep(now=T0)

    assert flagged == 1
    stored = await _get(uow_factory, task.id)
    assert stored is not None and stored.stalled is True
    assert stored.stalled_reason, "nổi cờ mà không nói được vì sao"


@pytest.mark.asyncio
async def test_the_flag_seals_the_door_into_done(uow_factory) -> None:
    """FR-058 in its strongest form. The gate lives in the entity so it holds against every
    caller, but it is worth proving end to end: a stalled task reaching *done* would mean
    the system quietly finished work it had actually dropped."""
    from armarius.domain.entities.task import StalledTaskError

    project, _ = await _world(uow_factory)
    task = await _task(uow_factory, project.id, status=TaskStatus.IN_REVIEW)
    await _watchdog(uow_factory).sweep(now=T0)

    stored = await _get(uow_factory, task.id)
    assert stored is not None and stored.stalled is True
    with pytest.raises(StalledTaskError):
        stored.transition_to(
            TaskStatus.DONE, T0, has_artifact=True, signatures_complete=True
        )


@pytest.mark.asyncio
async def test_a_task_with_a_live_run_is_left_alone(uow_factory) -> None:
    project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, status=TaskStatus.IN_PROGRESS)
    async with uow_factory() as uow:
        await uow.runs.add(
            Run(
                project_id=project.id,
                marius_id=alice.id,
                task_id=task.id,
                adapter_type="echo",
                wake_source=WakeSource.ASSIGNMENT,
                status=RunStatus.RUNNING,
                started_at=T0 - timedelta(seconds=30),
                last_output_at=T0 - timedelta(seconds=30),
                created_at=T0 - timedelta(seconds=30),
            )
        )
        await uow.commit()

    flagged = await _watchdog(uow_factory).sweep(now=T0)

    assert flagged == 0
    stored = await _get(uow_factory, task.id)
    assert stored is not None and stored.stalled is False
    assert stored.drive is TaskDrive.RUN_ACTIVE


@pytest.mark.asyncio
async def test_a_stale_cache_is_not_enough_to_raise_the_alarm(uow_factory) -> None:
    """The cheap scan reads a *cached* decision, and a run may have started since it was
    written. Flagging off the cache alone would cry wolf, and an alarm that cries wolf is
    an alarm somebody mutes."""
    project, alice = await _world(uow_factory)
    task = await _task(
        uow_factory,
        project.id,
        status=TaskStatus.IN_PROGRESS,
        drive=TaskDrive.WAKE_SCHEDULED,
        drive_expires_at=T0 - timedelta(minutes=5),  # expired on the row…
    )
    async with uow_factory() as uow:  # …but a run is live right now
        await uow.runs.add(
            Run(
                project_id=project.id,
                marius_id=alice.id,
                task_id=task.id,
                adapter_type="echo",
                wake_source=WakeSource.ASSIGNMENT,
                status=RunStatus.RUNNING,
                last_output_at=T0 - timedelta(seconds=10),
                created_at=T0 - timedelta(seconds=10),
            )
        )
        await uow.commit()

    assert await _watchdog(uow_factory).sweep(now=T0) == 0
    stored = await _get(uow_factory, task.id)
    assert stored is not None and stored.stalled is False


@pytest.mark.asyncio
async def test_a_shelved_task_is_not_an_alarm(uow_factory) -> None:
    """*Backlog* and *draft* are parked by a person, not dropped by the system. Flagging
    them would put a permanent alarm on every board and teach everyone to ignore the
    colour."""
    project, _ = await _world(uow_factory)
    await _task(uow_factory, project.id, title="Xếp kho", status=TaskStatus.BACKLOG)
    await _task(uow_factory, project.id, title="Nháp", status=TaskStatus.DRAFT)

    assert await _watchdog(uow_factory).sweep(now=T0) == 0


@pytest.mark.asyncio
async def test_the_alarm_is_announced_once_but_recovery_keeps_climbing(uow_factory) -> None:
    """Two different rhythms on purpose. Re-announcing every minute would bury the channel
    in the same news; *not* re-climbing would leave Level 1 with one attempt forever."""
    project, _ = await _world(uow_factory)
    task = await _task(uow_factory, project.id, status=TaskStatus.IN_PROGRESS)
    ladder = RecordingLadder()
    watchdog = _watchdog(uow_factory, ladder=ladder)

    first = await watchdog.sweep(now=T0)
    second = await watchdog.sweep(now=T0 + timedelta(minutes=1))
    third = await watchdog.sweep(now=T0 + timedelta(minutes=2))

    assert (first, second, third) == (1, 0, 0), "báo lại cùng một tin ở mọi lượt quét"
    assert len(ladder.climbs) == 3, "ngừng leo thang trên một đầu việc vẫn đang kẹt"
    assert all(c["task_id"] == task.id for c in ladder.climbs)
    assert all(c["cause"] for c in ladder.climbs), "giao cho thang mà không nói vì sao"

    flagged = [e for e in await _logs(uow_factory, task.id) if e.kind is TaskLogKind.STALL_FLAGGED]
    assert len(flagged) == 1


@pytest.mark.asyncio
async def test_the_project_channel_hears_about_it(uow_factory) -> None:
    """Constitution IV: the board must not have to poll to find out a task was dropped."""
    project, _ = await _world(uow_factory)
    task = await _task(uow_factory, project.id, status=TaskStatus.IN_PROGRESS)
    bus = TopicEventBus()

    await _watchdog(uow_factory, bus=bus).sweep(now=T0)

    published = list(bus.backlog(project_topic(project.id)))
    assert [e.type for e in published] == ["dau-viec.dinh-tre"]
    assert published[0].data["task_id"] == str(task.id)
    assert published[0].data["reason"], "báo lên kênh mà không nói vì sao"


@pytest.mark.asyncio
async def test_a_task_that_recovers_has_its_flag_lifted(uow_factory) -> None:
    project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, status=TaskStatus.IN_PROGRESS)
    watchdog = _watchdog(uow_factory)
    await watchdog.sweep(now=T0)
    assert (await _get(uow_factory, task.id)).stalled is True

    async with uow_factory() as uow:  # somebody picked it back up
        await uow.runs.add(
            Run(
                project_id=project.id,
                marius_id=alice.id,
                task_id=task.id,
                adapter_type="echo",
                wake_source=WakeSource.CONTINUATION,
                status=RunStatus.RUNNING,
                last_output_at=T0 + timedelta(minutes=1),
                created_at=T0 + timedelta(minutes=1),
            )
        )
        await uow.commit()

    await watchdog.sweep(now=T0 + timedelta(minutes=2))

    stored = await _get(uow_factory, task.id)
    assert stored is not None and stored.stalled is False
    kinds = [e.kind for e in await _logs(uow_factory, task.id)]
    assert TaskLogKind.STALL_CLEARED in kinds, "gỡ cờ mà không để lại vết"


# ── bước 8 của Kịch bản 6: dựng lại sau khởi động lại (FR-068) ──────────────────


@pytest.mark.asyncio
async def test_every_open_task_gets_a_drive_back_after_a_restart(uow_factory) -> None:
    """The rebuild runs at startup because the process that made these claims is gone."""
    project, alice = await _world(uow_factory)
    running = await _task(uow_factory, project.id, title="Đang chạy", status=TaskStatus.IN_PROGRESS)
    blocker = await _task(uow_factory, project.id, title="Việc chặn", status=TaskStatus.TODO)
    blocked = await _task(uow_factory, project.id, title="Bị chặn", status=TaskStatus.BLOCKED)
    dropped = await _task(uow_factory, project.id, title="Bị rơi", status=TaskStatus.TODO)
    async with uow_factory() as uow:
        await uow.dependencies.add(
            TaskDependency(task_id=blocked.id, blocks_task_id=blocker.id)
        )
        await uow.runs.add(
            Run(
                project_id=project.id,
                marius_id=alice.id,
                task_id=running.id,
                adapter_type="echo",
                wake_source=WakeSource.ASSIGNMENT,
                status=RunStatus.RUNNING,
                last_output_at=T0 - timedelta(seconds=30),
                created_at=T0 - timedelta(seconds=30),
            )
        )
        await uow.commit()
    # Wipe every drive — this is what the schema looks like to a process that never set them.
    for t in (running, blocker, blocked, dropped):
        await _set(uow_factory, t.id, drive=None, drive_expires_at=None)

    rebuilt = await _watchdog(uow_factory).rebuild_drives(now=T0)

    assert rebuilt == 4
    assert (await _get(uow_factory, running.id)).drive is TaskDrive.RUN_ACTIVE
    assert (await _get(uow_factory, blocked.id)).drive is TaskDrive.BLOCKED_BY_TASK
    assert (await _get(uow_factory, dropped.id)).drive is None, (
        "dựng lại mà lại bịa ra một động cơ cho đầu việc thật sự đã bị rơi"
    )


@pytest.mark.asyncio
async def test_a_run_left_mid_flight_by_a_dead_process_is_treated_as_hung(uow_factory) -> None:
    """A run row still says RUNNING after a crash — nobody is streaming it. The rebuild
    must not read that row as "someone is working"; it dates the drive from the run's last
    output, so the clock decides rather than a process that no longer exists."""
    project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, status=TaskStatus.IN_PROGRESS)
    async with uow_factory() as uow:
        await uow.runs.add(
            Run(
                project_id=project.id,
                marius_id=alice.id,
                task_id=task.id,
                adapter_type="echo",
                wake_source=WakeSource.ASSIGNMENT,
                status=RunStatus.RUNNING,
                last_output_at=T0 - timedelta(hours=3),  # silent long before the restart
                created_at=T0 - timedelta(hours=3),
            )
        )
        await uow.commit()

    await _watchdog(uow_factory).rebuild_drives(now=T0)
    stored = await _get(uow_factory, task.id)
    assert stored is not None
    assert stored.drive is TaskDrive.RUN_ACTIVE
    assert as_utc(stored.drive_expires_at) is not None
    assert as_utc(stored.drive_expires_at) <= T0, (  # type: ignore[operator]
        "lượt chạy chết từ ba tiếng trước vẫn được coi là còn hạn"
    )

    assert await _watchdog(uow_factory).sweep(now=T0) == 1, (
        "khởi động lại xong, lượt quét đầu tiên vẫn không thấy đầu việc bị bỏ rơi"
    )
