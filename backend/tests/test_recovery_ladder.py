"""Thang phục hồi và hậu quả của ngoại tuyến, qua kho lưu trữ thật (FR-059 → FR-064).

`test_escalation.py` proves the rungs as arithmetic. What it cannot prove is the part that
only exists once there is storage: that the budget is *spaced* rather than spent in one
sweep, that reaching the patron carries the record of everything already tried, and that an
agent being declared gone actually changes the board rather than only a notification.

That last one is worth stating plainly. A task pointing at an agent that no longer exists
looks assigned and is not — it is the most expensive kind of wrong, because every dashboard
agrees it is fine.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from armarius.application.use_cases.inbox import InboxService
from armarius.application.use_cases.projects import ProjectService
from armarius.application.use_cases.push_reason import PushReasonService
from armarius.application.use_cases.recovery import (
    EscalationAnswer,
    NotOnTheLeadersRung,
    OfflineFalloutService,
    RecoveryEscalator,
)
from armarius.application.use_cases.stall_watchdog import StallWatchdog
from armarius.application.use_cases.task_log import TaskLogService
from armarius.application.use_cases.tasks import TaskService
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.entities.inbox_item import InboxItemKind, InboxItemStatus
from armarius.domain.entities.marius import Liveness
from armarius.domain.entities.project import Project, ProjectThresholds
from armarius.domain.entities.role import Role
from armarius.domain.entities.run import WakeSource
from armarius.domain.entities.seat_grant import SeatGrant
from armarius.domain.entities.task import TaskStatus
from armarius.domain.entities.task_log import TaskLogKind
from armarius.domain.entities.wakeup import WakeupRequest
from armarius.domain.services.escalation import EscalationLevel
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus
from armarius.infrastructure.events.topic_bus import TopicEventBus, patron_topic
from armarius.shared.config import settings
from tests.support.agents import make_agent
from tests.support.projects import force_phase

T0 = datetime(2026, 8, 6, 10, 0, 0, tzinfo=UTC)
CAP = 3
HANDOVER_CAP = 3
CAUSE = "không có gì được hẹn để đẩy đầu việc này đi tiếp"

THRESHOLDS = ProjectThresholds(
    hang_suspect_seconds=600,
    hang_grace_seconds=120,
    orchestration_cadence_seconds=900,
    due_soon_hours=(24, 12, 6, 1),
    patron_reminder_hours=(8, 24, 72),
    level1_recovery_attempts=CAP,
    rejection_round_cap=3,
    orchestration_wakes_per_hour=4,
)


class RecordingWakes:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def enqueue(self, **kwargs) -> None:  # noqa: ANN003
        self.calls.append(kwargs)


class RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def notify(
        self, *, project_id: UUID, source: WakeSource, reason, detail: str = ""
    ) -> bool:
        self.calls.append({"project_id": project_id, "reason": reason, "detail": detail})
        return True


async def _world(uow_factory, *, patron: str = "patron-1"):
    """A running project with a named patron, a Leader seat, and one worker.

    The project is written through the repository rather than nudged afterwards:
    `created_by_user_id` is set at creation and never rewritten by `update`, so a test that
    tried to patch it in place would be asserting against a write path that does not exist.
    """
    ws = await WorkspaceService(uow_factory).create_workspace("WS")
    alice = await make_agent(uow_factory, 
        workspace_id=ws.id, name="Alice", role="Backend", skills=[],
        adapter_type="echo", adapter_config={},
    )
    project = Project(
        workspace_id=ws.id, name="P", slug="p", key="P1",
        created_by_user_id=patron,
    )
    async with uow_factory() as uow:
        project = await uow.projects.add(project)
        await uow.roles.add(
            Role(project_id=project.id, key="leader", title="Trưởng dự án", is_leader=True)
        )
        await uow.commit()
    await force_phase(uow_factory, project.id)
    return ws, project, alice


async def _task(uow_factory, project_id, *, assignee=None, **fields):
    tasks = TaskService(
        uow_factory,
        WakeEngine(uow_factory, InMemoryAdapterRegistry(), InMemoryEventBus(),
                   run_timeout_seconds=30),
    )
    task = await tasks.create(
        project_id=project_id, title="Việc kẹt",
        description="Gom số liệu tháng rồi kết xuất ra tệp bảng tính.",
    )
    async with uow_factory() as uow:
        stored = await uow.tasks.get(task.id)
        assert stored is not None
        stored.status = TaskStatus.IN_PROGRESS
        stored.assigned_marius_id = assignee
        for name, value in fields.items():
            setattr(stored, name, value)
        await uow.tasks.update(stored)
        await uow.commit()
        return stored


def _escalator(uow_factory, *, wakes, notifier, bus) -> RecoveryEscalator:
    return RecoveryEscalator(
        uow_factory,
        ProjectService(uow_factory, THRESHOLDS),
        wakes=wakes,
        inbox=InboxService(uow_factory, bus),
        task_log=TaskLogService(uow_factory),
        control_bus=bus,
        leader_notifier=notifier,
        push_reasons=PushReasonService(
            uow_factory,
            ProjectService(uow_factory, THRESHOLDS),
            accept_grace_seconds=settings.run_claim_hold_seconds,
        ),
    )


async def _ladder(uow_factory, task_id):
    async with uow_factory() as uow:
        return await uow.push_reasons.get_for_task(task_id)


# ── Mức 1: có ngân sách và có khoảng cách ───────────────────────────────────────


@pytest.mark.asyncio
async def test_level_one_rewakes_the_same_assignee(uow_factory) -> None:
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    wakes = RecordingWakes()

    await _escalator(
        uow_factory, wakes=wakes, notifier=RecordingNotifier(), bus=TopicEventBus()
    ).climb(task, cause=CAUSE, now=T0)

    assert len(wakes.calls) == 1
    assert wakes.calls[0]["marius_id"] == alice.id
    assert wakes.calls[0]["task_id"] == task.id


@pytest.mark.asyncio
async def test_the_budget_is_spaced_not_spent_in_one_burst(uow_factory) -> None:
    """The watchdog sweeps every minute. Without the spacing, a budget of three would be
    gone in three minutes and every stuck task would reach the Leader before anyone had a
    chance to be woken — the budget would be decoration."""
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    wakes = RecordingWakes()
    escalator = _escalator(
        uow_factory, wakes=wakes, notifier=RecordingNotifier(), bus=TopicEventBus()
    )

    for minute in range(5):  # five sweeps a minute apart
        await escalator.climb(task, cause=CAUSE, now=T0 + timedelta(minutes=minute))

    assert len(wakes.calls) == 1, (
        f"tiêu {len(wakes.calls)} lần gọi trong năm phút — ngân sách Mức 1 thành đồ trang trí"
    )
    ladder = await _ladder(uow_factory, task.id)
    assert ladder is not None and ladder.level is EscalationLevel.LEVEL_1


@pytest.mark.asyncio
async def test_the_budget_runs_out_and_the_leader_is_asked(uow_factory) -> None:
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    wakes, notifier = RecordingWakes(), RecordingNotifier()
    escalator = _escalator(uow_factory, wakes=wakes, notifier=notifier, bus=TopicEventBus())

    # Far enough apart that every attempt is due (the gap doubles: 60s, 120s, 240s…).
    for hour in range(5):
        await escalator.climb(task, cause=CAUSE, now=T0 + timedelta(hours=hour))

    assert len(wakes.calls) == CAP, (
        f"tiêu {len(wakes.calls)} lần tự gọi lại, trần là {CAP}"
    )
    assert notifier.calls, "hết ngân sách rồi mà Trưởng dự án không được hỏi"
    assert "has stalled" in notifier.calls[0]["detail"]
    ladder = await _ladder(uow_factory, task.id)
    assert ladder is not None and ladder.level >= EscalationLevel.LEVEL_2


# ── điều kiện vào nấc: đầu việc chưa có người phụ trách (FR-059a) ───────────────


@pytest.mark.asyncio
async def test_a_task_with_nobody_on_it_reaches_the_leader_on_the_first_sweep(
    uow_factory,
) -> None:
    """FR-059a. Level 1 is *re-wake the assignee*, so an unassigned task has no rung there.

    The cost of the old behaviour, measured: the ladder spent all three attempts waking
    nobody, spaced 5, 10 and 20 minutes, and the Leader — the one party that could have
    fixed this in one move, by assigning somebody — heard about it some thirty-five
    minutes late.
    """
    _, project, _alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=None)
    wakes, notifier = RecordingWakes(), RecordingNotifier()

    await _escalator(
        uow_factory, wakes=wakes, notifier=notifier, bus=TopicEventBus()
    ).climb(task, cause=CAUSE, now=T0)

    assert wakes.calls == [], "không có ai để gọi mà hệ vẫn tiêu một lần thử"
    assert notifier.calls, "chưa gán ai mà Trưởng dự án không được hỏi ngay"
    ladder = await _ladder(uow_factory, task.id)
    assert ladder is not None
    assert ladder.level is EscalationLevel.LEVEL_2
    assert ladder.attempts == 0


@pytest.mark.asyncio
async def test_the_leader_is_told_which_of_the_two_roads_led_to_it(uow_factory) -> None:
    """FR-059a. Two ways into Mức 2, two different things for the Leader to do.

    *The assignee was called and never came* wants a reassignment, a split, an unblock.
    *Nobody was ever given this* wants one move: assign it. Sharing one paragraph would
    have told the Leader the system tried three times to wake somebody who does not exist.
    """
    _, project, alice = await _world(uow_factory)
    unassigned = await _task(uow_factory, project.id, assignee=None)
    stalled = await _task(uow_factory, project.id, assignee=alice.id)

    orphan_notifier, worked_notifier = RecordingNotifier(), RecordingNotifier()
    await _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=orphan_notifier, bus=TopicEventBus()
    ).climb(unassigned, cause=CAUSE, now=T0)
    worked = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=worked_notifier, bus=TopicEventBus()
    )
    for hour in range(5):
        await worked.climb(stalled, cause=CAUSE, now=T0 + timedelta(hours=hour))

    orphan_text = orphan_notifier.calls[0]["detail"]
    assert "Nobody holds this task" in orphan_text
    assert "called them back" not in orphan_text, (
        "nói với Trưởng dự án là đã gọi lại, trong khi không gọi ai lần nào"
    )
    assert "called them back" in worked_notifier.calls[0]["detail"]


@pytest.mark.asyncio
async def test_the_log_records_the_rung_the_task_actually_came_from(uow_factory) -> None:
    """The entry used to be written as *the level below where it is now*, which was the
    same answer only while every climb was one rung. A task entering at Mức 2 would have
    left a line claiming a Mức 1 attempt that never happened."""
    _, project, _alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=None)

    await _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=RecordingNotifier(), bus=TopicEventBus()
    ).climb(task, cause=CAUSE, now=T0)

    async with uow_factory() as uow:
        entries = list(await uow.task_logs.list_by_task(task.id))
    climbs = [e for e in entries if e.kind is TaskLogKind.ESCALATED]
    assert climbs, "leo thang mà không ghi vết"
    assert climbs[0].before == "mức 0"
    assert climbs[0].after == "mức 2"


@pytest.mark.asyncio
async def test_the_patron_dossier_keeps_the_unassigned_case_apart(uow_factory) -> None:
    """FR-061 through FR-059a: the record has to survive all the way to the patron.

    A bare ``level1_attempts: 0`` is ambiguous — *not applicable* and *not tried yet* read
    the same — so the flag is carried explicitly and the letter says it in words.
    """
    _, project, _alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=None)
    escalator = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=RecordingNotifier(), bus=TopicEventBus()
    )

    for hour in range(7):
        await escalator.climb(task, cause=CAUSE, now=T0 + timedelta(hours=hour))

    async with uow_factory() as uow:
        items = list(await uow.inbox.list_for_recipient("patron-1"))
    escalations = [i for i in items if i.kind is InboxItemKind.ESCALATION]
    assert escalations, "leo hết thang mà người chủ không nhận được gì"
    dossier = escalations[0].attempt_dossier
    assert dossier.get("level1_applicable") is False
    assert dossier.get("level1_attempts") == 0
    assert "giao" in str(dossier.get("question", "")), (
        "hồ sơ không nói điều duy nhất cần làm là giao đầu việc cho ai đó"
    )
    assert "chưa có người phụ trách" in escalations[0].body


class UnreachableNotifier:
    """A Leader that cannot be reached — offline, or already mid-turn.

    The real notifier answers this with a return value, not an exception: it still writes a
    durable wake request, then reports False. Every fake in this suite answered True
    unconditionally, so the whole not-delivered branch had no coverage at all.
    """

    def __init__(self) -> None:
        self.attempts: list[dict] = []

    async def notify(
        self, *, project_id: UUID, source: WakeSource, reason, detail: str = ""
    ) -> bool:
        self.attempts.append(
            {"project_id": project_id, "reason": reason, "detail": detail}
        )
        return False


class FlakyNotifier:
    """Unreachable for the first `fail_first` calls, then fine — a Leader that was busy."""

    def __init__(self, *, fail_first: int) -> None:
        self.attempts: list[dict] = []
        self._fail_first = fail_first

    async def notify(
        self, *, project_id: UUID, source: WakeSource, reason, detail: str = ""
    ) -> bool:
        self.attempts.append({"project_id": project_id, "reason": reason})
        return len(self.attempts) > self._fail_first


@pytest.mark.asyncio
async def test_a_question_that_never_reached_the_leader_is_asked_again(
    uow_factory,
) -> None:
    """Mức 2 is climbed **once**, so a single undelivered call spends the whole rung.

    The rung is written and committed before anyone tries to deliver it, and `_ask_leader`
    only runs on the sweep that climbs. Leave the rung standing on a call that failed and
    every later sweep finds the ladder already at Level 2 and walks it straight past.
    """
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    notifier = UnreachableNotifier()
    escalator = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=notifier, bus=TopicEventBus()
    )

    for hour in range(7):
        await escalator.climb(task, cause=CAUSE, now=T0 + timedelta(hours=hour))

    assert len(notifier.attempts) > 1, (
        f"chỉ thử gọi Trưởng dự án {len(notifier.attempts)} lần rồi thôi — một lượt gọi "
        "hụt nuốt trọn Mức 2"
    )


@pytest.mark.asyncio
async def test_an_unreachable_leader_still_reaches_the_patron_but_truthfully(
    uow_factory,
) -> None:
    """The rung must not be skipped **and** must not be lied about.

    A Leader nobody can reach is exactly the problem only the patron can fix — restart it,
    replace it — so keeping the task off their desk hides the one thing they could act on.
    But the dossier must say what actually happened: the Leader was never reached, not that
    they were asked and shrugged. For the patron that is the more urgent sentence anyway.
    """
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    escalator = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=UnreachableNotifier(),
        bus=TopicEventBus(),
    )

    for hour in range(12):
        await escalator.climb(task, cause=CAUSE, now=T0 + timedelta(hours=hour))

    async with uow_factory() as uow:
        items = list(await uow.inbox.list_for_recipient("patron-1"))
    escalations = [i for i in items if i.kind is InboxItemKind.ESCALATION]
    assert len(escalations) == 1, (
        f"người chủ nhận {len(escalations)} mục — Trưởng dự án mất liên lạc mà việc kẹt "
        "không tới được người duy nhất dựng lại được nó"
    )
    dossier = escalations[0].attempt_dossier
    assert dossier.get("leader_asked") is False, (
        "hồ sơ khai Trưởng dự án đã được hỏi, trong khi lời hỏi chưa từng tới nơi"
    )
    assert dossier.get("leader_asks") == HANDOVER_CAP, (
        "hồ sơ không nói đã hỏi Trưởng dự án mấy lần"
    )
    assert "không gọi được" in (escalations[0].body or ""), (
        "thân thư không nói ra điều đáng nói nhất: không ai liên lạc được với Trưởng dự án"
    )


@pytest.mark.asyncio
async def test_the_patron_is_not_told_on_the_first_failed_handover(uow_factory) -> None:
    """A Leader mid-turn is busy this minute and free the next.

    Handing that to the patron spends a person's attention on something that fixes itself,
    which is the exact failure mode the whole ladder is ordered to avoid.
    """
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    notifier = UnreachableNotifier()
    escalator = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=notifier, bus=TopicEventBus()
    )

    # Far enough to spend the Level-1 budget and make the first handover attempt, no more.
    for hour in range(4):
        await escalator.climb(task, cause=CAUSE, now=T0 + timedelta(hours=hour))

    assert len(notifier.attempts) == 1, f"đã thử {len(notifier.attempts)} lần chuyển giao"
    async with uow_factory() as uow:
        items = list(await uow.inbox.list_for_recipient("patron-1"))
    assert [i for i in items if i.kind is InboxItemKind.ESCALATION] == [], (
        "gọi hụt Trưởng dự án đúng một lần đã làm phiền người chủ"
    )


@pytest.mark.asyncio
async def test_a_handover_that_lands_on_a_retry_still_counts_as_asked(
    uow_factory,
) -> None:
    """The counter measures *failed* handovers, so a second try that lands clears it.

    Without this the dossier would call a Leader who was reached — late, but reached —
    unreachable, and the patron would be sent to restart something that is running.
    """
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    notifier = FlakyNotifier(fail_first=1)
    escalator = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=notifier, bus=TopicEventBus()
    )

    for hour in range(12):
        await escalator.climb(task, cause=CAUSE, now=T0 + timedelta(hours=hour))

    ladder = await _ladder(uow_factory, task.id)
    assert ladder is not None and ladder.leader_reached_at is not None, (
        "lời hỏi tới nơi ở lần thử thứ hai mà vẫn bị ghi là không gọi được"
    )
    async with uow_factory() as uow:
        items = list(await uow.inbox.list_for_recipient("patron-1"))
    escalations = [i for i in items if i.kind is InboxItemKind.ESCALATION]
    assert escalations and escalations[0].attempt_dossier.get("leader_asked") is True


@pytest.mark.asyncio
async def test_a_new_cause_gets_a_fresh_handover_budget(uow_factory) -> None:
    """FR-060 counts a budget **per cause**, and the handover budget is no exception.

    The two numbers sit beside each other in the patron's dossier, so a handover count that
    outlives its cause makes the dossier charge the new problem for calls that belong to the
    old one — and gets the patron to the "your Leader is gone" screen on the first hiccup of
    a problem the system has barely started on.
    """
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    escalator = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=UnreachableNotifier(),
        bus=TopicEventBus(),
    )

    for hour in range(5):  # burn the Level-1 budget, then miss two handovers
        await escalator.climb(task, cause=CAUSE, now=T0 + timedelta(hours=hour))
    spent = await _ladder(uow_factory, task.id)
    assert spent is not None and spent.handover_attempts == 2, spent

    await escalator.climb(
        task, cause="thành phẩm không còn trong kho", now=T0 + timedelta(hours=5)
    )

    ladder = await _ladder(uow_factory, task.id)
    assert ladder is not None and ladder.handover_attempts == 0, (
        "nguyên nhân mới bị tính tiền cho những lần gọi hụt của nguyên nhân cũ"
    )


# ── Mức 3: hồ sơ đã thử (FR-061) ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reaching_the_patron_carries_the_record_of_what_was_tried(
    uow_factory,
) -> None:
    """A patron asked "this is stuck, what now?" has to go and reconstruct what was already
    attempted before they can answer. One told "woken three times, Leader asked, still
    stuck, here is the question" can answer in one read."""
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    bus = TopicEventBus()
    escalator = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=RecordingNotifier(), bus=bus
    )

    for hour in range(7):
        await escalator.climb(task, cause=CAUSE, now=T0 + timedelta(hours=hour))

    async with uow_factory() as uow:
        items = list(await uow.inbox.list_for_recipient("patron-1"))
    escalations = [i for i in items if i.kind is InboxItemKind.ESCALATION]
    assert escalations, "leo hết thang mà người chủ không nhận được gì"
    dossier = escalations[0].attempt_dossier
    assert dossier.get("level1_attempts") == CAP, (
        "hồ sơ không nói hệ đã tự thử mấy lần, nên người chủ phải tự đi dựng lại"
    )
    assert dossier.get("cause"), "hồ sơ không nói vì sao kẹt"
    assert dossier.get("question"), "hồ sơ không nêu chính xác điều cần quyết"

    types = [e.type for e in bus.backlog(patron_topic("patron-1"))]
    assert "escalation.level_3" in types


