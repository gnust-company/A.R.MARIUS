"""The plan approval gate, as pure rules (spec 001 FR-011 → FR-014).

The gate is where "the system never decides for you" becomes code. Three choices belong
to the patron and only the patron; the Leader who wrote the plan cannot wave its own plan
through, and asking for changes leaves the project exactly where it was.
"""

from __future__ import annotations

import pytest

from armarius.domain.entities.plan import PlanStatus
from armarius.domain.entities.project import ProjectStatus
from armarius.domain.services.plan_gate import (
    PlanDecision,
    PlanGateError,
    SelfApprovalError,
    can_leave_planning,
    decide,
)


# ── the three choices (FR-013) ────────────────────────────────────────────────────
def test_approve_moves_plan_and_project_forward() -> None:
    outcome = decide(PlanStatus.SUBMITTED, PlanDecision.APPROVE, decider_is_leader=False)

    assert outcome.plan_status is PlanStatus.APPROVED
    assert outcome.next_phase is ProjectStatus.OPERATING
    assert outcome.wake_leader is True
    assert outcome.next_action  # the Leader is told what to do next, in words


def test_request_changes_keeps_the_project_in_planning() -> None:
    outcome = decide(
        PlanStatus.SUBMITTED,
        PlanDecision.REQUEST_CHANGES,
        decider_is_leader=False,
        note="Chia nhỏ hạng mục 2 ra.",
    )

    assert outcome.plan_status is PlanStatus.CHANGES_REQUESTED
    assert outcome.next_phase is None  # stays put — nothing was approved
    assert outcome.wake_leader is True
    assert "Chia nhỏ" in (outcome.note or "")


def test_ask_back_leaves_the_plan_submitted() -> None:
    """A question is not a verdict: the plan is still on the table, still awaiting one."""
    outcome = decide(
        PlanStatus.SUBMITTED,
        PlanDecision.ASK_BACK,
        decider_is_leader=False,
        note="Sao hạng mục 3 lại cần hai người?",
    )

    assert outcome.plan_status is PlanStatus.SUBMITTED
    assert outcome.next_phase is None
    assert outcome.wake_leader is True


@pytest.mark.parametrize(
    "decision", [PlanDecision.REQUEST_CHANGES, PlanDecision.ASK_BACK]
)
def test_changes_and_questions_must_say_why(decision: PlanDecision) -> None:
    with pytest.raises(PlanGateError):
        decide(PlanStatus.SUBMITTED, decision, decider_is_leader=False, note="   ")


# ── the Leader cannot approve its own plan (FR-014) ───────────────────────────────
@pytest.mark.parametrize("decision", list(PlanDecision))
def test_leader_cannot_decide_on_its_own_plan(decision: PlanDecision) -> None:
    with pytest.raises(SelfApprovalError):
        decide(PlanStatus.SUBMITTED, decision, decider_is_leader=True, note="ok")


# ── you can only decide on a plan that is actually on the table ───────────────────
@pytest.mark.parametrize(
    "plan_status", [PlanStatus.DRAFT, PlanStatus.APPROVED, PlanStatus.CHANGES_REQUESTED]
)
def test_cannot_decide_on_a_plan_that_is_not_submitted(plan_status: PlanStatus) -> None:
    with pytest.raises(PlanGateError):
        decide(plan_status, PlanDecision.APPROVE, decider_is_leader=False)


# ── leaving PLANNING needs both an approved context and an approved plan ──────────
@pytest.mark.parametrize(
    ("context_approved", "plan_status", "expected"),
    [
        (True, PlanStatus.APPROVED, True),
        (False, PlanStatus.APPROVED, False),
        (True, PlanStatus.SUBMITTED, False),
        (True, PlanStatus.CHANGES_REQUESTED, False),
        (False, PlanStatus.DRAFT, False),
        (True, None, False),  # no plan at all
    ],
)
def test_can_leave_planning(
    context_approved: bool, plan_status: PlanStatus | None, expected: bool
) -> None:
    assert can_leave_planning(context_approved, plan_status) is expected


# ── cổng thay đổi lớn và chuyển tiếp sạch (FR-075, FR-076) ──────────────────────
#
# FR-074 already lets the Leader run the project: split work up, reorder it, swap who does
# it, change *how* the same outcome is reached. Five things are not that, because each of
# them changes what the patron agreed to — and a system that lets an agent quietly move any
# of them is a system nobody can hand a budget.

from uuid import uuid4  # noqa: E402

import pytest  # noqa: E402

from armarius.application.use_cases.inbox import InboxService  # noqa: E402
from armarius.application.use_cases.plans import (  # noqa: E402
    MajorChangeArea,
    PlanningError,
    PlanService,
)
from armarius.application.use_cases.task_log import TaskLogService  # noqa: E402
from armarius.application.use_cases.workspaces import WorkspaceService  # noqa: E402
from armarius.domain.entities.inbox_item import InboxItemKind  # noqa: E402
from armarius.domain.entities.plan import Plan, PlanItem, PlanStatus  # noqa: E402
from armarius.domain.entities.project import Project  # noqa: E402
from armarius.domain.entities.task import Task, TaskStatus  # noqa: E402
from armarius.infrastructure.events.topic_bus import TopicEventBus  # noqa: E402


