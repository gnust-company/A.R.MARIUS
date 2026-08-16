"""The orchestration loop over a real database (spec 001 FR-052 → FR-055).

The rules themselves are proven in `test_orchestration_cadence.py` against a fixed clock.
What this file is about is the thing the rules cannot prove on their own: that a sweep
**happened**, and that a project running smoothly gets swept and woken *zero* times.

Those two are the same test asked from two sides, and both matter. "The Leader was never
woken" is the pass condition of Kịch bản 5 bước 1 — but it is also exactly what a
completely broken loop produces. So the sweep leaves a durable record, and the tests read
it: swept N times, woke nobody. Without that record the feature could not be told apart
from its own absence, on the real service or here.

The hourly cap is tested the same way — over storage, not over a counter in the object —
because the ceiling has to survive the restart it exists to protect against.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from armarius.application.use_cases.mariuses import MariusService
from armarius.application.use_cases.orchestrator import OrchestrationLoop
from armarius.application.use_cases.projects import ProjectService
from armarius.application.use_cases.tasks import TaskService
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.entities.approval import (
    Approval,
    ApprovalResult,
    SignerKind,
)
from armarius.domain.entities.project import ProjectThresholds
from armarius.domain.entities.run import Run, RunStatus, WakeSource
from armarius.domain.entities.task import TaskStatus
from armarius.domain.services.orchestration_cadence import SnagKind
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus
from tests.support.projects import force_phase

T0 = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)

THRESHOLDS = ProjectThresholds(
    hang_suspect_seconds=600,
    hang_grace_seconds=120,
    orchestration_cadence_seconds=900,
    due_soon_hours=(24, 12, 6, 1),
    patron_reminder_hours=(8, 24, 72),
    level1_recovery_attempts=3,
    rejection_round_cap=3,
    orchestration_wakes_per_hour=4,
)


class RecordingNotifier:
    """Stands in for the Leader's project session.

    The loop's job stops at "wake the Leader with this reason"; how that reaches an agent
    is the chat service's problem and is proven where it lives. Recording the calls here
    keeps the assertions about *whether and why*, which is what FR-053 and FR-054 are.
    """

    def __init__(self, deliverable: bool = True) -> None:
        self.calls: list[dict] = []
        self._deliverable = deliverable

    async def notify(
        self, *, project_id: UUID, text: str, source: WakeSource, reason: str
    ) -> bool:
        self.calls.append(
            {"project_id": project_id, "text": text, "source": source, "reason": reason}
        )
        return self._deliverable


async def _world(uow_factory):
    """A project past the planning gate with one agent and nothing wrong with it."""
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


def _loop(uow_factory, notifier, *, clock=lambda: T0) -> OrchestrationLoop:
    return OrchestrationLoop(
        uow_factory,
        ProjectService(uow_factory, THRESHOLDS),
        leader_notifier=notifier,
        clock=clock,
        interval_seconds=0.01,
    )


async def _task(uow_factory, project_id, *, title: str, **fields):
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
    async with uow_factory() as uow:
        stored = await uow.tasks.get(task.id)
        assert stored is not None
        for name, value in fields.items():
            setattr(stored, name, value)
        await uow.tasks.update(stored)
        await uow.commit()
    return task


async def _touch(uow_factory, task_id, at: datetime) -> None:
    """Move a task's last activity forward — what a project actually being worked on
    looks like from the sweep's side."""
    async with uow_factory() as uow:
        stored = await uow.tasks.get(task_id)
        assert stored is not None
        stored.updated_at = at
        await uow.tasks.update(stored)
        await uow.commit()


async def _sweeps(uow_factory, project_id):
    async with uow_factory() as uow:
        return list(await uow.orchestration_sweeps.list_recent(project_id, limit=50))


# ── bước 1: nhịp trôi qua trong im lặng ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_smooth_project_is_swept_and_nobody_is_woken(uow_factory) -> None:
    project, _ = await _world(uow_factory)
    task = await _task(uow_factory, project.id, title="Việc đang chạy tốt", updated_at=T0)
    notifier = RecordingNotifier()
    loop = _loop(uow_factory, notifier)

    for minute in (0, 20, 60):
        at = T0 + timedelta(minutes=minute)
        await _touch(uow_factory, task.id, at)  # the task is being worked on
        await loop.sweep_project(project.id, now=at)

    assert notifier.calls == []  # FR-053
    # …and the silence is the loop working, not the loop missing: three sweeps on record.
    swept = await _sweeps(uow_factory, project.id)
    assert len(swept) == 3
    assert all(s.snag_count == 0 and not s.woke_leader for s in swept)