@pytest.mark.asyncio
async def test_the_patron_is_asked_once_not_on_every_sweep(uow_factory) -> None:
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    escalator = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=RecordingNotifier(),
        bus=TopicEventBus(),
    )

    for hour in range(12):
        await escalator.climb(task, cause=CAUSE, now=T0 + timedelta(hours=hour))

    async with uow_factory() as uow:
        items = list(await uow.inbox.list_for_recipient("patron-1"))
    escalations = [i for i in items if i.kind is InboxItemKind.ESCALATION]
    assert len(escalations) == 1, (
        f"người chủ bị hỏi {len(escalations)} lần về đúng một đầu việc"
    )


# ── ngoại tuyến (FR-064) ────────────────────────────────────────────────────────


def _fallout(uow_factory, *, notifier, bus) -> OfflineFalloutService:
    return OfflineFalloutService(
        uow_factory,
        inbox=InboxService(uow_factory, bus),
        task_log=TaskLogService(uow_factory),
        push_reasons=PushReasonService(
            uow_factory,
            ProjectService(uow_factory, THRESHOLDS),
            accept_grace_seconds=settings.run_claim_hold_seconds,
        ),
        leader_notifier=notifier,
    )


@pytest.mark.asyncio
async def test_a_worker_going_offline_parks_its_tasks_and_tells_the_leader(
    uow_factory,
) -> None:
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    notifier = RecordingNotifier()
    async with uow_factory() as uow:
        m = await uow.mariuses.get(alice.id)
        m.liveness = Liveness.OFFLINE
        await uow.mariuses.update(m)
        await uow.commit()

    await _fallout(uow_factory, notifier=notifier, bus=TopicEventBus()).agent_went_offline(
        alice.id, now=T0
    )

    async with uow_factory() as uow:
        stored = await uow.tasks.get(task.id)
    assert stored is not None
    assert stored.status is TaskStatus.BLOCKED, (
        "người phụ trách biến mất mà đầu việc vẫn trông như đang được làm"
    )
    assert "ngoại tuyến" in (stored.status_reason or ""), (
        "chặn mà không ghi lý do, nên ai đọc bảng cũng phải đi điều tra"
    )
    assert notifier.calls, "Trưởng dự án — người phân việc — không được báo"