def _plans(uow_factory, bus=None) -> PlanService:
    bus = bus or TopicEventBus()
    return PlanService(
        uow_factory,
        control_bus=bus,
        inbox=InboxService(uow_factory, bus),
        leader_chat=None,  # type: ignore[arg-type]
        task_logs=TaskLogService(uow_factory),
    )


async def _project_with_patron(uow_factory, patron: str = "patron-1"):
    ws = await WorkspaceService(uow_factory).create_workspace("WS")
    async with uow_factory() as uow:
        project = await uow.projects.add(
            Project(
                workspace_id=ws.id, name="P", slug="p", key="P1",
                created_by_user_id=patron,
            )
        )
        await uow.commit()
    return project


@pytest.mark.asyncio
@pytest.mark.parametrize("area", list(MajorChangeArea))
async def test_each_of_the_five_areas_parks_on_the_patron(uow_factory, area) -> None:
    project = await _project_with_patron(uow_factory)

    item = await _plans(uow_factory).request_major_change(
        project.id, area=area, summary="Cần nới thêm một tuần"
    )

    assert item.kind is InboxItemKind.MAJOR_CHANGE_APPROVAL
    assert item.recipient_user_id == "patron-1"
    assert item.project_id == project.id


@pytest.mark.asyncio
async def test_asking_does_not_apply_the_change(uow_factory) -> None:
    """The gate is the point. A method that parked the question *and* made the change would
    make it a formality — which is the failure mode this requirement exists to prevent."""
    project = await _project_with_patron(uow_factory)
    before = project.status

    await _plans(uow_factory).request_major_change(
        project.id, area=MajorChangeArea.DEADLINE, summary="Lùi hạn hai tuần"
    )

    async with uow_factory() as uow:
        after = await uow.projects.get(project.id)
    assert after is not None and after.status == before


@pytest.mark.asyncio
async def test_a_project_with_nobody_to_ask_refuses_rather_than_proceeding(
    uow_factory,
) -> None:
    """Failing shut. A change that widens the deal with no patron to approve it must not
    slip through just because the routing came up empty."""
    ws = await WorkspaceService(uow_factory).create_workspace("WS")
    async with uow_factory() as uow:
        stored = await uow.workspaces.get(ws.id)
        stored.owner_user_id = None
        await uow.workspaces.update(stored)
        project = await uow.projects.add(
            Project(workspace_id=ws.id, name="P", slug="p", key="P2")
        )
        await uow.commit()

    with pytest.raises(PlanningError):
        await _plans(uow_factory).request_major_change(
            project.id, area=MajorChangeArea.SCOPE, summary="Thêm một mảng mới"
        )


@pytest.mark.asyncio
async def test_a_replan_leaves_no_task_pointing_at_a_retired_item(uow_factory) -> None:
    """FR-076. A task attached to a plan item that no longer exists is neither in scope nor
    cancelled: every gate that asks "is this in the approved plan?" says no, while the board
    keeps showing it as live work."""
    project = await _project_with_patron(uow_factory)
    async with uow_factory() as uow:
        kept = PlanItem(title="Giữ lại", order=1)
        plan = await uow.plans.add(
            Plan(project_id=project.id, version=2, status=PlanStatus.APPROVED, items=[kept])
        )
        orphan = await uow.tasks.add(
            Task(
                project_id=project.id, title="Bám hạng mục đã bị thay",
                status=TaskStatus.IN_PROGRESS, plan_item_id=uuid4(),
            )
        )
        safe = await uow.tasks.add(
            Task(
                project_id=project.id, title="Vẫn trong kế hoạch",
                status=TaskStatus.IN_PROGRESS, plan_item_id=plan.items[0].id,
            )
        )
        await uow.commit()

    settled = await _plans(uow_factory).settle_orphaned_tasks(project.id)

    assert settled == [orphan.id]
    async with uow_factory() as uow:
        assert (await uow.tasks.get(orphan.id)).status is TaskStatus.DRAFT
        assert (await uow.tasks.get(safe.id)).status is TaskStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_finished_work_keeps_its_history_after_a_replan(uow_factory) -> None:
    """A closed task's dead pointer is history, not an orphan — rewriting it would edit the
    record of what was actually delivered."""
    project = await _project_with_patron(uow_factory)
    async with uow_factory() as uow:
        await uow.plans.add(
            Plan(project_id=project.id, version=2, status=PlanStatus.APPROVED, items=[])
        )
        done = await uow.tasks.add(
            Task(
                project_id=project.id, title="Đã xong từ đợt trước",
                status=TaskStatus.DONE, plan_item_id=uuid4(),
            )
        )
        await uow.commit()

    assert await _plans(uow_factory).settle_orphaned_tasks(project.id) == []
    async with uow_factory() as uow:
        assert (await uow.tasks.get(done.id)).status is TaskStatus.DONE