# ── bước 2: ba tình cảnh, một lần gọi, nêu đích danh cả ba ───────────────────────

@pytest.mark.asyncio
async def test_three_predicaments_wake_the_leader_exactly_once_naming_all_three(
    uow_factory,
) -> None:
    project, alice = await _world(uow_factory)
    blocked = await _task(
        uow_factory,
        project.id,
        title="Việc bị chặn",
        status=TaskStatus.BLOCKED,
        updated_at=T0,
    )
    due = await _task(
        uow_factory,
        project.id,
        title="Việc sắp trễ",
        status=TaskStatus.IN_PROGRESS,
        due_date=T0 + timedelta(hours=5),
        updated_at=T0,
    )
    waiting = await _task(
        uow_factory,
        project.id,
        title="Việc chờ Trưởng dự án chấm",
        status=TaskStatus.IN_REVIEW,
        updated_at=T0,
    )
    notifier = RecordingNotifier()
    loop = _loop(uow_factory, notifier)

    sweep = await loop.sweep_project(project.id, now=T0)

    assert len(notifier.calls) == 1
    packet = notifier.calls[0]["text"]
    for task in (blocked, due, waiting):
        assert (task.identifier or "") in packet, f"{task.identifier} không có trong gói tin"
    assert {s.kind for s in sweep.snags} == {
        SnagKind.BLOCKED,
        SnagKind.DUE_SOON,
        SnagKind.AWAITING_LEADER,
    }
    assert notifier.calls[0]["source"] == WakeSource.IDLE_REMINDER


@pytest.mark.asyncio
async def test_a_task_gone_quiet_is_left_to_the_stall_sweep(uow_factory) -> None:
    """FR-052 no longer lets this loop ask whether anything is about to touch a task.

    Two tasks that used to wake the Leader and now must not: one that has simply been
    quiet for hours, and one whose agent started a turn and went dark. Both belong to the
    stall sweep (FR-057), which reads the drive (FR-056) and can tell *a wake is queued*
    from *nobody is coming* — a distinction this loop never had, which is why it once
    reported a task being retried against an offline assignee as silent, in direct
    contradiction of FR-063.

    The old version of this test only covered the second task, so it passed for a reason
    that had nothing to do with the rule under it.
    """
    project, alice = await _world(uow_factory)
    await _task(
        uow_factory,
        project.id,
        title="Việc im lâu, không ai chạm",
        status=TaskStatus.IN_PROGRESS,
        updated_at=T0 - timedelta(hours=2),
    )
    running = await _task(
        uow_factory,
        project.id,
        title="Việc đang có lượt chạy",
        status=TaskStatus.IN_PROGRESS,
        updated_at=T0 - timedelta(hours=2),
    )
    async with uow_factory() as uow:
        await uow.runs.add(
            Run(
                marius_id=alice.id,
                task_id=running.id,
                status=RunStatus.RUNNING,
                wake_source=WakeSource.ASSIGNMENT,
                created_at=T0 - timedelta(hours=2),
            )
        )
        await uow.commit()
    notifier = RecordingNotifier()

    sweep = await _loop(uow_factory, notifier).sweep_project(project.id, now=T0)

    assert sweep.snags == []
    assert notifier.calls == []


@pytest.mark.asyncio
async def test_a_task_the_leader_already_signed_is_not_still_waiting_on_it(
    uow_factory,
) -> None:
    """*Waiting on the Leader* means the current round has no Leader signature.

    A task sitting in review with the Leader's signature already on it is waiting on the
    **patron**, not on the Leader (FR-033). Waking the Leader about it would be telling it
    to do something it has already done — and a board of those teaches it to skim.
    """
    project, alice = await _world(uow_factory)
    task = await _task(
        uow_factory,
        project.id,
        title="Việc đã có chữ ký Trưởng dự án",
        status=TaskStatus.IN_REVIEW,
        updated_at=T0,
    )
    async with uow_factory() as uow:
        await uow.approvals.add(
            Approval(
                task_id=task.id,

                signer_kind=SignerKind.LEADER,
                signer_marius_id=alice.id,
                result=ApprovalResult.APPROVE,
                signed_at=T0,
            )
        )
        await uow.commit()
    notifier = RecordingNotifier()

    sweep = await _loop(uow_factory, notifier).sweep_project(project.id, now=T0)

    assert sweep.snags == []
    assert notifier.calls == []