@pytest.mark.asyncio
async def test_a_task_already_blocked_is_not_churned(uow_factory) -> None:
    """Re-blocking an already-blocked task would overwrite the real reason it was parked
    with a second-hand one, and add a log line saying nothing changed."""
    _, project, alice = await _world(uow_factory)
    task = await _task(
        uow_factory, project.id, assignee=alice.id,
        status=TaskStatus.BLOCKED, status_reason="đợi bên thứ ba trả lời",
    )
    notifier = RecordingNotifier()

    await _fallout(uow_factory, notifier=notifier, bus=TopicEventBus()).agent_went_offline(
        alice.id, now=T0
    )

    async with uow_factory() as uow:
        stored = await uow.tasks.get(task.id)
    assert stored is not None and stored.status_reason == "đợi bên thứ ba trả lời"
    assert notifier.calls == []


@pytest.mark.asyncio
async def test_the_leader_going_offline_goes_straight_to_the_patron(uow_factory) -> None:
    """Telling the Leader its own Leader is gone would be talking into an empty room."""
    ws, project, alice = await _world(uow_factory)
    async with uow_factory() as uow:
        leader_role = next(
            r for r in await uow.roles.list_by_project(project.id) if r.is_leader
        )
        await uow.seat_grants.add(
            SeatGrant(project_id=project.id, role_id=leader_role.id, marius_id=alice.id)
        )
        await uow.commit()

    await _fallout(
        uow_factory, notifier=RecordingNotifier(), bus=TopicEventBus()
    ).agent_went_offline(alice.id, now=T0)

    async with uow_factory() as uow:
        items = list(
            await uow.inbox.list_for_recipient("patron-1", status=InboxItemStatus.PENDING)
        )
    assert items, "Trưởng dự án biến mất mà người chủ không hay biết"
    assert any("Trưởng dự án" in i.title for i in items)


