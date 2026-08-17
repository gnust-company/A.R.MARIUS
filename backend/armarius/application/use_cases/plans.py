"""Project context and plan use cases (spec 001 FR-007 → FR-014).

The Story-1 loop lives here: the Leader submits a context and a plan, the patron decides,
and only an approval opens the door to real work. Three things this module is careful
about, because they are the whole point of the feature:

- **It never decides.** A submitted plan parks in the patron's inbox and stays there.
  Nothing here approves anything on anyone's behalf.
- **It always leaves a trail.** Every submission and every decision publishes on the
  project channel and lands in the durable record, so the board updates without polling
  (Constitution IV) and the history answers "who decided what, when".
- **It never edits in place.** A revised context or plan is a new version; the approved
  one keeps working until the patron says otherwise (FR-010).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from armarius.application.ports.unit_of_work import UnitOfWork
from armarius.application.use_cases.inbox import InboxService
from armarius.application.use_cases.leader_chat import LeaderChatService
from armarius.application.use_cases.task_log import TaskLogService
from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.inbox_item import InboxItem, InboxItemKind
from armarius.domain.entities.plan import Plan, PlanItem, PlanStatus
from armarius.domain.entities.project import Project, ProjectStatus
from armarius.domain.entities.project_context import (
    ContextApprovalStatus,
    ProjectContext,
)
from armarius.domain.entities.run import WakeSource
from armarius.domain.entities.task import TaskStatus
from armarius.domain.entities.task_log import ActorKind, TaskLogKind
from armarius.domain.services import plan_gate, project_rules
from armarius.domain.services.project_rules import ProjectClosed
from armarius.domain.services.wake_reason import WakeReason
from armarius.domain.services.wake_reason import reason as wake_reason
from armarius.infrastructure.events.topic_bus import TopicEventBus, project_topic
from armarius.shared.clock import utcnow

EVENT_PLAN_SUBMITTED = "plan.submitted"
EVENT_PLAN_DECIDED = "plan.decided"
EVENT_PHASE_CHANGED = "project.phase_changed"
EVENT_CONTEXT_SUBMITTED = "context.submitted"
EVENT_CONTEXT_DECIDED = "context.decided"
EVENT_MAJOR_CHANGE_REQUESTED = "thay-doi-lon.trinh"


class PlanningError(Exception):
    """Raised when a context/plan action does not fit the project's current phase."""


@dataclass(frozen=True)
class PlanItemSpec:
    """One plan item as the Leader submits it."""

    title: str
    description: str = ""
    order: int = 0
    definition_of_done: str = ""
    depends_on: list[UUID] | None = None


class MajorChangeArea(StrEnum):
    """The five things a Leader may not change on its own (FR-075).

    A closed list, and short on purpose. Everything *not* here is the Leader's to
    decide (FR-074) — a gate that catches everything is a gate that gets routed around.
    """

    SCOPE = "scope"
    OBJECTIVE = "objective"
    COST = "cost"
    DEADLINE = "deadline"
    ACCEPTANCE = "acceptance"


MAJOR_CHANGE_LABELS: dict[MajorChangeArea, str] = {
    MajorChangeArea.SCOPE: "phạm vi",
    MajorChangeArea.OBJECTIVE: "mục tiêu / Bối cảnh",
    MajorChangeArea.COST: "chi phí",
    MajorChangeArea.DEADLINE: "thời hạn",
    MajorChangeArea.ACCEPTANCE: "tiêu chí công nhận",
}