@pytest.mark.asyncio
async def test_a_task_reworked_after_a_rejection_is_waiting_on_the_leader_again(
    uow_factory,
) -> None:
    """Vòng làm lại thường gặp nhất của hệ, và nó từng lọt lưới hoàn toàn.

    Trong sổ chỉ có đúng một dòng của Trưởng dự án, và dòng đó là một lời **trả về**. Hỏi
    "Trưởng dự án đã đụng vào đầu việc này chưa" thì câu trả lời là rồi — nhưng câu cần
    hỏi là "bản **đang** nằm đây đã ai duyệt chưa", và câu đó là chưa.

    Đọc nhầm câu hỏi thì đầu việc đã sửa xong, nộp lại, nằm im ở *chờ rà soát* mà không
    ai gọi Trưởng dự án tới chấm. Nó cũng không rơi vào lưới *im lâu* đúng lúc, vì vừa
    mới có hoạt động.
    """
    project, alice = await _world(uow_factory)
    task = await _task(
        uow_factory,
        project.id,
        title="Việc đã sửa và nộp lại",
        status=TaskStatus.IN_REVIEW,
        updated_at=T0,
    )
    async with uow_factory() as uow:
        await uow.approvals.add(
            Approval(
                task_id=task.id,
                signer_kind=SignerKind.LEADER,
                signer_marius_id=alice.id,
                result=ApprovalResult.REJECT,
                reason="Thiếu phần đối chiếu sổ cái.",
                signed_at=T0 - timedelta(hours=2),
            )
        )
        await uow.commit()
    notifier = RecordingNotifier()

    sweep = await _loop(uow_factory, notifier).sweep_project(project.id, now=T0)

    assert [s.kind for s in sweep.snags] == [SnagKind.AWAITING_LEADER], sweep.snags
    assert len(notifier.calls) == 1


# ── bước 3: giãn khi trơn tru, dày lại khi ứ đọng ────────────────────────────────

@pytest.mark.asyncio
async def test_the_gap_stretches_while_quiet_and_tightens_when_work_backs_up(
    uow_factory,
) -> None:
    project, _ = await _world(uow_factory)
    healthy = await _task(uow_factory, project.id, title="Việc chạy tốt", updated_at=T0)
    loop = _loop(uow_factory, RecordingNotifier())

    quiet = []
    for hour in (0, 1, 2, 3):
        at = T0 + timedelta(hours=hour)
        await _touch(uow_factory, healthy.id, at)
        quiet.append(await loop.sweep_project(project.id, now=at))
    assert [s.next_interval_seconds for s in quiet] == sorted(
        s.next_interval_seconds for s in quiet
    )
    assert quiet[-1].next_interval_seconds > quiet[0].next_interval_seconds

    # A real snag, not an old timestamp: FR-052 counts three kinds and *quiet* is not one
    # of them, so backing the clock up would now change nothing at all.
    async with uow_factory() as uow:
        stored = await uow.tasks.get(healthy.id)
        assert stored is not None
        stored.status = TaskStatus.BLOCKED
        await uow.tasks.update(stored)
        await uow.commit()

    backed_up = await loop.sweep_project(project.id, now=T0 + timedelta(hours=4))

    assert backed_up.snags != []
    assert backed_up.next_interval_seconds < quiet[0].next_interval_seconds


# ── bước 4: trần số lần gọi trong một giờ ────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_hourly_cap_holds_across_a_restart(uow_factory) -> None:
    """The ceiling is only worth having if it survives the process that set it.

    A counter on the loop object would pass a single-object test and then let a restarted
    service wake the Leader as many times over again. So the second half of this test
    throws the loop away and builds a new one over the same database — a restart, from the
    data's point of view — and the ceiling still holds.
    """
    project, _ = await _world(uow_factory)
    await _task(
        uow_factory,
        project.id,
        title="Việc mắc kẹt",
        status=TaskStatus.BLOCKED,
        status_reason="đợi bên thứ ba trả lời",
        updated_at=T0,
    )
    notifier = RecordingNotifier()
    loop = _loop(uow_factory, notifier)

    for minute in (0, 5, 10, 15, 20, 25):
        await loop.sweep_project(project.id, now=T0 + timedelta(minutes=minute))

    assert len(notifier.calls) == THRESHOLDS.orchestration_wakes_per_hour

    fresh_notifier = RecordingNotifier()
    fresh_loop = _loop(uow_factory, fresh_notifier)
    await fresh_loop.sweep_project(project.id, now=T0 + timedelta(minutes=30))

    assert fresh_notifier.calls == []
    capped = (await _sweeps(uow_factory, project.id))[0]
    assert capped.woke_leader is False
    assert capped.skipped_reason is not None  # the sweep says *why* it stayed quiet