# ── Mức 2 phải có đường ra (FR-059) ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_decision_that_changed_nothing_still_reaches_the_patron(
    uow_factory,
) -> None:
    """The Leader saying it handled something is not the same as it being handled.

    This ladder used to stand down on the sentence alone, which let a Leader answer
    *reassigned it to Bob* — reassigning nothing — and the rung would clear on a task that
    still had nobody scheduled to touch it. A minute later the sweep re-flagged it and the
    whole ladder started again from the bottom: round and round, and because the reset was
    total, the patron was never reached at all.
    """
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    escalator = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=RecordingNotifier(),
        bus=TopicEventBus(),
    )
    for hour in range(4):  # burn the Level-1 budget and reach the Leader
        await escalator.climb(task, cause=CAUSE, now=T0 + timedelta(hours=hour))
    assert (await _ladder(uow_factory, task.id)).level is EscalationLevel.LEVEL_2

    await escalator.leader_decided(
        task.id, action="giao lại cho Bob", now=T0 + timedelta(hours=5)
    )
    still = await _ladder(uow_factory, task.id)
    assert still is not None and still.level is EscalationLevel.LEVEL_2, (
        "cái thang hạ xuống chỉ vì Trưởng dự án nói là đã xử lý"
    )

    for hour in range(6, 18):  # the task never moves
        await escalator.climb(task, cause=CAUSE, now=T0 + timedelta(hours=hour))

    async with uow_factory() as uow:
        items = list(await uow.inbox.list_for_recipient("patron-1"))
    assert [i for i in items if i.kind is InboxItemKind.ESCALATION], (
        "Trưởng dự án quyết mãi mà đầu việc đứng im, người chủ không bao giờ được báo"
    )


@pytest.mark.asyncio
async def test_the_decision_door_is_shut_once_the_question_is_the_patrons(
    uow_factory,
) -> None:
    """Mức 2 is the Leader's window, and both its doors close with it.

    Above it the question belongs to the patron and the Leader is out of it. Leaving this
    door open cost something real: the call closed the patron's escalation on its way
    through, and because the ladder freezes at the top, nothing ever placed that item
    again — the patron was asked, then had the question quietly taken back while the task
    stayed dead. It also *paid* the Leader for talking: one sentence with no action behind
    it removed the last person watching.
    """
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    escalator = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=RecordingNotifier(),
        bus=TopicEventBus(),
    )
    for hour in range(12):  # all the way to the patron
        await escalator.climb(task, cause=CAUSE, now=T0 + timedelta(hours=hour))
    assert (await _ladder(uow_factory, task.id)).level is EscalationLevel.LEVEL_3

    with pytest.raises(NotOnTheLeadersRung):
        await escalator.leader_decided(
            task.id, action="giao lại cho Bob", now=T0 + timedelta(hours=13)
        )

    async with uow_factory() as uow:
        pending = [
            i for i in await uow.inbox.list_for_recipient(
                "patron-1", status=InboxItemStatus.PENDING
            )
            if i.kind is InboxItemKind.ESCALATION
        ]
    assert pending, "câu hỏi của người chủ bị rút về trong khi đầu việc vẫn chết"