class PlanService:
    def __init__(
        self,
        uow_factory: UowFactory,
        *,
        control_bus: TopicEventBus,
        inbox: InboxService,
        leader_chat: LeaderChatService,
        task_logs: TaskLogService | None = None,
    ) -> None:
        self._uow = uow_factory
        self._bus = control_bus
        self._inbox = inbox
        self._leader_chat = leader_chat
        self._task_logs = task_logs

    # ── reads ────────────────────────────────────────────────────────────────────
    async def get_context(
        self, project_id: UUID
    ) -> tuple[ProjectContext | None, ProjectContext | None]:
        """(approved, pending). The approved one is what wake packets carry (FR-009)."""
        async with self._uow() as uow:
            return (
                await uow.project_contexts.get_approved(project_id),
                await uow.project_contexts.get_pending(project_id),
            )

    async def get_plan(self, project_id: UUID) -> Plan | None:
        async with self._uow() as uow:
            return await uow.plans.get_current(project_id)

    # ── the Leader submits ───────────────────────────────────────────────────────
    async def submit_context(
        self,
        project_id: UUID,
        *,
        objective: str = "",
        background: str = "",
        constraints: str = "",
        scope: str = "",
        principles: str = "",
    ) -> ProjectContext:
        """Submit a context version for approval (FR-008, FR-010).

        Always a new version — the approved one stays in force until the patron moves it,
        so an edit can never quietly change what the team is working towards.
        """
        async with self._uow() as uow:
            project = await self._writable(uow, project_id)
            now = utcnow()
            context = ProjectContext(
                project_id=project_id,
                version=await uow.project_contexts.latest_version(project_id) + 1,
                objective=objective,
                background=background,
                constraints=constraints,
                scope=scope,
                principles=principles,
                approval_status=ContextApprovalStatus.SUBMITTED,
                created_at=now,
                updated_at=now,
            )
            await uow.project_contexts.add(context)
            await uow.commit()
            workspace_id = project.workspace_id
            recipient = project.created_by_user_id

        await self._publish(
            project_id, EVENT_CONTEXT_SUBMITTED, {"version": context.version}
        )
        if recipient and workspace_id:
            await self._inbox.place(
                workspace_id=workspace_id,
                recipient_user_id=recipient,
                kind=InboxItemKind.PLAN_APPROVAL,
                title="Bối cảnh dự án chờ bạn duyệt",
                body=objective or None,
                project_id=project_id,
            )
        return context

    async def submit_plan(
        self,
        project_id: UUID,
        *,
        summary: str = "",
        risks: str = "",
        milestones: str = "",
        items: list[PlanItemSpec] | None = None,
    ) -> Plan:
        """Submit a plan version and park it in the patron's inbox (FR-011, FR-012)."""
        async with self._uow() as uow:
            project = await self._writable(uow, project_id)
            if project.status is not ProjectStatus.PLANNING:
                raise PlanningError(
                    f"A plan can only be submitted while planning (project is '{project.status}')."
                )
            now = utcnow()
            plan = Plan(
                project_id=project_id,
                version=await uow.plans.latest_version(project_id) + 1,
                summary=summary,
                risks=risks,
                milestones=milestones,
                status=PlanStatus.SUBMITTED,
                submitted_at=now,
                created_at=now,
                updated_at=now,
                items=[
                    PlanItem(
                        title=spec.title,
                        description=spec.description,
                        order=spec.order or index,
                        definition_of_done=spec.definition_of_done,
                        depends_on=list(spec.depends_on or []),
                        created_at=now,
                    )
                    for index, spec in enumerate(items or [], start=1)
                ],
            )
            await uow.plans.add(plan)
            await uow.commit()
            workspace_id = project.workspace_id
            recipient = project.created_by_user_id

        await self._publish(
            project_id,
            EVENT_PLAN_SUBMITTED,
            {"version": plan.version, "items": len(plan.items)},
        )
        if recipient and workspace_id:
            await self._inbox.place(
                workspace_id=workspace_id,
                recipient_user_id=recipient,
                kind=InboxItemKind.PLAN_APPROVAL,
                title="Kế hoạch dự án chờ bạn duyệt",
                body=summary or None,
                project_id=project_id,
            )
        return plan

    # ── the patron decides ───────────────────────────────────────────────────────
    async def approve_context(
        self, project_id: UUID, *, user_id: str, approve: bool, note: str | None = None
    ) -> ProjectContext:
        """Approve or send back the pending context version (FR-008)."""
        async with self._uow() as uow:
            await self._writable(uow, project_id)
            pending = await uow.project_contexts.get_pending(project_id)
            if pending is None:
                raise PlanningError("There is no context version awaiting a decision.")
            now = utcnow()
            if approve:
                pending.approval_status = ContextApprovalStatus.APPROVED
                pending.approved_at = now
                pending.approved_by_user_id = user_id
            else:
                if not (note or "").strip():
                    raise PlanningError("Sending a context back must say why.")
                pending.approval_status = ContextApprovalStatus.DRAFT
            pending.updated_at = now
            await uow.project_contexts.update(pending)
            await uow.commit()

        await self._publish(
            project_id,
            EVENT_CONTEXT_DECIDED,
            {"version": pending.version, "approved": approve},
        )
        if not approve:
            await self._wake_leader(
                project_id,
                WakeSource.PATRON_DECISION,
                reason=wake_reason("context_change_requested"),
                detail=f"What the patron wrote: {note}",
            )
        return pending

    async def decide_plan(
        self,
        project_id: UUID,
        *,
        user_id: str,
        decision: plan_gate.PlanDecision,
        note: str | None = None,
    ) -> Plan:
        """Apply the patron's decision at the plan gate (FR-013, FR-014).

        The rule itself lives in `domain.services.plan_gate`; this method only carries out
        what it returns — persist, move the phase, close the inbox item, wake the Leader.
        """
        async with self._uow() as uow:
            project = await self._writable(uow, project_id)
            plan = await uow.plans.get_current(project_id)
            if plan is None:
                raise PlanningError("This project has no plan yet.")

            outcome = plan_gate.decide(
                plan.status,
                decision,
                # The patron surface is the only way in; the agent surface has no decision
                # route at all. This flag is the belt to that door's braces (FR-014).
                decider_is_leader=False,
                note=note,
            )

            now = utcnow()
            plan.status = outcome.plan_status
            plan.patron_note = outcome.note
            plan.decided_at = now
            plan.decided_by_user_id = user_id
            plan.updated_at = now
            await uow.plans.update(plan)

            previous_phase = project.status
            if outcome.next_phase is not None:
                context = await uow.project_contexts.get_approved(project_id)
                pending_context = await uow.project_contexts.get_pending(project_id)
                # Approving the plan implies the brief it was written against: a plan the
                # patron just accepted cannot be built on a context they never signed.
                if context is None and pending_context is not None:
                    pending_context.approval_status = ContextApprovalStatus.APPROVED
                    pending_context.approved_at = now
                    pending_context.approved_by_user_id = user_id
                    pending_context.updated_at = now
                    await uow.project_contexts.update(pending_context)
                    context = pending_context
                if not plan_gate.can_leave_planning(context is not None, plan.status):
                    raise PlanningError(
                        "The project cannot leave planning without an approved context."
                    )
                project_rules.assert_phase_transition(project.status, outcome.next_phase)
                project.status = outcome.next_phase
                project.updated_at = now
                await uow.projects.update(project)
            await uow.commit()
            workspace_id = project.workspace_id
            recipient = project.created_by_user_id

        await self._publish(
            project_id,
            EVENT_PLAN_DECIDED,
            {"version": plan.version, "decision": str(decision), "status": str(plan.status)},
        )
        if outcome.next_phase is not None:
            await self._publish(
                project_id,
                EVENT_PHASE_CHANGED,
                {
                    "before": str(previous_phase),
                    "after": str(outcome.next_phase),
                    "decided_by": user_id,
                },
            )
        # The patron does not tidy up after themselves: deciding closes what was waiting.
        if recipient and workspace_id:
            await self._resolve_plan_items(project_id, recipient)

        if outcome.wake_leader:
            await self._wake_leader(
                project_id,
                WakeSource.PATRON_DECISION,
                reason=wake_reason("plan_decided", decision=decision),
                detail=self._decision_message(outcome),
            )
        return plan

    # ── helpers ──────────────────────────────────────────────────────────────────
    async def _writable(self, uow: UnitOfWork, project_id: UUID) -> Project:
        """Load the project and refuse every write once it is closed (FR-005)."""
        project = await uow.projects.get(project_id)
        if project is None:
            raise LookupError("project not found")
        if project_rules.is_closed(project.status):
            raise ProjectClosed(
                "This project is closed — its history is read-only."
            )
        return project

    async def _resolve_plan_items(self, project_id: UUID, recipient: str) -> None:
        pending = await self._inbox.list_for(recipient, project_id=project_id)
        for item in pending:
            if item.kind is InboxItemKind.PLAN_APPROVAL:
                await self._inbox.resolve(item.id)

    def _decision_message(self, outcome: plan_gate.PlanOutcome) -> str:
        """The extra a plan decision owes the Leader (FR-044a): the verdict's consequence,
        and the patron's own note verbatim when they left one."""
        if outcome.note:
            return f"What the patron wrote: {outcome.note}\n\n{outcome.next_action}"
        return outcome.next_action

    async def _wake_leader(
        self, project_id: UUID, source: WakeSource, *, reason: WakeReason, detail: str = ""
    ) -> None:
        try:
            await self._leader_chat.notify(
                project_id=project_id, source=source, reason=reason, detail=detail
            )
        except LookupError:  # pragma: no cover - project vanished mid-flight
            return

    async def _publish(
        self, project_id: UUID, event: str, payload: dict[str, object]
    ) -> None:
        await self._bus.publish(project_topic(project_id), event, payload)


    # ── cổng thay đổi lớn (FR-075) ───────────────────────────────────────────────

    async def request_major_change(
        self,
        project_id: UUID,
        *,
        area: MajorChangeArea,
        summary: str,
        detail: str | None = None,
    ) -> InboxItem:
        """Park a change that widens the deal on the patron, before it takes effect.

        FR-074 already lets the Leader run the project: split work up, reorder it, swap
        who does it, change *how* the same outcome is reached. Five things are not that
        (FR-075) — scope, the objective or brief, cost, the deadline, and the acceptance
        criteria — because each of them changes what the patron agreed to, and a system
        that lets an agent quietly move any of them is a system nobody can hand a budget.

        The change is not applied here. This asks; the patron's answer is what applies it.
        A method that parked the question *and* made the change would make the gate a
        formality, which is the failure mode this requirement exists to prevent.
        """
        async with self._uow() as uow:
            project = await uow.projects.get(project_id)
            if project is None:
                raise LookupError("project not found")
            workspace_id = project.workspace_id
            recipient = (project.created_by_user_id or "").strip()
            if not recipient and workspace_id is not None:
                workspace = await uow.workspaces.get(workspace_id)
                recipient = (workspace.owner_user_id or "").strip() if workspace else ""

        if not recipient or workspace_id is None:
            raise PlanningError(
                "Dự án chưa có người chủ nào để hỏi, nên chưa duyệt được thay đổi lớn."
            )
        item = await self._inbox.place(
            workspace_id=workspace_id,
            recipient_user_id=recipient,
            kind=InboxItemKind.MAJOR_CHANGE_APPROVAL,
            title=f"Thay đổi lớn cần bạn duyệt — {MAJOR_CHANGE_LABELS[area]}",
            body=summary if detail is None else f"{summary}\n\n{detail}",
            project_id=project_id,
        )
        await self._publish(
            project_id,
            EVENT_MAJOR_CHANGE_REQUESTED,
            {"item_id": str(item.id), "area": str(area)},
        )
        return item

    # ── chuyển tiếp sạch khi tái hoạch định (FR-076) ─────────────────────────────

    async def settle_orphaned_tasks(
        self, project_id: UUID, *, reason: str | None = None
    ) -> list[UUID]:
        """After a replan, make sure no task is left pointing at nothing.

        A replan retires plan items. A task that pointed at one of them is now attached to
        a decision nobody made — it is neither in scope nor cancelled, and every gate that
        asks "is this in the approved plan?" gets a *no* while the board keeps showing the
        task as live work. That is the orphan FR-076 forbids.

        The resolution is deliberately the blunt one: send it back to *draft*. A draft is a
        proposal awaiting a decision, which is exactly what such a task has become, and it
        cannot wake anybody in the meantime. Cancelling instead would throw away work on
        the system's own initiative; leaving it alone is what produced the orphan.
        """
        settled: list[UUID] = []
        async with self._uow() as uow:
            plan = await uow.plans.get_current(project_id)
            live_items = {item.id for item in (plan.items if plan else [])}
            for task in await uow.tasks.list_by_project(project_id):
                if task.status in (TaskStatus.DONE, TaskStatus.CANCELLED):
                    continue  # finished work keeps its history, dead pointer and all
                if task.status is TaskStatus.DRAFT:
                    continue  # already a proposal awaiting a decision
                if task.plan_item_id is None or task.plan_item_id in live_items:
                    continue
                task.status = TaskStatus.DRAFT
                task.status_reason = reason or (
                    "hạng mục kế hoạch mà đầu việc này bám vào đã bị thay khi tái hoạch định"
                )
                task.drive = None
                task.drive_expires_at = None
                task.updated_at = utcnow()
                await uow.tasks.update(task)
                settled.append(task.id)
            await uow.commit()

        for task_id in settled:
            if self._task_logs is not None:
                await self._task_logs.record(
                    task_id,
                    TaskLogKind.STATUS_CHANGED,
                    actor_kind=ActorKind.SYSTEM,
                    after=str(TaskStatus.DRAFT),
                    reason=reason or "tái hoạch định: hạng mục cũ không còn",
                )
        return settled