@pytest.mark.asyncio
async def test_the_hourly_cap_holds_when_the_project_sweeps_often(uow_factory) -> None:
    """The ceiling is an hour, so it has to be counted over an hour.

    Reading the sweep history "a fixed number of rows back" and then filtering that slice
    by time makes the real window `min(N rows, one hour)`. On a project with a short
    cadence, N rows stop covering an hour, wakes older than the slice fall out of the
    count, and the ceiling quietly lifts — worst on exactly the busy projects the ceiling
    exists to protect.

    A two-minute cadence is not an exotic setting: the threshold endpoint accepts any
    positive number, and a patron watching an urgent project will reach for one.
    """
    project, _ = await _world(uow_factory)
    await _task(
        uow_factory,
        project.id,
        title="Việc mắc kẹt",
        status=TaskStatus.BLOCKED,
        status_reason="đợi bên thứ ba trả lời",
        updated_at=T0,
    )
    async with uow_factory() as uow:
        stored = await uow.projects.get(project.id)
        assert stored is not None
        stored.settings = {
            **(stored.settings or {}),
            "thresholds": {"orchestration_cadence_seconds": 120},
        }
        await uow.projects.update(stored)
        await uow.commit()

    notifier = RecordingNotifier()
    loop = _loop(uow_factory, notifier)

    # Every sweep finds the blocked task, so every one of them wants a wake. Fifty-nine
    # sweeps a minute apart all sit inside a single hour.
    for minute in range(59):
        await loop.sweep_project(project.id, now=T0 + timedelta(minutes=minute))

    assert len(notifier.calls) <= THRESHOLDS.orchestration_wakes_per_hour


@pytest.mark.asyncio
async def test_the_cap_releases_once_the_hour_has_rolled_past(uow_factory) -> None:
    project, _ = await _world(uow_factory)
    await _task(
        uow_factory,
        project.id,
        title="Việc mắc kẹt",
        status=TaskStatus.BLOCKED,
        status_reason="đợi bên thứ ba trả lời",
        updated_at=T0,
    )
    notifier = RecordingNotifier()
    loop = _loop(uow_factory, notifier)

    for minute in (0, 5, 10, 15, 20):
        await loop.sweep_project(project.id, now=T0 + timedelta(minutes=minute))
    assert len(notifier.calls) == THRESHOLDS.orchestration_wakes_per_hour

    await loop.sweep_project(project.id, now=T0 + timedelta(minutes=90))

    assert len(notifier.calls) == THRESHOLDS.orchestration_wakes_per_hour + 1


@pytest.mark.asyncio
async def test_a_deadline_mark_crossed_under_the_cap_is_still_delivered(
    uow_factory,
) -> None:
    """The ceiling delays a warning; it must not eat one.

    Three of the four predicaments are recomputed from the board on every sweep, so a
    sweep the ceiling stopped costs them nothing — the next sweep past the hour finds them
    again. *Sắp trễ* is the one that remembers: a mark already announced is not announced
    again, and that memory is written on **every** sweep, including the ones that woke
    nobody. So a mark crossing while the ceiling is saturated gets filed as "already told
    them" without anyone having been told, and it never comes round again.

    The 24-hour mark is the early one — the one that exists so the Leader still has room to
    move. Losing it and waiting for 12 hours spends half the reaction time, and on a
    deadline sitting just under the mark it is nearly twelve hours of silence on a task
    running at a wall.
    """
    project, _ = await _world(uow_factory)
    await _task(
        uow_factory,
        project.id,
        title="Việc mắc kẹt",
        status=TaskStatus.BLOCKED,
        status_reason="đợi bên thứ ba trả lời",
        updated_at=T0,
    )
    # Crosses the 24-hour mark at minute 40 — after the ceiling is already spent.
    due_soon = await _task(
        uow_factory,
        project.id,
        title="Việc có hạn chót",
        status=TaskStatus.IN_PROGRESS,
        due_date=T0 + timedelta(hours=24, minutes=30),
        updated_at=T0,
    )
    notifier = RecordingNotifier()
    loop = _loop(uow_factory, notifier)

    for minute in (0, 5, 10, 15):
        await _touch(uow_factory, due_soon.id, T0 + timedelta(minutes=minute))
        await loop.sweep_project(project.id, now=T0 + timedelta(minutes=minute))
    assert len(notifier.calls) == THRESHOLDS.orchestration_wakes_per_hour

    await _touch(uow_factory, due_soon.id, T0 + timedelta(minutes=40))
    blocked_sweep = await loop.sweep_project(project.id, now=T0 + timedelta(minutes=40))
    assert blocked_sweep.woke_leader is False, "cần đúng lượt rà bị trần chặn"
    assert any(s.kind is SnagKind.DUE_SOON for s in blocked_sweep.snags)

    await _touch(uow_factory, due_soon.id, T0 + timedelta(minutes=90))
    released = await loop.sweep_project(project.id, now=T0 + timedelta(minutes=90))

    assert released.woke_leader is True
    marks = [s for s in released.snags if s.kind is SnagKind.DUE_SOON]
    assert [s.task_id for s in marks] == [due_soon.id], (
        "mốc hạn chót chạm đúng lúc trần đang chặn đã bị ghi là 'đã báo', "
        "nên Trưởng dự án không bao giờ nhận được"
    )
    assert "hạn chót" in notifier.calls[-1]["text"]