@pytest.mark.asyncio
async def test_the_decision_door_is_shut_while_the_system_is_still_trying(
    uow_factory,
) -> None:
    """The mirror of the rule above, and the reason it is a rule and not a special case.

    At Mức 1 nobody has asked the Leader anything yet. A decision recorded there would
    claim a handover that never happened, and the dossier the patron eventually reads is
    built from exactly these records.
    """
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    escalator = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=RecordingNotifier(),
        bus=TopicEventBus(),
    )
    await escalator.climb(task, cause=CAUSE, now=T0)

    with pytest.raises(NotOnTheLeadersRung):
        await escalator.leader_decided(
            task.id, action="giao lại cho Bob", now=T0 + timedelta(minutes=1)
        )


@pytest.mark.asyncio
async def test_standing_down_leaves_the_patrons_letter_alone(uow_factory) -> None:
    """Standing down resets the rung and touches nothing else.

    Closing the letter here was tried and it is circular: a pending letter is one of the
    answers to *is anything going to touch this task*, so writing it un-stalls the task,
    which closed the letter, which stalled it again — while the stored answer said otherwise
    and carried no deadline, so no sweep looked at the task ever again. The letter is the
    patron's; the rung is the ladder's.
    """
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    escalator = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=RecordingNotifier(),
        bus=TopicEventBus(),
    )
    for hour in range(12):
        await escalator.climb(task, cause=CAUSE, now=T0 + timedelta(hours=hour))
    async with uow_factory() as uow:
        assert [
            i for i in await uow.inbox.list_for_recipient(
                "patron-1", status=InboxItemStatus.PENDING
            )
            if i.kind is InboxItemKind.ESCALATION
        ]

    await escalator.stand_down(task.id, now=T0 + timedelta(hours=13))

    settled = await _ladder(uow_factory, task.id)
    assert settled is not None and settled.level is EscalationLevel.NONE
    async with uow_factory() as uow:
        pending = [
            i for i in await uow.inbox.list_for_recipient(
                "patron-1", status=InboxItemStatus.PENDING
            )
            if i.kind is InboxItemKind.ESCALATION
        ]
    assert len(pending) == 1, (
        "xoá nấc thang đã rút mất câu hỏi của người chủ — người chủ chưa trả lời gì cả"
    )


@pytest.mark.asyncio
async def test_the_task_moving_again_takes_it_off_the_ladder(uow_factory) -> None:
    """The one door back to a clean slate, and it is a fact rather than a claim.

    The sweep calls this the moment a flagged task turns out to have a drive again — by the
    Leader's action, by a retry landing, by anything at all. Both budgets come back whole,
    because whatever goes wrong next is a new problem and charging it for this one would
    leave it out of tries before it started.
    """
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    escalator = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=RecordingNotifier(),
        bus=TopicEventBus(),
    )
    for hour in range(4):
        await escalator.climb(task, cause=CAUSE, now=T0 + timedelta(hours=hour))
    assert (await _ladder(uow_factory, task.id)).level is EscalationLevel.LEVEL_2

    await escalator.stand_down(task.id, now=T0 + timedelta(hours=5))

    settled = await _ladder(uow_factory, task.id)
    assert settled is not None
    assert settled.level is EscalationLevel.NONE
    assert settled.attempts == 0 and settled.handover_attempts == 0, (
        "việc chạy lại rồi mà vẫn giữ nợ cũ, nên lần kẹt sau hết ngân sách trước khi bắt đầu"
    )


@pytest.mark.asyncio
async def test_the_leader_can_hand_a_task_straight_to_the_patron(uow_factory) -> None:
    """The second door out of Mức 2, and the reason the first one is bearable.

    A Leader that knows in seconds it cannot help would otherwise have to sit out three
    spaced asks and half an hour, or invent an action so as to look busy. Both cost more
    than letting it say so.
    """
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    escalator = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=RecordingNotifier(),
        bus=TopicEventBus(),
    )
    for hour in range(4):
        await escalator.climb(task, cause=CAUSE, now=T0 + timedelta(hours=hour))

    await escalator.leader_gave_up(
        task.id, reason="kho thành phẩm hỏng, ngoài tầm dự án",
        now=T0 + timedelta(hours=4, minutes=1),
    )

    async with uow_factory() as uow:
        items = list(await uow.inbox.list_for_recipient("patron-1"))
    escalations = [i for i in items if i.kind is InboxItemKind.ESCALATION]
    assert len(escalations) == 1, "Trưởng dự án báo chịu mà người chủ không nhận được gì"
    assert (await _ladder(uow_factory, task.id)).level is EscalationLevel.LEVEL_3


@pytest.mark.asyncio
async def test_the_give_up_door_cannot_be_used_to_skip_a_rung(uow_factory) -> None:
    """The door means *I was asked and it is beyond me*, so it only opens from Mức 2.

    From lower down it would mean something else: the patron handed a task the system has
    not finished trying. FR-059 forbids exactly that, and the rule has to hold against a
    Leader in a hurry the same as against a sweep — a ladder that can be talked into
    skipping is not a ladder.
    """
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    escalator = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=RecordingNotifier(),
        bus=TopicEventBus(),
    )
    await escalator.climb(task, cause=CAUSE, now=T0)  # Mức 1, còn ngân sách

    with pytest.raises(NotOnTheLeadersRung):
        await escalator.leader_gave_up(
            task.id, reason="lười", now=T0 + timedelta(minutes=1)
        )

    async with uow_factory() as uow:
        items = list(await uow.inbox.list_for_recipient("patron-1"))
    assert [i for i in items if i.kind is InboxItemKind.ESCALATION] == [], (
        "người chủ bị gọi về một đầu việc hệ thống còn chưa thử xong"
    )


@pytest.mark.asyncio
async def test_a_silent_leader_is_asked_three_times_before_the_patron(
    uow_factory,
) -> None:
    """Online and silent is treated exactly like offline, and that is the whole point.

    Mức 2 used to have no clock at all, so the sweep sixty seconds later found nothing to
    respect and walked straight past to the patron — less time than an agent needs to read
    the question. An *unreachable* Leader, meanwhile, got three tries over half an hour. The
    rung that could still work was the one given no time.
    """
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    notifier = RecordingNotifier()  # delivers every time; the Leader simply never acts
    escalator = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=notifier, bus=TopicEventBus()
    )

    for minute in range(4):  # four sweeps a minute apart, right after the handover
        await escalator.climb(task, cause=CAUSE, now=T0 + timedelta(hours=3, minutes=minute))

    async with uow_factory() as uow:
        items = list(await uow.inbox.list_for_recipient("patron-1"))
    assert [i for i in items if i.kind is InboxItemKind.ESCALATION] == [], (
        "người chủ bị gọi vào trong vòng vài phút, trước khi Trưởng dự án kịp đọc xong"
    )

    for hour in range(4, 16):
        await escalator.climb(task, cause=CAUSE, now=T0 + timedelta(hours=hour))

    assert len(notifier.calls) == HANDOVER_CAP, (
        f"hỏi Trưởng dự án {len(notifier.calls)} lần, ngân sách là {HANDOVER_CAP}"
    )
    async with uow_factory() as uow:
        items = list(await uow.inbox.list_for_recipient("patron-1"))
    assert [i for i in items if i.kind is InboxItemKind.ESCALATION], (
        "hỏi hết lượt mà đầu việc vẫn đứng im, người chủ vẫn không được báo"
    )


