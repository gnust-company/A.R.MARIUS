"""Task use cases — create, propose, assign, gated transitions and their consequences.

Spec 001 Story 2 turns this from a thin CRUD layer into the place the five gates are
actually applied and the place a finished task sets off everything it should:

  - a Leader's proposal is auto-approved **only** inside the approved plan (FR-027) —
    this is what replaced the old project-wide "just do it" switch;
  - a worker cannot claim work (FR-072); it asks, and the Leader decides;
  - reaching *done* records the completion mark, frees whatever was only waiting on this
    task, and wakes the Leader to pass the word (FR-031);
  - every status change, assignment and criteria edit lands in the task's own log and on
    the project channel, so the board updates without asking (Constitution IV).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from armarius.application.ports.unit_of_work import UnitOfWork
from armarius.application.use_cases.types import UowFactory
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.domain.entities.checklist_item import ChecklistItem, assert_criteria_editable
from armarius.domain.entities.comment import AuthorKind, Comment
from armarius.domain.entities.inbox_item import InboxItemKind
from armarius.domain.entities.run import WakeSource
from armarius.domain.entities.task import (
    DEPENDENCY_GATED_STATUSES,
    Task,
    TaskDrive,
    TaskPriority,
    TaskStatus,
    assert_assignable,
    is_in_scope,
)
from armarius.domain.entities.task_dependency import TaskDependency, TaskDependencyError
from armarius.domain.entities.task_log import ActorKind, TaskLogKind
from armarius.domain.services import project_rules
from armarius.infrastructure.events.topic_bus import TopicEventBus, project_topic
from armarius.shared.clock import utcnow

if TYPE_CHECKING:  # pragma: no cover — typing only, keeps the import graph acyclic
    from armarius.application.use_cases.inbox import InboxService
    from armarius.application.use_cases.task_log import TaskLogService

EVENT_TASK_STATUS = "dau-viec.doi-trang-thai"
EVENT_TASK_UNLOCKED = "dau-viec.mo-khoa"


class LeaderNotifier(Protocol):
    """The one thing task use cases need from the Leader chat: wake it about a project."""

    async def notify(
        self, *, project_id: UUID, text: str, source: WakeSource, reason: str
    ) -> bool: ...


def _coerce_priority(value: str | TaskPriority | None) -> TaskPriority:
    """Map a patron/agent-supplied priority to the enum; unknown/empty → MEDIUM."""
    if value is None or value == "":
        return TaskPriority.MEDIUM
    try:
        return TaskPriority(str(value).lower())
    except ValueError:
        return TaskPriority.MEDIUM


class ProjectNotReadyForTasks(Exception):
    """Raised when a real task is created before the plan gate opened (spec 001 FR-003)."""


class AlreadyAssignedError(Exception):
    """Raised when a second worker is put on a task that already has one (FR-028)."""


class SelfClaimForbidden(Exception):
    """Raised if anything still tries to let a worker take work for itself (FR-072)."""


class TaskService:
    def __init__(
        self,
        uow_factory: UowFactory,
        wake_engine: WakeEngine,
        *,
        leader_chat: LeaderNotifier | None = None,
        task_logs: TaskLogService | None = None,
        control_bus: TopicEventBus | None = None,
        inbox: InboxService | None = None,
    ) -> None:
        self._uow = uow_factory
        self._wake = wake_engine
        # Optional collaborators: the composition root wires all four. Unit tests that
        # only care about one rule leave them out, and every use of them is guarded.
        self._leader_chat = leader_chat
        self._logs = task_logs
        self._bus = control_bus
        self._inbox = inbox

    async def create(
        self,
        *,
        project_id: UUID,
        title: str,
        description: str | None = None,
        status: TaskStatus = TaskStatus.BACKLOG,
        priority: str | TaskPriority | None = None,
        due_date: datetime | None = None,
        definition_of_done: str | None = None,
        created_by_user_id: str | None = None,
        created_by_marius_id: UUID | None = None,
        assigned_marius_id: UUID | None = None,
        plan_item_id: UUID | None = None,
    ) -> Task:
        """Create a task. Defaults to a ``backlog`` task; the Leader's proposals pass
        ``status=DRAFT`` + a proposed ``assigned_marius_id`` so the task waits for a
        decision before any worker is woken. The patron's manual add-task supplies the
        full definition — priority/due_date/assignee."""
        async with self._uow() as uow:
            project = await uow.projects.get(project_id)
            if project is None:
                raise LookupError("project not found")
            # FR-003: a real task exists only once the patron has approved the plan. A
            # draft is exempt — a proposal is precisely the thing you make before the
            # answer is in, and it cannot wake anyone.
            if status is not TaskStatus.DRAFT and not project_rules.accepts_real_tasks(
                project.status
            ):
                raise ProjectNotReadyForTasks(
                    "Kế hoạch chưa được duyệt — dự án chưa nhận đầu việc thật "
                    f"(giai đoạn hiện tại: '{project.status}')."
                )
            # Mint "{KEY}-{seq}" — the seq is allocated atomically (UPDATE … RETURNING) so
            # concurrent creates never share a number and the number is never reused.
            seq = await uow.projects.allocate_task_number(project_id)
            now = utcnow()
            task = Task(
                project_id=project_id,
                title=title,
                description=description,
                status=status,
                priority=_coerce_priority(priority),
                due_date=due_date,
                definition_of_done=definition_of_done,
                created_by_user_id=created_by_user_id,
                created_by_marius_id=created_by_marius_id,
                assigned_marius_id=assigned_marius_id,
                plan_item_id=await self._resolve_plan_item(uow, project_id, plan_item_id),
                identifier=f"{project.key}-{seq}",
                created_at=now,
                updated_at=now,
            )
            created = await uow.tasks.add(task)
            await uow.commit()
            return created

    async def propose(
        self,
        *,
        project_id: UUID,
        title: str,
        description: str | None = None,
        assigned_marius_id: UUID | None = None,
        created_by_marius_id: UUID | None = None,
        plan_item_id: UUID | None = None,
    ) -> Task:
        """The Leader proposing work (FR-027).

        Inside the approved plan the Leader does not ask permission — the patron already
        gave it, item by item, when they approved the plan. Outside it, the proposal is a
        request to widen scope: the task stays a draft and the decision goes to the
        patron's inbox rather than to a worker.
        """
        task = await self.create(
            project_id=project_id,
            title=title,
            description=description,
            status=TaskStatus.DRAFT,
            created_by_marius_id=created_by_marius_id,
            assigned_marius_id=assigned_marius_id,
            plan_item_id=plan_item_id,
        )
        if is_in_scope(task):
            return await self.approve_proposed(task.id, actor_kind=ActorKind.AGENT)
        await self._ask_patron_to_widen_scope(task)
        return task

    async def approve_proposed(
        self,
        task_id: UUID,
        *,
        user_id: str | None = None,
        actor_kind: ActorKind = ActorKind.USER,
    ) -> Task:
        """Release a draft onto the board: ``draft → todo``, then wake the assignee.

        Called two ways — automatically for work inside the approved plan, and by hand
        when the patron widens scope for a draft that fell outside it. Either way the
        description-gate applies: nothing reaches a worker without a brief.
        """
        assignee: UUID | None = None
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise LookupError("task not found")
            before = str(task.status)
            if task.assigned_marius_id is not None:
                assert_assignable(task)
            now = utcnow()
            deps_satisfied = await uow.dependencies.all_blockers_done(task_id)
            # DRAFT → TODO (raises on illegal transition or an unfinished blocked_by).
            task.transition_to(TaskStatus.TODO, now, deps_satisfied=deps_satisfied)
            task.drive = TaskDrive.WAKE_SCHEDULED if task.assigned_marius_id else None
            task.updated_at = now
            updated = await uow.tasks.update(task)
            await self._log(
                uow,
                task_id,
                TaskLogKind.STATUS_CHANGED,
                actor_kind=actor_kind,
                actor_user_id=user_id,
                before=before,
                after=str(TaskStatus.TODO),
            )
            await uow.commit()
            assignee = updated.assigned_marius_id
            project_id = updated.project_id

        await self._resolve_scope_question(task_id)
        await self._publish_status(project_id, task_id, TaskStatus.TODO)
        if assignee is not None:
            await self._wake.enqueue(
                marius_id=assignee,
                task_id=task_id,
                source=WakeSource.ASSIGNMENT,
                reason="you were assigned to this task",
            )
        return updated

    async def reject_proposed(self, task_id: UUID, *, reason: str | None = None) -> Task:
        """Turn down a proposal: ``draft → cancelled`` (no wake)."""
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise LookupError("task not found")
            now = utcnow()
            before = str(task.status)
            task.transition_to(
                TaskStatus.CANCELLED, now, reason=reason or "người chủ không duyệt đề xuất"
            )
            task.drive = None
            task.updated_at = now
            updated = await uow.tasks.update(task)
            await self._log(
                uow,
                task_id,
                TaskLogKind.STATUS_CHANGED,
                actor_kind=ActorKind.USER,
                before=before,
                after=str(TaskStatus.CANCELLED),
                reason=task.status_reason,
            )
            await uow.commit()
            project_id = updated.project_id

        await self._resolve_scope_question(task_id)
        await self._publish_status(project_id, task_id, TaskStatus.CANCELLED)
        return updated

    async def get(self, task_id: UUID) -> Task | None:
        async with self._uow() as uow:
            return await uow.tasks.get(task_id)

    async def get_in_workspace(self, task_id: UUID, workspace_id: UUID) -> Task:
        """The task, only if it lives in this workspace (agent ws-consistency, #15).

        Agent tokens are per-workspace; a cross-workspace task_id reads as "not
        found" so a token can't act on — or probe for — another workspace's tasks.
        """
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise LookupError("task not found")
            project = await uow.projects.get(task.project_id)
            if project is None or project.workspace_id != workspace_id:
                raise LookupError("task not found")
            return task

    async def list_by_project(
        self, project_id: UUID, *, statuses: list[str] | None = None
    ) -> Sequence[Task]:
        async with self._uow() as uow:
            return await uow.tasks.list_by_project(project_id, statuses=statuses)

    async def assign(
        self,
        task_id: UUID,
        marius_id: UUID,
        *,
        transfer_reason: str | None = None,
        user_id: str | None = None,
    ) -> Task:
        """Put one worker on a task and fire an assignment event-wake (§4.3 family 1).

        Two gates apply. The description-gate (FR-029): nobody is handed a title and left
        to guess. The one-assignee gate (FR-028): a task has exactly one owner at a time,
        so putting a second person on it is refused — say it is a **transfer** and give a
        reason, or split the task in two.
        """
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise LookupError("task not found")
            if await uow.mariuses.get(marius_id) is None:
                raise LookupError("marius not found")
            previous = task.assigned_marius_id
            if (
                previous is not None
                and previous != marius_id
                and not (transfer_reason or "").strip()
            ):
                raise AlreadyAssignedError(
                    "Đầu việc đã có người phụ trách. Một đầu việc chỉ có đúng một người: "
                    "chuyển giao kèm lý do, hoặc chẻ thành hai đầu việc."
                )
            assert_assignable(task)
            task.assigned_marius_id = marius_id
            # Convenience promotion backlog→todo, but honour the dependency-gate: a task
            # with an unfinished blocked_by stays in backlog rather than being forced up.
            if task.status == TaskStatus.BACKLOG and await uow.dependencies.all_blockers_done(
                task_id
            ):
                task.status = TaskStatus.TODO
            task.drive = TaskDrive.WAKE_SCHEDULED
            task.updated_at = utcnow()
            await uow.tasks.update(task)
            await self._log(
                uow,
                task_id,
                TaskLogKind.ASSIGNED,
                actor_kind=ActorKind.USER if user_id else ActorKind.SYSTEM,
                actor_user_id=user_id,
                before=str(previous) if previous else None,
                after=str(marius_id),
                reason=transfer_reason,
            )
            await uow.commit()

        await self._wake.enqueue(
            marius_id=marius_id,
            task_id=task_id,
            source=WakeSource.ASSIGNMENT,
            reason="you were assigned to this task",
        )
        return task

    # ── the worker's two ways of speaking about its own workload (FR-071, FR-072) ──
    #
    # Neither of them changes who owns the task. A worker asks; the Leader decides. That
    # is the whole point of removing self-claim: work is allocated by someone who can see
    # the whole board, not by whoever happened to wake up first.

    async def request_assignment(
        self, task_id: UUID, marius_id: UUID, *, note: str | None = None
    ) -> Task:
        """A worker asks to be put on a task (FR-072). Routed to the Leader, never applied."""
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise LookupError("task not found")
            await uow.comments.add(
                Comment(
                    task_id=task_id,
                    author_kind=AuthorKind.AGENT,
                    author_marius_id=marius_id,
                    body=note or "Tôi xin nhận đầu việc này.",
                )
            )
            await self._log(
                uow,
                task_id,
                TaskLogKind.ESCALATED,
                actor_kind=ActorKind.AGENT,
                actor_marius_id=marius_id,
                reason=note or "xin nhận đầu việc",
                detail={"kind": "assignment_request"},
            )
            await uow.commit()
            project_id = task.project_id

        await self._notify_leader(
            project_id,
            text=(
                f"Một thợ xin nhận đầu việc {task.identifier or task_id}. "
                "Vào xem rồi giao hoặc trả lời."
            ),
            reason="thợ xin nhận đầu việc",
            source=WakeSource.WORKER_HANDBACK,
        )
        return task

    async def hand_back(
        self, task_id: UUID, marius_id: UUID, *, reason: str
    ) -> Task:
        """A worker hands work back, or asks a clarifying question.

        Healthy behaviour, not a failure: the task keeps a live drive (a wake is booked
        for the Leader), so the watchdog does not count it as dropped (FR-056).
        """
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise LookupError("task not found")
            await uow.comments.add(
                Comment(
                    task_id=task_id,
                    author_kind=AuthorKind.AGENT,
                    author_marius_id=marius_id,
                    body=reason,
                )
            )
            task.drive = TaskDrive.WAKE_SCHEDULED
            task.updated_at = utcnow()
            updated = await uow.tasks.update(task)
            await self._log(
                uow,
                task_id,
                TaskLogKind.ESCALATED,
                actor_kind=ActorKind.AGENT,
                actor_marius_id=marius_id,
                reason=reason,
                detail={"kind": "handback"},
            )
            await uow.commit()
            project_id = updated.project_id

        await self._notify_leader(
            project_id,
            text=(
                f"Thợ trả lại đầu việc {updated.identifier or task_id}: {reason}"
            ),
            reason="thợ trả việc hoặc hỏi lại",
            source=WakeSource.WORKER_HANDBACK,
        )
        return updated

    async def transition(
        self,
        task_id: UUID,
        target: TaskStatus,
        *,
        reason: str | None = None,
        user_id: str | None = None,
        marius_id: UUID | None = None,
    ) -> Task:
        """Apply a gated status transition, then do what the new status implies.

        Reaching *done* is the one that carries weight (FR-031): the completion mark is
        written, every task that was only waiting on this one is let through, and the
        Leader is woken so somebody is actually told.
        """
        unlocked: list[Task] = []
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise LookupError("task not found")
            before = str(task.status)
            artifact_count = await uow.artifacts.count_by_task(task_id)
            deps_satisfied = True
            if target in DEPENDENCY_GATED_STATUSES:
                deps_satisfied = await uow.dependencies.all_blockers_done(task_id)
            now = utcnow()
            task.transition_to(
                target,
                now,
                has_artifact=artifact_count > 0,
                deps_satisfied=deps_satisfied,
                reason=reason,
            )
            task.drive = _drive_for(target)
            task.updated_at = now
            updated = await uow.tasks.update(task)
            await self._log(
                uow,
                task_id,
                TaskLogKind.STATUS_CHANGED,
                actor_kind=_actor_kind(user_id, marius_id),
                actor_user_id=user_id,
                actor_marius_id=marius_id,
                before=before,
                after=str(target),
                reason=reason,
            )
            if target is TaskStatus.DONE:
                unlocked = await self._unlock_dependents(uow, task_id)
            await uow.commit()
            project_id = updated.project_id

        await self._publish_status(project_id, task_id, target)
        for freed in unlocked:
            await self._publish(
                project_id,
                EVENT_TASK_UNLOCKED,
                {"task_id": str(freed.id), "unblocked_by": str(task_id)},
            )
        if target is TaskStatus.DONE:
            await self._notify_leader(
                project_id,
                text=(
                    f"Đầu việc {updated.identifier or task_id} đã xong"
                    + (
                        f"; {len(unlocked)} đầu việc được mở khoá."
                        if unlocked
                        else "."
                    )
                ),
                reason="một đầu việc vừa xong",
                source=WakeSource.TASK_DONE,
            )
        return updated

    async def reopen(
        self, task_id: UUID, *, reason: str, user_id: str | None = None
    ) -> Task:
        """Bring a closed task back — the only route out of *done*/*cancelled* (FR-022)."""
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise LookupError("task not found")
            before = str(task.status)
            now = utcnow()
            task.reopen(now, reason=reason)
            task.drive = _drive_for(task.status)
            updated = await uow.tasks.update(task)
            await self._log(
                uow,
                task_id,
                TaskLogKind.REOPENED,
                actor_kind=ActorKind.USER if user_id else ActorKind.SYSTEM,
                actor_user_id=user_id,
                before=before,
                after=str(task.status),
                reason=reason,
            )
            await uow.commit()
            project_id = updated.project_id

        await self._publish_status(project_id, task_id, updated.status)
        return updated

    async def set_next_action(self, task_id: UUID, next_action: str | None) -> Task:
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise LookupError("task not found")
            task.next_action = next_action
            task.updated_at = utcnow()
            updated = await uow.tasks.update(task)
            await uow.commit()
            return updated

    # ── acceptance criteria (FR-019) ──────────────────────────────────────────
    async def list_criteria(self, task_id: UUID) -> Sequence[ChecklistItem]:
        async with self._uow() as uow:
            if await uow.tasks.get(task_id) is None:
                raise LookupError("task not found")
            return await uow.criteria.list_by_task(task_id)

    async def set_criteria(
        self, task_id: UUID, texts: Sequence[str], *, user_id: str | None = None
    ) -> Sequence[ChecklistItem]:
        """Replace the yardstick. Only before the worker starts — after that it is a
        scope-level change and goes to the patron (FR-075), not into this method."""
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise LookupError("task not found")
            assert_criteria_editable(task)
            before = len(await uow.criteria.list_by_task(task_id))
            await uow.criteria.replace_for_task(
                task_id,
                [
                    ChecklistItem(task_id=task_id, text=text.strip(), order=index)
                    for index, text in enumerate(texts)
                    if text.strip()
                ],
            )
            await self._log(
                uow,
                task_id,
                TaskLogKind.CRITERIA_CHANGED,
                actor_kind=ActorKind.USER if user_id else ActorKind.SYSTEM,
                actor_user_id=user_id,
                before=str(before),
                after=str(len(texts)),
            )
            await uow.commit()
            return await uow.criteria.list_by_task(task_id)

    # ── Dependency edges (feed the dependency-gate, §1.3) ──────────────────────
    async def add_dependency(
        self, task_id: UUID, blocks_task_id: UUID
    ) -> TaskDependency:
        """Add a `blocked_by` edge: ``task_id`` waits on ``blocks_task_id``. Both tasks
        must exist in the same project. Rejects self-loops, duplicate pairs, and edges
        that would close a dependency cycle (all → ``TaskDependencyError`` → 422)."""
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            blocker = await uow.tasks.get(blocks_task_id)
            if task is None or blocker is None:
                raise LookupError("task not found")
            if task.project_id != blocker.project_id:
                raise TaskDependencyError("A dependency must stay within one project.")
            # Construct first: the entity rejects a self-loop in __post_init__.
            edge = TaskDependency(task_id=task_id, blocks_task_id=blocks_task_id)
            if await uow.dependencies.get(task_id, blocks_task_id) is not None:
                raise TaskDependencyError("This dependency already exists.")
            if await self._would_cycle(uow, task_id, blocks_task_id):
                raise TaskDependencyError("This dependency would create a cycle.")
            created = await uow.dependencies.add(edge)
            # Waiting on another task is a drive, not a void: the task is accounted for,
            # so the watchdog leaves it alone until the blocker lands.
            if blocker.status is not TaskStatus.DONE and task.status not in (
                TaskStatus.DONE,
                TaskStatus.CANCELLED,
            ):
                task.drive = TaskDrive.BLOCKED_BY_TASK
                await uow.tasks.update(task)
            await uow.commit()
            return created

    async def remove_dependency(self, task_id: UUID, blocks_task_id: UUID) -> None:
        """Remove a `blocked_by` edge (idempotent — a missing edge is a no-op)."""
        async with self._uow() as uow:
            await uow.dependencies.remove(task_id, blocks_task_id)
            await uow.commit()

    async def list_blockers(self, task_id: UUID) -> list[Task]:
        """The tasks ``task_id`` is blocked_by, as full tasks (for rendering)."""
        async with self._uow() as uow:
            blockers: list[Task] = []
            for edge in await uow.dependencies.list_blockers(task_id):
                if edge.blocks_task_id is None:
                    continue
                bt = await uow.tasks.get(edge.blocks_task_id)
                if bt is not None:
                    blockers.append(bt)
            return blockers

    async def list_project_dependencies(
        self, project_id: UUID
    ) -> Sequence[TaskDependency]:
        """All `blocked_by` edges in a project — the board reads these to flag which
        cards are blocked (a blocker not yet done)."""
        async with self._uow() as uow:
            return await uow.dependencies.list_by_project(project_id)

    # ── internals ─────────────────────────────────────────────────────────────
    async def _unlock_dependents(self, uow: UnitOfWork, task_id: UUID) -> list[Task]:
        """Free every task that was *only* waiting on this one (FR-031).

        A task still short of another blocker is left exactly where it is — being freed
        halfway is worse than not being freed, because it looks ready and is not.
        """
        freed: list[Task] = []
        for edge in await uow.dependencies.list_dependents(task_id):
            if edge.task_id is None:
                continue
            dependent = await uow.tasks.get(edge.task_id)
            if dependent is None or dependent.drive is not TaskDrive.BLOCKED_BY_TASK:
                continue
            if not await uow.dependencies.all_blockers_done(dependent.id):
                continue
            now = utcnow()
            before = str(dependent.status)
            if dependent.status in (TaskStatus.BACKLOG, TaskStatus.BLOCKED):
                dependent.transition_to(TaskStatus.TODO, now, deps_satisfied=True)
            dependent.drive = TaskDrive.WAKE_SCHEDULED if dependent.assigned_marius_id else None
            dependent.updated_at = now
            await uow.tasks.update(dependent)
            await self._log(
                uow,
                dependent.id,
                TaskLogKind.STATUS_CHANGED,
                before=before,
                after=str(dependent.status),
                reason="việc phụ thuộc đã xong",
                detail={"unblocked_by": str(task_id)},
            )
            freed.append(dependent)
        return freed

    async def _resolve_plan_item(
        self, uow: UnitOfWork, project_id: UUID, plan_item_id: UUID | None
    ) -> UUID | None:
        """Keep the pointer only if it really is an item of the **approved** plan.

        A dangling or made-up id silently becomes "out of scope" rather than an error:
        the answer to "is this in the plan?" is no, and no is a valid answer.
        """
        if plan_item_id is None:
            return None
        plan = await uow.plans.get_approved(project_id)
        if plan is None:
            return None
        return plan_item_id if any(i.id == plan_item_id for i in plan.items) else None

    async def _ask_patron_to_widen_scope(self, task: Task) -> None:
        """Park an out-of-scope proposal on the patron (FR-027 → FR-075)."""
        if self._inbox is None or task.project_id is None:
            return
        async with self._uow() as uow:
            project = await uow.projects.get(task.project_id)
        if project is None or project.workspace_id is None:
            return
        recipient = project.created_by_user_id
        if not recipient:
            return
        await self._inbox.place(
            workspace_id=project.workspace_id,
            recipient_user_id=recipient,
            kind=InboxItemKind.MAJOR_CHANGE_APPROVAL,
            title=task.title,
            body=(
                "Trưởng dự án đề xuất một đầu việc nằm ngoài các hạng mục kế hoạch đã "
                "duyệt. Duyệt là nới phạm vi dự án."
            ),
            project_id=task.project_id,
            task_id=task.id,
        )

    async def _resolve_scope_question(self, task_id: UUID) -> None:
        """Close the waiting item once the draft has been decided, either way."""
        if self._inbox is not None:
            await self._inbox.resolve_pending_for_task(task_id)

    async def _notify_leader(
        self, project_id: UUID | None, *, text: str, reason: str, source: WakeSource
    ) -> None:
        if self._leader_chat is None or project_id is None:
            return
        await self._leader_chat.notify(
            project_id=project_id, text=text, source=source, reason=reason
        )

    async def _publish_status(
        self, project_id: UUID | None, task_id: UUID, status: TaskStatus
    ) -> None:
        await self._publish(
            project_id,
            EVENT_TASK_STATUS,
            {"task_id": str(task_id), "status": str(status)},
        )

    async def _publish(
        self, project_id: UUID | None, event: str, data: dict[str, object]
    ) -> None:
        """Identifiers and labels only — never task content (contracts/su-kien-day §4)."""
        if self._bus is None or project_id is None:
            return
        await self._bus.publish(project_topic(project_id), event, data)

    async def _log(
        self,
        uow: UnitOfWork,
        task_id: UUID,
        kind: TaskLogKind,
        *,
        actor_kind: ActorKind = ActorKind.SYSTEM,
        actor_user_id: str | None = None,
        actor_marius_id: UUID | None = None,
        before: str | None = None,
        after: str | None = None,
        reason: str | None = None,
        detail: dict[str, object] | None = None,
    ) -> None:
        """Append to the task's history inside the caller's transaction, so a change that
        commits always has its log line with it."""
        if self._logs is None:
            return
        await self._logs.record_in(
            uow,
            task_id,
            kind,
            actor_kind=actor_kind,
            actor_user_id=actor_user_id,
            actor_marius_id=actor_marius_id,
            before=before,
            after=after,
            reason=reason,
            detail=detail,
        )

    async def _would_cycle(
        self, uow: UnitOfWork, task_id: UUID, blocks_task_id: UUID
    ) -> bool:
        """Would adding "task_id blocked_by blocks_task_id" close a cycle? True when
        ``task_id`` is already reachable from ``blocks_task_id`` via existing edges."""
        seen: set[UUID] = set()
        frontier: list[UUID] = [blocks_task_id]
        while frontier:
            current = frontier.pop()
            if current == task_id:
                return True
            if current in seen:
                continue
            seen.add(current)
            for edge in await uow.dependencies.list_blockers(current):
                if edge.blocks_task_id is not None:
                    frontier.append(edge.blocks_task_id)
        return False


def _actor_kind(user_id: str | None, marius_id: UUID | None) -> ActorKind:
    if user_id:
        return ActorKind.USER
    if marius_id:
        return ActorKind.AGENT
    return ActorKind.SYSTEM


def _drive_for(status: TaskStatus) -> TaskDrive | None:
    """The drive a status implies on its own. Story 6 refines this with live run state;
    what matters here is that a task never silently ends up with no drive at all."""
    if status in (TaskStatus.DONE, TaskStatus.CANCELLED):
        return None
    if status is TaskStatus.BLOCKED:
        return TaskDrive.BLOCKED_BY_TASK
    if status is TaskStatus.DRAFT:
        return TaskDrive.WAITING_PATRON
    if status is TaskStatus.IN_PROGRESS:
        return TaskDrive.RUN_ACTIVE
    return TaskDrive.WAKE_SCHEDULED