@pytest.mark.asyncio
async def test_a_deadline_mark_is_kept_when_the_wake_could_not_be_delivered(
    uow_factory,
) -> None:
    """Spent is not the same as delivered, and only delivered retires a mark.

    A wake that could not be handed over does leave a durable row — but nothing in the
    system reads it. Both queries over that table demand a task id, and a cadence wake is
    project-level: no task, no run. No endpoint returns it and no screen shows it. So a
    mark retired on the strength of that row is a mark nobody will ever be told about.

    The case is not rare, either: the wake is refused while the Leader is mid-turn, and it
    is this very cadence wake that puts it mid-turn. One sweep waking the Leader is enough
    to make the next sweep undeliverable — and the cadence thickens exactly when the board
    is busy, which is exactly when deadlines are crossing.
    """
    project, _ = await _world(uow_factory)
    due_soon = await _task(
        uow_factory,
        project.id,
        title="Việc có hạn chót",
        status=TaskStatus.IN_PROGRESS,
        due_date=T0 + timedelta(hours=23, minutes=50),
        updated_at=T0,
    )
    unreachable = RecordingNotifier(deliverable=False)
    loop = _loop(uow_factory, unreachable)

    crossing = await loop.sweep_project(project.id, now=T0)
    assert crossing.woke_leader is True, "lượt gọi vẫn được tiêu"
    assert crossing.skipped_reason is not None, "…nhưng không giao được"
    assert any(s.kind is SnagKind.DUE_SOON for s in crossing.snags)

    # Trưởng dự án quay lại, kênh thông suốt.
    back = RecordingNotifier(deliverable=True)
    await _touch(uow_factory, due_soon.id, T0 + timedelta(minutes=30))
    returned = await _loop(uow_factory, back).sweep_project(
        project.id, now=T0 + timedelta(minutes=30)
    )

    marks = [s for s in returned.snags if s.kind is SnagKind.DUE_SOON]
    assert [s.task_id for s in marks] == [due_soon.id], (
        "mốc hạn chót bị tiêu trên một lượt gọi không giao được, nên khi Trưởng dự án "
        "quay lại thì không còn gì nêu tên đầu việc đang chạy về phía hạn"
    )
    assert back.calls and "hạn chót" in back.calls[-1]["text"]


# ── vòng nền: chỉ quét dự án đã tới nhịp ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_sweep_all_skips_a_project_whose_next_sweep_is_not_due(uow_factory) -> None:
    """The loop body ticks often; a project is swept on *its own* rhythm.

    A loop that swept every project on every tick would make the per-project interval
    decorative and would put the hourly cap in charge of pacing — which is the wrong job
    for a ceiling.
    """
    project, _ = await _world(uow_factory)
    await _task(uow_factory, project.id, title="Việc chạy tốt", updated_at=T0)
    loop = _loop(uow_factory, RecordingNotifier())

    first = await loop.sweep_all(now=T0)
    too_soon = await loop.sweep_all(now=T0 + timedelta(seconds=60))
    due = await loop.sweep_all(now=T0 + timedelta(hours=3))

    assert first == 1
    assert too_soon == 0
    assert due == 1


@pytest.mark.asyncio
async def test_a_closed_project_is_never_swept(uow_factory) -> None:
    """FR-005: a closed project is read-only history. Nobody is woken about it again."""
    from armarius.domain.entities.project import ProjectStatus

    project, _ = await _world(uow_factory)
    await _task(
        uow_factory,
        project.id,
        title="Việc im lâu",
        status=TaskStatus.IN_PROGRESS,
        updated_at=T0 - timedelta(days=2),
    )
    await force_phase(uow_factory, project.id, ProjectStatus.CLOSED)
    notifier = RecordingNotifier()

    swept = await _loop(uow_factory, notifier).sweep_all(now=T0)

    assert swept == 0
    assert notifier.calls == []