@pytest.mark.asyncio
async def test_the_patron_is_told_once_per_outage_not_once_per_reprobe(
    uow_factory,
) -> None:
    """Found on the running service: two identical escalations, two minutes apart.

    The liveness FSM does not sit still in OFFLINE — it climbs out to CHECKING on a
    doubling backoff, fails the probe, and drops back. Every one of those cycles is a
    genuine *edge* into offline, so checking the edge is not enough on its own: a Leader
    that stays down would post a fresh escalation every backoff period, forever, and the
    patron would mute the channel long before the outage ended.
    """
    ws, project, alice = await _world(uow_factory)
    async with uow_factory() as uow:
        leader_role = next(
            r for r in await uow.roles.list_by_project(project.id) if r.is_leader
        )
        await uow.seat_grants.add(
            SeatGrant(project_id=project.id, role_id=leader_role.id, marius_id=alice.id)
        )
        await uow.commit()
    fallout = _fallout(uow_factory, notifier=RecordingNotifier(), bus=TopicEventBus())

    for cycle in range(4):  # offline → checking → offline → …
        await fallout.agent_went_offline(alice.id, now=T0 + timedelta(minutes=cycle * 2))

    async with uow_factory() as uow:
        items = list(
            await uow.inbox.list_for_recipient("patron-1", status=InboxItemStatus.PENDING)
        )
    leader_items = [i for i in items if i.kind is InboxItemKind.ESCALATION]
    assert len(leader_items) == 1, (
        f"người chủ bị báo {len(leader_items)} lần về đúng một lần Trưởng dự án mất"
    )


@pytest.mark.asyncio
async def test_a_resolved_outage_notice_can_be_raised_again(uow_factory) -> None:
    """The suppression is *while they are looking at it*, not forever. Once the patron has
    handled it and the Leader is still gone, telling them again is new information."""
    ws, project, alice = await _world(uow_factory)
    async with uow_factory() as uow:
        leader_role = next(
            r for r in await uow.roles.list_by_project(project.id) if r.is_leader
        )
        await uow.seat_grants.add(
            SeatGrant(project_id=project.id, role_id=leader_role.id, marius_id=alice.id)
        )
        await uow.commit()
    fallout = _fallout(uow_factory, notifier=RecordingNotifier(), bus=TopicEventBus())

    await fallout.agent_went_offline(alice.id, now=T0)
    async with uow_factory() as uow:
        first = [
            i for i in await uow.inbox.list_for_recipient("patron-1")
            if i.kind is InboxItemKind.ESCALATION
        ][0]
    await InboxService(uow_factory, TopicEventBus()).resolve(first.id)

    await fallout.agent_went_offline(alice.id, now=T0 + timedelta(hours=1))

    async with uow_factory() as uow:
        pending = [
            i for i in await uow.inbox.list_for_recipient(
                "patron-1", status=InboxItemStatus.PENDING
            )
            if i.kind is InboxItemKind.ESCALATION
        ]
    assert len(pending) == 1, "gỡ xong rồi mà lần mất tiếp theo không được báo lại"


# ── Mức 3: giao cho người chủ rồi thì buông tay, và đường về ────────────────────
#
# Every test above drives the ladder by hand. That is exactly how two rounds of bugs got
# through: the ladder is only ever called by the stall sweep, and the sweep re-derives the
# drive *first* — so a rung that behaves correctly under a direct call can still be undone a
# minute later by the loop that owns it. These run the real loop.


def _watchdog(uow_factory, *, ladder, bus, at):
    return StallWatchdog(
        uow_factory,
        PushReasonService(
            uow_factory,
            ProjectService(uow_factory, THRESHOLDS),
            accept_grace_seconds=settings.run_claim_hold_seconds,
        ),
        task_log=TaskLogService(uow_factory),
        control_bus=bus,
        ladder=ladder,
        interval_seconds=0.01,
        clock=lambda: at,
    )


async def _climb_to_the_patron(uow_factory, task, *, escalator, cause=CAUSE):
    """Both budgets, an hour apart so every attempt is due, then flag it as the sweep would."""
    for hour in range(12):
        await escalator.climb(task, cause=cause, now=T0 + timedelta(hours=hour))
    async with uow_factory() as uow:
        stored = await uow.tasks.get(task.id)
        assert stored is not None
        stored.stalled = True
        await uow.tasks.update(stored)
        await uow.commit()


async def _pending_escalations(uow_factory, task_id):
    async with uow_factory() as uow:
        return [
            i
            for i in await uow.inbox.list_pending_for_task(task_id)
            if i.kind is InboxItemKind.ESCALATION
        ]


@pytest.mark.asyncio
async def test_the_letter_survives_the_sweep_that_follows_it(uow_factory) -> None:
    """One sweep after Mức 3, the patron's letter is still there.

    It was not, and that was the whole shape of the bug: a pending letter is one of the six
    answers to *is anything going to touch this task*, so writing it made the task
    un-stalled; standing down then closed the letter; and the task was left holding a stored
    answer with no deadline and no flag, matching no stall-candidate clause ever again.
    Sixty seconds from written to gone, and nobody looked at the task again.

    The rung *does* come down here, and that is correct — the task is not stalled, a named
    human has it. Resetting the rung and closing the letter are two different acts, and only
    the first belongs to the sweep.
    """
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    bus = TopicEventBus()
    escalator = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=RecordingNotifier(), bus=bus
    )
    await _climb_to_the_patron(uow_factory, task, escalator=escalator)
    assert await _pending_escalations(uow_factory, task.id)

    at = T0 + timedelta(hours=13)
    await _watchdog(uow_factory, ladder=escalator, bus=bus, at=at).sweep(at)

    assert await _pending_escalations(uow_factory, task.id), (
        "một lượt quét sau khi hỏi, câu hỏi của người chủ đã bị dọn đi"
    )


@pytest.mark.asyncio
async def test_real_movement_takes_the_rung_down_and_only_the_rung(uow_factory) -> None:
    """A booked wake outranks the wait on the patron, so the task is moving again by the one
    measure the ladder has — and the rung goes, whole budgets and all.

    The letter stays. Nobody has answered it, and the system deciding on the patron's behalf
    that a question they never read has been settled is the same mistake in a nicer suit.
    """
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    bus = TopicEventBus()
    escalator = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=RecordingNotifier(), bus=bus
    )
    await _climb_to_the_patron(uow_factory, task, escalator=escalator)

    at = T0 + timedelta(hours=13)
    async with uow_factory() as uow:
        await uow.wakeups.add(
            WakeupRequest(
                project_id=project.id,
                marius_id=alice.id,
                task_id=task.id,
                source=WakeSource.ON_DEMAND,
                reason="người chủ giao lại",
                created_at=at,
            )
        )
        await uow.commit()
    await _watchdog(uow_factory, ladder=escalator, bus=bus, at=at).sweep(at)

    ladder = await _ladder(uow_factory, task.id)
    assert ladder is not None and ladder.level is EscalationLevel.NONE
    assert ladder.attempts == 0 and ladder.handover_attempts == 0
    assert await _pending_escalations(uow_factory, task.id), (
        "hệ tự đóng câu hỏi của người chủ trong khi họ chưa đọc"
    )


