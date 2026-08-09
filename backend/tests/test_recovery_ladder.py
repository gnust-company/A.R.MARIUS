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
from armarius.application.use_cases.mariuses import MariusService
from armarius.application.use_cases.projects import ProjectService
from armarius.application.use_cases.push_reason import PushReasonService
from armarius.application.use_cases.recovery import (
    OfflineFalloutService,
    RecoveryEscalator,
)
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
from armarius.domain.services.escalation import EscalationLevel
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus
from armarius.infrastructure.events.topic_bus import TopicEventBus, patron_topic
from tests.support.projects import force_phase

T0 = datetime(2026, 8, 6, 10, 0, 0, tzinfo=UTC)
CAP = 3
CAUSE = "không có gì được hẹn để đẩy đầu việc này đi tiếp"

THRESHOLDS = ProjectThresholds(
    hang_suspect_seconds=600,
    hang_grace_seconds=120,
    orchestration_cadence_seconds=900,
    task_silence_seconds=300,
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
        self, *, project_id: UUID, text: str, source: WakeSource, reason: str
    ) -> bool:
        self.calls.append({"project_id": project_id, "text": text, "reason": reason})
        return True


async def _world(uow_factory, *, patron: str = "patron-1"):
    """A running project with a named patron, a Leader seat, and one worker.

    The project is written through the repository rather than nudged afterwards:
    `created_by_user_id` is set at creation and never rewritten by `update`, so a test that
    tried to patch it in place would be asserting against a write path that does not exist.
    """
    ws = await WorkspaceService(uow_factory).create_workspace("WS")
    alice = await MariusService(uow_factory).register(
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
    assert "đình trệ" in notifier.calls[0]["text"]
    ladder = await _ladder(uow_factory, task.id)
    assert ladder is not None and ladder.level >= EscalationLevel.LEVEL_2


class UnreachableNotifier:
    """A Leader that cannot be reached — offline, or already mid-turn.

    The real notifier answers this with a return value, not an exception: it still writes a
    durable wake request, then reports False. Every fake in this suite answered True
    unconditionally, so the whole not-delivered branch had no coverage at all.
    """

    def __init__(self) -> None:
        self.attempts: list[dict] = []

    async def notify(
        self, *, project_id: UUID, text: str, source: WakeSource, reason: str
    ) -> bool:
        self.attempts.append({"project_id": project_id, "text": text, "reason": reason})
        return False


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
async def test_an_unreachable_leader_does_not_get_the_patron_told_they_were_asked(
    uow_factory,
) -> None:
    """The rule this rung exists for: never report a step that did not happen.

    A dossier that says the Leader was asked, about a project whose Leader was never
    reached, spends the patron's attention on a false premise — and once a dossier has
    lied, the next one is read as decoration.
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
    assert escalations == [], (
        "người chủ bị báo là Trưởng dự án đã được hỏi, trong khi lời hỏi chưa từng tới nơi"
    )
    ladder = await _ladder(uow_factory, task.id)
    assert ladder is not None and ladder.level < EscalationLevel.LEVEL_3, (
        "cái thang trèo lên Mức 3 trên một Mức 2 chưa hề xảy ra"
    )


@pytest.mark.asyncio
async def test_the_budget_is_not_spent_again_while_the_leader_is_unreachable(
    uow_factory,
) -> None:
    """Putting the rung back down is not a retreat to Level 1's behaviour.

    The budget stays spent, so the assignee is not re-woken all over again for a problem the
    system has already admitted it cannot fix on its own; the ladder simply has not handed
    over yet. Without this, an unreachable Leader would turn the ladder into an infinite
    Level-1 loop and the whole point of the budget would be gone.
    """
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    wakes = RecordingWakes()
    escalator = _escalator(
        uow_factory, wakes=wakes, notifier=UnreachableNotifier(), bus=TopicEventBus()
    )

    for hour in range(12):
        await escalator.climb(task, cause=CAUSE, now=T0 + timedelta(hours=hour))

    assert len(wakes.calls) == CAP, (
        f"tự gọi lại {len(wakes.calls)} lần, trần là {CAP} — ngân sách bị tiêu lại"
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
    assert "leo-thang.muc-3" in types


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
        push_reasons=PushReasonService(uow_factory, ProjectService(uow_factory, THRESHOLDS)),
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
        await uow.seat_grants.add(
            SeatGrant(project_id=project.id, role_key="leader", marius_id=alice.id)
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
async def test_the_leader_naming_an_action_takes_the_task_off_the_ladder(
    uow_factory,
) -> None:
    """Without this door Level 2 is a rung with no way off it: the ladder waits for a
    decision that has nowhere to be recorded, and the next sweep climbs to the patron
    anyway — telling them nobody decided, while the Leader was deciding."""
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    escalator = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=RecordingNotifier(),
        bus=TopicEventBus(),
    )
    for hour in range(4):  # burn the budget and reach the Leader
        await escalator.climb(task, cause=CAUSE, now=T0 + timedelta(hours=hour))
    assert (await _ladder(uow_factory, task.id)).level is EscalationLevel.LEVEL_2

    await escalator.leader_decided(
        task.id, action="chẻ đôi đầu việc và giao phần hạ tầng cho người khác",
        now=T0 + timedelta(hours=5),
    )

    settled = await _ladder(uow_factory, task.id)
    assert settled is not None
    assert settled.level is EscalationLevel.NONE
    assert settled.attempts == 0, (
        "quyết xong mà vẫn giữ nợ cũ, nên lần kẹt sau đã hết ngân sách trước khi bắt đầu"
    )


@pytest.mark.asyncio
async def test_the_patron_is_never_reached_once_the_leader_has_decided(
    uow_factory,
) -> None:
    _, project, alice = await _world(uow_factory)
    task = await _task(uow_factory, project.id, assignee=alice.id)
    escalator = _escalator(
        uow_factory, wakes=RecordingWakes(), notifier=RecordingNotifier(),
        bus=TopicEventBus(),
    )
    for hour in range(4):
        await escalator.climb(task, cause=CAUSE, now=T0 + timedelta(hours=hour))
    await escalator.leader_decided(
        task.id, action="giao lại cho Bob", now=T0 + timedelta(hours=5)
    )

    # The task is still stuck, so the sweep keeps climbing — but from the bottom.
    await escalator.climb(task, cause=CAUSE, now=T0 + timedelta(hours=6))

    async with uow_factory() as uow:
        items = list(await uow.inbox.list_for_recipient("patron-1"))
    assert [i for i in items if i.kind is InboxItemKind.ESCALATION] == [], (
        "Trưởng dự án vừa quyết xong mà người chủ đã bị gọi"
    )
    assert (await _ladder(uow_factory, task.id)).level is EscalationLevel.LEVEL_1


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
        await uow.seat_grants.add(
            SeatGrant(project_id=project.id, role_key="leader", marius_id=alice.id)
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
        await uow.seat_grants.add(
            SeatGrant(project_id=project.id, role_key="leader", marius_id=alice.id)
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