@pytest.mark.asyncio
async def test_the_patron_answering_puts_the_task_back_under_the_net(uow_factory) -> None:
    """The one way back down from Mức 3, and the price of the system letting go.

    Once the letter is written both the system and the agents are out of moves, so nothing
    is gained by sweeping the task every minute — it leaves the net, exactly like any other
    task parked on a human. That is only safe if handing the letter back picks it up again:
    the patron's answer either gave the task a real drive, or it did not, and the second
    case has to become a fresh stall rather than silence.
    """
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    escalator = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=RecordingNotifier(),
        bus=TopicEventBus(),
    )
    await _climb_to_the_patron(uow_factory, task, escalator=escalator)
    item = (await _pending_escalations(uow_factory, task.id))[0]

    await escalator.patron_answered(item.id, now=T0 + timedelta(hours=13))

    settled = await _ladder(uow_factory, task.id)
    assert settled is not None and settled.level is EscalationLevel.NONE, (
        "người chủ đã trả lời mà thang vẫn treo ở Mức 3 — lần kẹt sau không ai được hỏi"
    )
    async with uow_factory() as uow:
        candidates = await uow.tasks.list_stall_candidates(T0 + timedelta(hours=14))
    assert any(c.id == task.id for c in candidates), (
        "trả lời xong mà đầu việc vẫn nằm ngoài tầm lưới — không ai canh nữa"
    )


@pytest.mark.asyncio
async def test_a_changed_cause_does_not_strand_the_patrons_letter(uow_factory) -> None:
    """A different stall reason restarts the budget and can drop the rung to Mức 1 while the
    letter is still in the inbox. Closing the letter must not depend on where the rung is —
    the rung is where the task stands *now*, and *did we ever ask* only ever becomes true.
    """
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    escalator = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=RecordingNotifier(),
        bus=TopicEventBus(),
    )
    await _climb_to_the_patron(uow_factory, task, escalator=escalator)
    item = (await _pending_escalations(uow_factory, task.id))[0]

    await escalator.climb(
        task,
        cause="đã gọi người làm nhưng nó chưa từng bắt đầu",
        now=T0 + timedelta(hours=13),
    )
    assert (await _ladder(uow_factory, task.id)).level is EscalationLevel.LEVEL_1

    await escalator.patron_answered(item.id, now=T0 + timedelta(hours=14))

    assert await _pending_escalations(uow_factory, task.id) == []
    settled = await _ladder(uow_factory, task.id)
    assert settled is not None and settled.level is EscalationLevel.NONE, (
        "người chủ trả lời rồi mà nấc thang vẫn treo vì nguyên nhân đã đổi giữa chừng"
    )


@pytest.mark.asyncio
async def test_the_patron_is_never_handed_the_same_task_twice(uow_factory) -> None:
    """Two letters, same task, same title, different reason — and the reminder ladder
    chasing both. The Leader-is-gone path already asks the inbox before it writes."""
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    escalator = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=RecordingNotifier(),
        bus=TopicEventBus(),
    )
    await _climb_to_the_patron(uow_factory, task, escalator=escalator)

    other = "đã gọi người làm nhưng nó chưa từng bắt đầu"
    for hour in range(13, 25):
        await escalator.climb(task, cause=other, now=T0 + timedelta(hours=hour))

    assert (await _ladder(uow_factory, task.id)).level is EscalationLevel.LEVEL_3
    waiting = await _pending_escalations(uow_factory, task.id)
    assert len(waiting) == 1, f"người chủ ôm {len(waiting)} lá thư cho cùng một đầu việc"


@pytest.mark.asyncio
async def test_a_task_that_recovers_onto_a_different_question_still_leaves_the_ladder(
    uow_factory,
) -> None:
    """The skip must catch the ladder's *own* letter, not every wait on a human.

    A pending inbox item of **any** kind parks the task on a patron, and the drive rules do
    not record which kind — so a rule written against the drive kind catches the commonest
    healthy shape there is: the ladder worked, the assignee was woken, the work landed, and
    now the patron holds a waiting-for-acceptance item. Skip the stand-down there and the
    rung outlives the problem it was measuring.

    The bill arrives on the *next* stall, which starts halfway up: no Level-1 retry at all,
    straight to the Leader, carrying a dossier of attempts that belong to a problem already
    solved. That is the no-skipping rule of FR-059 broken from the inside, and it is worst
    in the case where the ladder had actually succeeded.
    """
    ws, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    bus = TopicEventBus()
    escalator = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=RecordingNotifier(), bus=bus
    )
    for hour in range(4):
        await escalator.climb(task, cause=CAUSE, now=T0 + timedelta(hours=hour))
    assert (await _ladder(uow_factory, task.id)).level is EscalationLevel.LEVEL_2
    async with uow_factory() as uow:
        stored = await uow.tasks.get(task.id)
        assert stored is not None
        stored.stalled = True
        await uow.tasks.update(stored)
        await uow.commit()

    # The work came back and stopped on the patron — a different question entirely.
    await InboxService(uow_factory, bus).place(
        workspace_id=ws.id,
        recipient_user_id="patron-1",
        kind=InboxItemKind.OUTPUT_ACCEPTANCE,
        title="Có thành phẩm chờ bạn công nhận",
        project_id=project.id,
        task_id=task.id,
    )

    at = T0 + timedelta(hours=5)
    await _watchdog(uow_factory, ladder=escalator, bus=bus, at=at).sweep(at)

    settled = await _ladder(uow_factory, task.id)
    assert settled is not None and settled.level is EscalationLevel.NONE, (
        "đầu việc hồi phục rồi mà nấc thang nằm lại — lần kẹt sau sẽ nhảy cóc qua Mức 1"
    )
    assert settled.attempts == 0 and settled.handover_attempts == 0


# ── Câu trả lời của người chủ: một quyết định, một lần chốt ──────────────────────


def _tasks_for(uow_factory, wakes):
    """A task service whose wakes are counted, wired like the composition root wires it."""
    return TaskService(
        uow_factory,
        wakes,
        task_logs=TaskLogService(uow_factory),
        push_reasons=PushReasonService(
            uow_factory,
            ProjectService(uow_factory, THRESHOLDS),
            accept_grace_seconds=settings.run_claim_hold_seconds,
        ),
    )


def _answering_escalator(uow_factory, *, wakes, bus, tasks):
    return RecoveryEscalator(
        uow_factory,
        ProjectService(uow_factory, THRESHOLDS),
        wakes=wakes,
        inbox=InboxService(uow_factory, bus),
        task_log=TaskLogService(uow_factory),
        control_bus=bus,
        leader_notifier=RecordingNotifier(),
        push_reasons=PushReasonService(
            uow_factory,
            ProjectService(uow_factory, THRESHOLDS),
            accept_grace_seconds=settings.run_claim_hold_seconds,
        ),
        tasks=tasks,
    )


async def _letter_for(uow_factory, task_id):
    letters = await _pending_escalations(uow_factory, task_id)
    assert letters, "chưa có lá thư nào để trả lời"
    return letters[0]


async def _reload(uow_factory, task_id):
    async with uow_factory() as uow:
        return await uow.tasks.get(task_id)


async def _letter_status(uow_factory, item_id):
    async with uow_factory() as uow:
        item = await uow.inbox.get(item_id)
        assert item is not None
        return item.status


@pytest.mark.asyncio
async def test_the_answer_moves_the_task_and_closes_the_letter_together(
    uow_factory,
) -> None:
    ws, project, alice = await _world(uow_factory)
    bob = await make_agent(uow_factory, 
        workspace_id=ws.id, name="Bob", role="Backend", skills=[],
        adapter_type="echo", adapter_config={},
    )
    task = await _task(uow_factory, project.id, assignee=alice.id)
    bus = TopicEventBus()
    task_wakes = RecordingWakes()
    escalator = _answering_escalator(
        uow_factory, wakes=RecordingWakes(), bus=bus,
        tasks=_tasks_for(uow_factory, task_wakes),
    )
    await _climb_to_the_patron(uow_factory, task, escalator=escalator)
    letter = await _letter_for(uow_factory, task.id)

    await escalator.answer_escalation(
        letter.id,
        answer=EscalationAnswer.REASSIGN,
        marius_id=bob.id,
        text="Alice treo, chuyển sang Bob.",
        recipient_user_id="patron-1",
        now=T0 + timedelta(hours=13),
    )

    assert (await _reload(uow_factory, task.id)).assigned_marius_id == bob.id
    assert await _letter_status(uow_factory, letter.id) is InboxItemStatus.RESOLVED
    assert (await _ladder(uow_factory, task.id)).level is EscalationLevel.NONE
    assert [c["marius_id"] for c in task_wakes.calls] == [bob.id], (
        "người mới phải được gọi đúng một lần cho một sự cố"
    )


@pytest.mark.asyncio
async def test_answering_the_same_letter_twice_does_nothing_the_second_time(
    uow_factory,
) -> None:
    """The reflex that used to cost a second wake.

    A patron who sees an error presses again — the most natural thing there is. Before the
    answer landed as one fact, that second press ran the assignment a second time and woke
    the new owner twice for one incident. The letter is the record of the decision, so the
    letter is what makes a repeat a no-op.
    """
    ws, project, alice = await _world(uow_factory)
    bob = await make_agent(uow_factory, 
        workspace_id=ws.id, name="Bob", role="Backend", skills=[],
        adapter_type="echo", adapter_config={},
    )
    task = await _task(uow_factory, project.id, assignee=alice.id)
    bus = TopicEventBus()
    task_wakes = RecordingWakes()
    escalator = _answering_escalator(
        uow_factory, wakes=RecordingWakes(), bus=bus,
        tasks=_tasks_for(uow_factory, task_wakes),
    )
    await _climb_to_the_patron(uow_factory, task, escalator=escalator)
    letter = await _letter_for(uow_factory, task.id)

    for _ in range(3):
        await escalator.answer_escalation(
            letter.id,
            answer=EscalationAnswer.REASSIGN,
            marius_id=bob.id,
            text="Alice treo, chuyển sang Bob.",
            recipient_user_id="patron-1",
            now=T0 + timedelta(hours=13),
        )

    assert len(task_wakes.calls) == 1, (
        f"bấm lại làm người mới bị gọi dậy {len(task_wakes.calls)} lần cho một sự cố"
    )


@pytest.mark.asyncio
async def test_cancelling_from_the_letter_survives_being_pressed_again(
    uow_factory,
) -> None:
    """A cancelled task has nowhere left to go, so a second cancel used to throw — and the
    letter could then never be closed from that button at all."""
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    bus = TopicEventBus()
    escalator = _answering_escalator(
        uow_factory, wakes=RecordingWakes(), bus=bus,
        tasks=_tasks_for(uow_factory, RecordingWakes()),
    )
    await _climb_to_the_patron(uow_factory, task, escalator=escalator)
    letter = await _letter_for(uow_factory, task.id)

    for _ in range(2):
        await escalator.answer_escalation(
            letter.id,
            answer=EscalationAnswer.CANCEL,
            text="Khách đổi ý, bỏ hạng mục này.",
            recipient_user_id="patron-1",
            now=T0 + timedelta(hours=13),
        )

    assert (await _reload(uow_factory, task.id)).status is TaskStatus.CANCELLED
    assert await _letter_status(uow_factory, letter.id) is InboxItemStatus.RESOLVED


@pytest.mark.asyncio
async def test_an_answer_that_fails_leaves_the_question_standing(uow_factory) -> None:
    """The whole reason the answer is one transaction (FR-061e).

    If the action fails after the letter has been closed, the patron loses the question and
    the task stays stuck — the one direction this must never break in. Under a single
    commit there is no such half: the failure takes the close down with it, and the screen
    still shows what it showed before.
    """
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    bus = TopicEventBus()
    escalator = _answering_escalator(
        uow_factory, wakes=RecordingWakes(), bus=bus,
        tasks=_tasks_for(uow_factory, RecordingWakes()),
    )
    await _climb_to_the_patron(uow_factory, task, escalator=escalator)
    letter = await _letter_for(uow_factory, task.id)
    rung_before = (await _ladder(uow_factory, task.id)).level

    with pytest.raises(LookupError):
        await escalator.answer_escalation(
            letter.id,
            answer=EscalationAnswer.REASSIGN,
            marius_id=UUID("00000000-0000-0000-0000-0000000000ff"),  # nobody
            text="Chuyển cho người không tồn tại.",
            recipient_user_id="patron-1",
            now=T0 + timedelta(hours=13),
        )

    assert await _letter_status(uow_factory, letter.id) is InboxItemStatus.PENDING, (
        "hành động hỏng mà lá thư đã đóng — người chủ mất câu hỏi và đầu việc vẫn kẹt"
    )
    assert (await _reload(uow_factory, task.id)).assigned_marius_id == alice.id
    assert (await _ladder(uow_factory, task.id)).level is rung_before


@pytest.mark.asyncio
async def test_someone_elses_letter_is_not_found(uow_factory) -> None:
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    bus = TopicEventBus()
    escalator = _answering_escalator(
        uow_factory, wakes=RecordingWakes(), bus=bus,
        tasks=_tasks_for(uow_factory, RecordingWakes()),
    )
    await _climb_to_the_patron(uow_factory, task, escalator=escalator)
    letter = await _letter_for(uow_factory, task.id)

    with pytest.raises(LookupError):
        await escalator.answer_escalation(
            letter.id,
            answer=EscalationAnswer.HANDLED,
            recipient_user_id="patron-2",
            now=T0 + timedelta(hours=13),
        )
    assert await _letter_status(uow_factory, letter.id) is InboxItemStatus.PENDING
