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
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from armarius.application.ports.unit_of_work import UnitOfWork
from armarius.application.use_cases.review_reset import retire_signatures_on_move
from armarius.application.use_cases.threads import announce_comment
from armarius.application.use_cases.types import UowFactory
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.domain.entities.checklist_item import (
    AcceptanceResult,
    ChecklistItem,
    ChecklistTally,
    assert_criteria_editable,
    assert_criteria_ratable,
    criteria_not_passed,
)
from armarius.domain.entities.comment import AuthorKind, Comment
from armarius.domain.entities.inbox_item import InboxItemKind
from armarius.domain.entities.run import WakeSource
from armarius.domain.entities.task import (
    CRITERIA_REQUIRED_STATUSES,
    DEPENDENCY_GATED_STATUSES,
    SIGNATURE_REQUIRED_STATUSES,
    TERMINAL_STATUSES,
    Task,
    TaskPriority,
    TaskStatus,
    assert_assignable,
    is_in_scope,
)
from armarius.domain.entities.task_dependency import TaskDependency, TaskDependencyError
from armarius.domain.entities.task_log import ActorKind, TaskLogKind
from armarius.domain.services import project_rules
from armarius.domain.services.approval_rules import (
    current_signatures,
    is_closable,
    missing_signatures,
)
from armarius.domain.services.project_rules import ProjectClosed
from armarius.domain.services.push_reason_rules import (
    QueueCandidate,
    keeps_running,
    provisional_drive,
    queue_order,
)
from armarius.domain.services.wake_reason import WakeReason
from armarius.domain.services.wake_reason import reason as wake_reason
from armarius.infrastructure.events.topic_bus import TopicEventBus, project_topic
from armarius.shared.clock import as_utc, utcnow
from armarius.shared.errors import CodedError, NotFound

if TYPE_CHECKING:  # pragma: no cover — typing only, keeps the import graph acyclic
    from armarius.application.use_cases.inbox import InboxService
    from armarius.application.use_cases.push_reason import PushReasonService
    from armarius.application.use_cases.task_log import TaskLogService

EVENT_TASK_STATUS = "task.status_changed"
EVENT_TASK_UNLOCKED = "task.unblocked"
EVENT_TASK_CREATED = "task.created"
# The board card draws more than a status: a criteria tally and a blocker count sit on it
# too, and both used to change in silence (T177). FR-080a is about everything the screen
# shows, not about the status field.
EVENT_TASK_CHECKLIST = "task.checklist_changed"
EVENT_TASK_DEPENDENCIES = "task.dependencies_changed"
# The patron rewrote the job itself — title, priority or deadline are all drawn on the
# card, so the board owes the same signal it owes a move (FR-070a, FR-080a).
EVENT_TASK_UPDATED = "task.updated"


@dataclass(frozen=True)
class TaskCardCounts:
    """What a board card needs to know about a task beyond the task row itself."""

    task_id: UUID
    comments: int = 0
    artifacts: int = 0
    criteria_total: int = 0
    criteria_passed: int = 0


class LeaderNotifier(Protocol):
    """The one thing task use cases need from the Leader chat: wake it about a project.

    A cause, never a sentence. The packet the Leader reads is assembled at the door out of
    its own four-part core plus `detail`, the extra this call type owes (FR-044, FR-044a) —
    callers that write the whole body themselves are how eight fixed parts got forced on a
    role that had no use for five of them.
    """

    async def notify(
        self,
        *,
        project_id: UUID,
        source: WakeSource,
        reason: WakeReason,
        detail: str = "",
    ) -> bool: ...


def _coerce_priority(value: str | TaskPriority | None) -> TaskPriority:
    """Map a patron/agent-supplied priority to the enum; unknown/empty → MEDIUM."""
    if value is None or value == "":
        return TaskPriority.MEDIUM
    try:
        return TaskPriority(str(value).lower())
    except ValueError:
        return TaskPriority.MEDIUM


class _Unset:
    """"This field was not in the request" — distinct from "set this field to nothing".

    An edit needs both (FR-070a). The motivating case is the one the spec names: a
    deadline typed in by mistake has to be *removable*, and with the house "None means
    unchanged" idiom it never can be — the patron would be back to deleting the task and
    recreating it, losing its comments, artifacts and history in the process.
    """

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "UNSET"


UNSET = _Unset()


#: The fields whose change makes the worker's current understanding of the job wrong
#: (FR-070a → FR-046). A title reworded or a priority bumped does not change what has to
#: be built, and waking somebody mid-turn to tell them nothing actionable is how an agent
#: learns that wake packets are not worth reading.
_SUBSTANTIVE: frozenset[str] = frozenset({"description", "due_date", "definition_of_done"})

#: Statuses in which somebody is still going to act on this task. A finished task is not
#: dragged back to life by an edit — reopening is its own deliberate move, with a reason.
_STILL_IN_PLAY: frozenset[TaskStatus] = frozenset(
    {TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.IN_REVIEW, TaskStatus.BLOCKED}
)


def _worker_to_warn(task: Task, changed: Sequence[str]) -> UUID | None:
    """Who, if anyone, needs to be told the job just moved under them."""
    if task.assigned_marius_id is None or task.status not in _STILL_IN_PLAY:
        return None
    return task.assigned_marius_id if _SUBSTANTIVE & set(changed) else None


class ProjectNotReadyForTasks(CodedError):
    """Raised when a real task is created before the plan gate opened (spec 001 FR-003)."""


class TitleRequiredError(CodedError):
    """Raised when an edit would leave a task with no title (FR-070a)."""


class AlreadyAssignedError(CodedError):
    """Raised when a second worker is put on a task that already has one (FR-028)."""


class SelfClaimForbidden(Exception):
    """Raised if anything still tries to let a worker take work for itself (FR-072)."""


@dataclass(frozen=True)
class AssignEffects:
    """What an assignment still owes the outside world once its writes have landed."""

    task: Task
    task_id: UUID
    marius_id: UUID
    project_id: UUID | None
    promoted_from: str | None


@dataclass(frozen=True)
class TransitionEffects:
    """What a status change still owes the outside world once its writes have landed."""

    task: Task
    task_id: UUID
    project_id: UUID | None
    target: TaskStatus
    unlocked: tuple[Task, ...]


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
        push_reasons: PushReasonService | None = None,
    ) -> None:
        self._uow = uow_factory
        self._wake = wake_engine
        # Optional collaborators: the composition root wires all four. Unit tests that
        # only care about one rule leave them out, and every use of them is guarded.
        self._leader_chat = leader_chat
        self._logs = task_logs
        self._bus = control_bus
        self._inbox = inbox
        # The authoritative drive writer (FR-056). Every status change here leaves a
        # *provisional* drive inside its own transaction, then asks this to settle it
        # once the wakes and inbox items that change the answer have actually been
        # created — see `_settle_drive`.
        self._push_reasons = push_reasons

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
                raise NotFound("project_not_found")
            # FR-003: a real task exists only once the patron has approved the plan. A
            # draft is exempt — a proposal is precisely the thing you make before the
            # answer is in, and it cannot wake anyone.
            if status is not TaskStatus.DRAFT and not project_rules.accepts_real_tasks(
                project.status
            ):
                raise ProjectNotReadyForTasks(
                    "project_not_ready_for_tasks", status=project.status
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

        # A card appearing is a change to what the board draws, so it owes the board a
        # signal exactly like a card moving does (FR-080a). Without this the board sat
        # still until someone reloaded the page — and a board that never moves reads the
        # same as a project where nothing is happening.
        #
        # Fired for drafts too. A draft is not drawn on the board, so the re-read finds
        # nothing new and costs one query; the alternative is a status condition here that
        # has to stay right every time the set of drawn statuses changes. Publishing is
        # never wrong; staying quiet is what is wrong.
        await self._publish(
            created.project_id,
            EVENT_TASK_CREATED,
            {"task_id": str(created.id), "status": str(created.status)},
        )
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
                raise NotFound("task_not_found")
            # FR-003 again, at the other door that turns a proposal into work. Releasing a
            # draft *is* creating a real task — the exemption `create` grants a draft ends
            # exactly here, because this is the step that wakes somebody.
            await self._assert_phase_accepts_work(uow, task)
            before = str(task.status)
            if task.assigned_marius_id is not None:
                assert_assignable(task)
            now = utcnow()
            deps_satisfied = await uow.dependencies.all_blockers_done(task_id)
            # DRAFT → TODO (raises on illegal transition or an unfinished blocked_by).
            task.transition_to(TaskStatus.TODO, now, deps_satisfied=deps_satisfied)
            _mark_provisional(task, now)
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
                reason=wake_reason("assigned"),
            )
        await self._settle_drive(task_id)
        return updated

    async def reject_proposed(self, task_id: UUID, *, reason: str | None = None) -> Task:
        """Turn down a proposal: ``draft → cancelled`` (no wake)."""
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise NotFound("task_not_found")
            now = utcnow()
            before = str(task.status)
            task.transition_to(
                TaskStatus.CANCELLED, now, reason=reason or "người chủ không duyệt đề xuất"
            )
            _mark_provisional(task, now)
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
        await self._settle_drive(task_id)
        return updated

    async def _settle_drive(self, task_id: UUID) -> None:
        """Replace the provisional drive with the verified one (FR-056, QĐ-4).

        Called **after** the transaction commits and after any wake has been enqueued,
        because those are the rows that decide the answer. Doing it inside the status
        transaction would ask the question a few lines too early and get a truthful
        'nothing is moving this' about a task whose wake was one statement away.
        """
        if self._push_reasons is not None:
            await self._push_reasons.refresh(task_id)

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
                raise NotFound("task_not_found")
            project = await uow.projects.get(task.project_id)
            if project is None or project.workspace_id != workspace_id:
                raise NotFound("task_not_found")
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
        """Put one worker on a task and fire an assignment event-wake (§4.3 family 1)."""
        async with self._uow() as uow:
            effects = await self.assign_within(
                uow,
                task_id,
                marius_id,
                transfer_reason=transfer_reason,
                user_id=user_id,
            )
            await uow.commit()
        await self.after_assign(effects)
        return effects.task

    async def edit(
        self,
        task_id: UUID,
        *,
        title: str | None | _Unset = UNSET,
        description: str | None | _Unset = UNSET,
        priority: str | TaskPriority | _Unset = UNSET,
        due_date: datetime | None | _Unset = UNSET,
        definition_of_done: str | None | _Unset = UNSET,
        user_id: str | None = None,
    ) -> Task:
        """The patron rewriting a task after it exists (FR-070, FR-070a).

        Which gate applies is decided by **who is calling**, not by which field is touched
        (FR-070a). This is the patron's door, and the patron's edits take effect at once —
        that is the whole point of FR-070. The Leader touching one of the five big things
        goes through its own change-request route instead, and the assignee has no edit
        door at all: it adds progress notes in the thread and leaves the requirement it
        was handed alone (FR-018).

        Only what the caller actually sent is touched, and passing an empty value clears
        the field rather than being read as "no change" — see `_Unset`.

        Not gated on the project phase, unlike creating or assigning. Rewording a draft
        while the plan is still being argued about is ordinary work and wakes nobody. A
        *closed* project is the exception: it is history, and history is read-only
        (FR-005).
        """
        changed: list[str] = []
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise NotFound("task_not_found")
            await self._assert_project_open(uow, task)

            if not isinstance(title, _Unset) and title != task.title:
                # The one field with no empty state: a task nobody can name is a task
                # nobody can find. Clearing it is refused rather than quietly ignored.
                if not (title or "").strip():
                    raise TitleRequiredError("task_needs_title")
                task.title = str(title)
                changed.append("title")
            if not isinstance(description, _Unset) and description != task.description:
                # Through the entity, so the FR-018 lock stays the single place that
                # decides who may rewrite a requirement.
                task.set_description(description, by_worker=False)
                changed.append("description")
            if not isinstance(priority, _Unset):
                resolved = _coerce_priority(priority)
                if resolved is not task.priority:
                    task.priority = resolved
                    changed.append("priority")
            if not isinstance(due_date, _Unset) and due_date != task.due_date:
                task.due_date = due_date
                changed.append("due_date")
            if (
                not isinstance(definition_of_done, _Unset)
                and definition_of_done != task.definition_of_done
            ):
                task.definition_of_done = definition_of_done
                changed.append("definition_of_done")

            if not changed:
                # An edit that edits nothing is not an event. Recording it would dilute
                # the one log the patron reads to find out when the job changed.
                return task

            task.updated_at = utcnow()
            updated = await uow.tasks.update(task)
            await self._log(
                uow,
                task_id,
                TaskLogKind.EDITED,
                actor_kind=ActorKind.USER,
                actor_user_id=user_id,
                # Field names, not values: the log is a trail, not a copy of every draft
                # a description ever passed through.
                detail={"fields": changed},
            )
            await uow.commit()
            project_id = updated.project_id
            tell = _worker_to_warn(updated, changed)

        # The board draws the title, the priority and the deadline, so an edit changes
        # what is on screen exactly as a move does (FR-080a).
        await self._publish(
            project_id,
            EVENT_TASK_UPDATED,
            {"task_id": str(task_id), "fields": changed},
        )
        if tell is not None:
            await self._wake.enqueue(
                marius_id=tell,
                task_id=task_id,
                source=WakeSource.REQUIREMENT_CHANGED,
                reason=wake_reason(
                    "requirement_changed", fields=", ".join(_SUBSTANTIVE & set(changed))
                ),
            )
            await self._settle_drive(task_id)
        return updated

    async def _assert_project_open(self, uow: UnitOfWork, task: Task) -> None:
        """FR-005 — a closed project is readable, never writable."""
        if task.project_id is None:  # pragma: no cover - defensive
            return
        project = await uow.projects.get(task.project_id)
        if project is not None and project_rules.is_closed(project.status):
            raise ProjectClosed("project_closed")

    async def _assert_phase_accepts_work(self, uow: UnitOfWork, task: Task) -> None:
        """FR-003 — a worker is only put on a task once the patron has approved the plan.

        Read from the project rather than trusted from the caller: the phase can move
        between the screen drawing a button and the request arriving, and the caller here
        is sometimes an agent that never saw the screen at all.
        """
        if task.project_id is None:  # pragma: no cover - defensive
            return
        project = await uow.projects.get(task.project_id)
        if project is None or project_rules.accepts_real_tasks(project.status):
            return
        raise ProjectNotReadyForTasks("project_not_ready_for_tasks", status=project.status)

    async def assign_within(
        self,
        uow: UnitOfWork,
        task_id: UUID,
        marius_id: UUID,
        *,
        transfer_reason: str | None = None,
        user_id: str | None = None,
    ) -> AssignEffects:
        """The write half of `assign`. **The caller owns the transaction.**

        Split out so an entry point that has to change two things at once — the patron
        answering an escalation changes the task *and* closes the letter — can put both
        writes behind a single commit. Two commits mean a moment where one landed and the
        other did not, and a retry from there runs the assignment a second time, waking
        the new owner twice for one incident.

        Three gates apply. The phase-gate (FR-003): the project has to be *operating* or
        *maintaining*. The description-gate (FR-029): nobody is handed a title and left
        to guess. The one-assignee gate (FR-028): a task has exactly one owner at a time,
        so putting a second person on it is refused — say it is a **transfer** and give a
        reason, or split the task in two.

        Note the phase-gate has no draft exemption, unlike the one on `create`. That one
        exists because a draft wakes nobody; an assignment always does, so there is no
        such thing as assigning "provisionally".
        """
        task = await uow.tasks.get(task_id)
        if task is None:
            raise NotFound("task_not_found")
        await self._assert_phase_accepts_work(uow, task)
        if await uow.mariuses.get(marius_id) is None:
            raise NotFound("agent_not_found")
        previous = task.assigned_marius_id
        if (
            previous is not None
            and previous != marius_id
            and not (transfer_reason or "").strip()
        ):
            raise AlreadyAssignedError("task_already_assigned")
        assert_assignable(task)
        now = utcnow()
        task.assigned_marius_id = marius_id
        # Convenience promotion backlog→todo, but honour the dependency-gate: a task
        # with an unfinished blocked_by stays in backlog rather than being forced up.
        # It goes through the transition table like every other move, and leaves its
        # own log line — a status that changed without a line in the log is a hole in
        # the audit trail (FR-079), even when the change was a side effect.
        promoted_from: str | None = None
        if task.status == TaskStatus.BACKLOG and await uow.dependencies.all_blockers_done(
            task_id
        ):
            promoted_from = str(task.status)
            task.transition_to(TaskStatus.TODO, now, deps_satisfied=True)
        _mark_provisional(task, now)
        task.updated_at = now
        await uow.tasks.update(task)
        actor_kind = ActorKind.USER if user_id else ActorKind.SYSTEM
        await self._log(
            uow,
            task_id,
            TaskLogKind.ASSIGNED,
            actor_kind=actor_kind,
            actor_user_id=user_id,
            before=str(previous) if previous else None,
            after=str(marius_id),
            reason=transfer_reason,
        )
        if promoted_from is not None:
            await self._log(
                uow,
                task_id,
                TaskLogKind.STATUS_CHANGED,
                actor_kind=actor_kind,
                actor_user_id=user_id,
                before=promoted_from,
                after=str(TaskStatus.TODO),
                reason="giao người phụ trách",
            )
        return AssignEffects(
            task=task,
            task_id=task_id,
            marius_id=marius_id,
            project_id=task.project_id,
            promoted_from=promoted_from,
        )

    async def after_assign(self, effects: AssignEffects) -> None:
        """Everything an assignment sets off once its writes have landed.

        Deliberately outside the transaction: waking an agent and publishing to the board
        are the outside world, and doing them while the write could still roll back would
        announce something that never happened.
        """
        if effects.promoted_from is not None:
            await self._publish_status(effects.project_id, effects.task_id, TaskStatus.TODO)
        await self._wake.enqueue(
            marius_id=effects.marius_id,
            task_id=effects.task_id,
            source=WakeSource.ASSIGNMENT,
            reason=wake_reason("assigned"),
        )
        await self._settle_drive(effects.task_id)

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
                raise NotFound("task_not_found")
            await uow.comments.add(
                Comment(
                    task_id=task_id,
                    author_kind=AuthorKind.AGENT,
                    author_marius_id=marius_id,
                    # The fallback is English: with no note of its own the server is
                    # writing in the agent's voice, and this comment is replayed into
                    # the Leader's wake packet under "## New messages since you last
                    # worked" (Constitution VII). A worker's own `note` is passed
                    # through untouched — that is the agent's sentence, not ours.
                    body=note or "I would like to take this task.",
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

        await announce_comment(self._bus, project_id, task_id)
        await self._notify_leader(
            project_id,
            reason=wake_reason(
                "worker_asked_for_task", task=task.identifier or task_id
            ),
            source=WakeSource.WORKER_HANDBACK,
            # The worker's own words, passed through untouched — a person (or an agent
            # speaking for itself) wrote them, so they are not the system's to translate.
            detail=(f"What the worker said: {note.strip()}" if note and note.strip() else ""),
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
                raise NotFound("task_not_found")
            await uow.comments.add(
                Comment(
                    task_id=task_id,
                    author_kind=AuthorKind.AGENT,
                    author_marius_id=marius_id,
                    body=reason,
                )
            )
            now = utcnow()
            _mark_provisional(task, now)
            task.updated_at = now
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

        await announce_comment(self._bus, project_id, task_id)
        await self._notify_leader(
            project_id,
            reason=wake_reason("worker_handback", task=updated.identifier or task_id),
            source=WakeSource.WORKER_HANDBACK,
            detail=(f"What the worker said: {reason.strip()}" if reason.strip() else ""),
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
        """Apply a gated status transition, then do what the new status implies."""
        async with self._uow() as uow:
            effects = await self.transition_within(
                uow, task_id, target, reason=reason, user_id=user_id, marius_id=marius_id
            )
            await uow.commit()
        await self.after_transition(effects)
        return effects.task

    async def transition_within(
        self,
        uow: UnitOfWork,
        task_id: UUID,
        target: TaskStatus,
        *,
        reason: str | None = None,
        user_id: str | None = None,
        marius_id: UUID | None = None,
    ) -> TransitionEffects:
        """The write half of `transition`. **The caller owns the transaction.**

        Reaching *done* is the one that carries weight (FR-031): the completion mark is
        written, every task that was only waiting on this one is let through, and the
        Leader is woken so somebody is actually told.

        Split out for the same reason as `assign_within` — see the note there.
        """
        unlocked: list[Task] = []
        task = await uow.tasks.get(task_id)
        if task is None:
            raise NotFound("task_not_found")
        before = str(task.status)
        artifact_count = await uow.artifacts.count_by_task(task_id)
        deps_satisfied = True
        unmet: tuple[str, ...] = ()
        if target in DEPENDENCY_GATED_STATUSES:
            # Name what is missing, don't just say something is (FR-025).
            open_blockers = await uow.dependencies.list_unfinished_blockers(task_id)
            deps_satisfied = not open_blockers
            unmet = tuple(b.identifier or str(b.id) for b in open_blockers)
        signed = True
        missing: tuple[str, ...] = ()
        if target in SIGNATURE_REQUIRED_STATUSES:
            # The two-signature gate (FR-033). Reading it here is what makes
            # "move it straight to done" stop working from every entry point at once
            # — the board, the agent surface and the middle layer all land here.
            history = await uow.approvals.list_for_task(task_id)
            current = current_signatures(history)
            signed = is_closable(current)
            missing = tuple(str(k) for k in missing_signatures(current))
        criteria_met = True
        unmet_criteria: tuple[str, ...] = ()
        if target in CRITERIA_REQUIRED_STATUSES:
            # The yardstick gate (FR-019). Read here for the same reason the signatures
            # are: this is the one place every route into *done* passes through, so a
            # route nobody remembered still meets it. A task with no criteria passes
            # vacuously — writing the list at all is a different gate, and inventing one
            # here would refuse every task in the system that predates the criteria.
            unmet_criteria = criteria_not_passed(await uow.criteria.list_by_task(task_id))
            criteria_met = not unmet_criteria
        now = utcnow()
        task.transition_to(
            target,
            now,
            has_artifact=artifact_count > 0,
            deps_satisfied=deps_satisfied,
            reason=reason,
            unmet_blockers=unmet,
            signatures_complete=signed,
            missing_signatures=missing,
            criteria_met=criteria_met,
            unmet_criteria=unmet_criteria,
        )
        _mark_provisional(task, now)
        task.updated_at = now
        # Every route out of review lands here, including the ones nobody thought to
        # enumerate — which is why the question is asked of the move rather than of
        # the caller (FR-033).
        await retire_signatures_on_move(uow, task_id, target)
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
        return TransitionEffects(
            task=updated,
            task_id=task_id,
            project_id=updated.project_id,
            target=target,
            unlocked=tuple(unlocked),
        )

    async def after_transition(self, effects: TransitionEffects) -> None:
        """Everything a status change sets off once its writes have landed."""
        task_id = effects.task_id
        project_id = effects.project_id
        target = effects.target
        updated = effects.task
        unlocked = list(effects.unlocked)
        await self._publish_status(project_id, task_id, target)
        for freed in unlocked:
            await self._publish(
                project_id,
                EVENT_TASK_UNLOCKED,
                {"task_id": str(freed.id), "unblocked_by": str(task_id)},
            )
        if target is TaskStatus.IN_REVIEW:
            # FR-047: handing work in is a cause to wake the **Leader**, who owes the
            # judgement. FR-049 is the other half — the worker is not woken for its own
            # submission; it has nothing left to do until somebody answers.
            await self._notify_leader(
                project_id,
                reason=wake_reason("task_in_review", task=updated.identifier or task_id),
                source=WakeSource.TASK_IN_REVIEW,
                detail="Judge it against the task's acceptance criteria.",
            )
        if target is TaskStatus.DONE:
            await self._notify_leader(
                project_id,
                reason=wake_reason("task_done", task=updated.identifier or task_id),
                source=WakeSource.TASK_DONE,
                detail=(
                    f"{len(unlocked)} task(s) came unblocked with it."
                    if unlocked
                    else ""
                ),
            )
            if not await self._project_has_open_tasks(project_id):
                # FR-043: the batch is closed — the Leader writes the wrap-up, then the
                # patron decides between closing the project, moving it to maintenance and
                # opening a new batch. There is no project-level acceptance gate (FR-042):
                # the work was already signed off one task at a time.
                await self._notify_leader(
                    project_id,
                    reason=wake_reason("batch_done"),
                    source=WakeSource.TASK_DONE,
                    detail=(
                        "Write the batch wrap-up and send it to the patron with the three "
                        "choices open to them: close the project, move it to maintenance, "
                        "or open a new batch."
                    ),
                )
        # Last, on purpose: the drive depends on the wakes and inbox items the block
        # above just created, and asking before them would settle on a stale answer.
        await self._settle_drive(task_id)
        for freed in unlocked:
            await self._wake_the_freed(freed, cleared_by=updated)
            # An unblocked task changed drive too — the thing it was waiting on is gone.
            await self._settle_drive(freed.id)

    async def ready_queue(self, project_id: UUID) -> list[Task]:
        """What to hand out next on this project, in order (FR-066, FR-067).

        Two rules, both of them about fairness rather than throughput.

        The **order** is priority, then deadline, then age, with the wait itself promoting a
        task (`queue_order`). Without that promotion a *low* task on a busy project is never
        reached: there is always another *high* one, and "we will get to it" becomes
        something the board says forever.

        The **membership** excludes only what genuinely stands behind a pending patron
        decision — the parked tasks and their downstream chain, nothing else (FR-066). The
        project stops at the question, not across the whole board, so a Friday afternoon
        that goes unanswered does not cost the following week.

        Ready means *todo* with every blocker done and nobody on it yet. A task already
        being worked on is not queued for a worker; it has one.
        """
        async with self._uow() as uow:
            tasks = list(await uow.tasks.list_by_project(project_id))
            edges = [
                (e.task_id, e.blocks_task_id)
                for e in await uow.dependencies.list_by_project(project_id)
                if e.task_id is not None and e.blocks_task_id is not None
            ]
            parked = [
                t.id
                for t in tasks
                if t.id in {
                    i.task_id
                    for i in await uow.inbox.list_pending()
                    if i.task_id is not None
                }
            ]
            unfinished = {
                t.id for t in tasks if t.status not in TERMINAL_STATUSES
            }

        ready = [
            t
            for t in tasks
            if t.status is TaskStatus.TODO
            and t.assigned_marius_id is None
            and not any(
                blocker in unfinished
                for task_id, blocker in edges
                if task_id == t.id
            )
        ]
        running = keeps_running(
            [t.id for t in ready], waiting_on=parked, edges=edges
        )
        by_id = {t.id: t for t in ready}
        ordered = queue_order(
            [
                QueueCandidate(
                    task_id=t.id,
                    identifier=t.identifier or str(t.id),
                    priority=str(t.priority),
                    due_date=as_utc(t.due_date),
                    created_at=as_utc(t.created_at),
                )
                for t in (by_id[tid] for tid in running)
            ],
            now=utcnow(),
        )
        return [by_id[c.task_id] for c in ordered]

    async def _project_has_open_tasks(self, project_id: UUID | None) -> bool:
        if project_id is None:
            return True
        async with self._uow() as uow:
            tasks = await uow.tasks.list_by_project(project_id)
        return any(t.status not in TERMINAL_STATUSES for t in tasks)

    async def reopen(
        self, task_id: UUID, *, reason: str, user_id: str | None = None
    ) -> Task:
        """Bring a closed task back — the only route out of *done*/*cancelled* (FR-022)."""
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise NotFound("task_not_found")
            before = str(task.status)
            now = utcnow()
            task.reopen(now, reason=reason)
            _mark_provisional(task, now)
            # A closed task carries the two signatures that closed it. Reopening it means
            # the work is not finished after all, so they stop speaking for it — otherwise
            # reopen would be a way back into *done* with nobody looking again.
            await retire_signatures_on_move(uow, task_id, task.status)
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
        await self._settle_drive(task_id)
        return updated

    async def set_next_action(self, task_id: UUID, next_action: str | None) -> Task:
        async with self._uow() as uow:
            updated = await self.set_next_action_within(uow, task_id, next_action)
            await uow.commit()
            return updated

    async def set_next_action_within(
        self, uow: UnitOfWork, task_id: UUID, next_action: str | None
    ) -> Task:
        """The write half of `set_next_action`. **The caller owns the transaction.**"""
        task = await uow.tasks.get(task_id)
        if task is None:
            raise NotFound("task_not_found")
        task.next_action = next_action
        task.updated_at = utcnow()
        return await uow.tasks.update(task)

    # ── acceptance criteria (FR-019) ──────────────────────────────────────────
    async def list_criteria(self, task_id: UUID) -> Sequence[ChecklistItem]:
        async with self._uow() as uow:
            if await uow.tasks.get(task_id) is None:
                raise NotFound("task_not_found")
            return await uow.criteria.list_by_task(task_id)

    async def set_criteria(
        self, task_id: UUID, texts: Sequence[str], *, user_id: str | None = None
    ) -> Sequence[ChecklistItem]:
        """Replace the yardstick. Only before the worker starts — after that it is a
        scope-level change and goes to the patron (FR-075), not into this method."""
        project_id: UUID | None = None
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise NotFound("task_not_found")
            project_id = task.project_id
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
            items = list(await uow.criteria.list_by_task(task_id))

        # The card draws "passed/total" off this list, so rewriting it changes the board
        # (FR-080a) — not only the task's own screen.
        await self._publish(
            project_id,
            EVENT_TASK_CHECKLIST,
            {"task_id": str(task_id), "total": len(items)},
        )
        return items

    async def rate_criterion(
        self,
        task_id: UUID,
        criterion_id: UUID,
        *,
        result: AcceptanceResult,
        evidence_artifact_id: UUID | None = None,
        marius_id: UUID | None = None,
    ) -> ChecklistItem:
        """Score one criterion against the output on the table (Story 3 scenario 1).

        The step the yardstick was written for. Without it the criteria are a note the
        Leader signs *beside* rather than a measure it signs *from* — which is how a list
        of true/false statements (FR-019) ends up gating nothing at all.

        The evidence must be an artifact of **this** task. Anything else would let a pass
        cite a file the reader cannot reach from the task, and a citation nobody can follow
        is worth no more than no citation.
        """
        project_id: UUID | None = None
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise NotFound("task_not_found")
            project_id = task.project_id
            assert_criteria_ratable(task)

            items = list(await uow.criteria.list_by_task(task_id))
            item = next((i for i in items if i.id == criterion_id), None)
            if item is None:
                raise NotFound("criterion_not_found")

            if evidence_artifact_id is not None:
                own = await uow.artifacts.list_by_task(task_id)
                if not any(a.id == evidence_artifact_id for a in own):
                    raise NotFound("artifact_not_found")

            before = str(item.result)
            item.rate(result, evidence_artifact_id=evidence_artifact_id)
            await uow.criteria.update(item)
            await self._log(
                uow,
                task_id,
                TaskLogKind.CRITERIA_CHANGED,
                actor_kind=_actor_kind(None, marius_id),
                actor_marius_id=marius_id,
                before=before,
                after=str(item.result),
                reason=item.text,
                detail={
                    "criterion_id": str(criterion_id),
                    "evidence_artifact_id": (
                        str(evidence_artifact_id) if evidence_artifact_id else None
                    ),
                },
            )
            await uow.commit()

        # Same event as rewriting the list: what changed on screen is the same number.
        # A second name for it would mean every listener has to learn both to draw one
        # badge, and the one that only learned the first draws a stale number.
        await self._publish(
            project_id,
            EVENT_TASK_CHECKLIST,
            {"task_id": str(task_id), "criterion_id": str(criterion_id)},
        )
        return item

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
                raise NotFound("task_not_found")
            if task.project_id != blocker.project_id:
                raise TaskDependencyError("dependency_cross_project")
            # Construct first: the entity rejects a self-loop in __post_init__.
            edge = TaskDependency(task_id=task_id, blocks_task_id=blocks_task_id)
            if await uow.dependencies.get(task_id, blocks_task_id) is not None:
                raise TaskDependencyError("dependency_exists")
            ring = await self._cycle_closed_by(uow, task_id, blocks_task_id)
            if ring:
                raise TaskDependencyError(
                    "dependency_cycle", cycle=await self._name_ring(uow, ring)
                )
            created = await uow.dependencies.add(edge)
            # Waiting on another task is a drive, not a void: the task is accounted for,
            # so the watchdog leaves it alone until the blocker lands.
            if blocker.status is not TaskStatus.DONE and task.status not in (
                TaskStatus.DONE,
                TaskStatus.CANCELLED,
            ):
                _mark_provisional(task, utcnow())
                await uow.tasks.update(task)
            await uow.commit()
            project_id = task.project_id

        # The board draws a lock and a blocker count from these edges, so adding one
        # changes the card (FR-080a).
        await self._publish_dependencies(project_id, task_id)
        return created

    async def remove_dependency(self, task_id: UUID, blocks_task_id: UUID) -> None:
        """Remove a `blocked_by` edge (idempotent — a missing edge is a no-op)."""
        project_id: UUID | None = None
        async with self._uow() as uow:
            # Read before the delete: after it there is nothing left tying the edge to a
            # project, and an event with no channel to go to is the same as no event.
            task = await uow.tasks.get(task_id)
            project_id = task.project_id if task is not None else None
            await uow.dependencies.remove(task_id, blocks_task_id)
            await uow.commit()

        # Announced even when the edge was not there. Whether the row existed is this
        # method's business; whether the board is up to date is not, and a listener that
        # re-reads finds the same numbers and draws the same card at the cost of one query.
        await self._publish_dependencies(project_id, task_id)

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

    async def card_counts(self, project_id: UUID) -> Sequence[TaskCardCounts]:
        """The tallies a board card draws, for every task in one project (T177).

        A card shows a criteria tally, a comment count and a clip for artifacts. None of
        those ride on the task row, and the board only ever fetched task rows — so the
        three badges could not be drawn at all, on any board, ever. That is a step worse
        than the stale value FR-080a describes: the number was not late, it was absent.

        Deliberately counts rather than returning the rows. The board renders `3` and a
        clip; shipping three comment bodies per card to produce that would put a task's
        whole conversation on a screen that never shows a word of it.

        Tasks with nothing to report are omitted — the caller reads a missing task as all
        zeroes, which is what it is, instead of paying for a row per empty card.
        """
        async with self._uow() as uow:
            comments = await uow.comments.count_by_project(project_id)
            artifacts = await uow.artifacts.count_by_project(project_id)
            criteria = await uow.criteria.count_by_project(project_id)
        return [
            TaskCardCounts(
                task_id=task_id,
                comments=comments.get(task_id, 0),
                artifacts=artifacts.get(task_id, 0),
                criteria_total=criteria.get(task_id, ChecklistTally()).total,
                criteria_passed=criteria.get(task_id, ChecklistTally()).passed,
            )
            for task_id in {*comments, *artifacts, *criteria}
        ]

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
            if dependent is None or dependent.status in TERMINAL_STATUSES:
                continue
            # Asked of the dependency edges, never of the drive. This used to read
            # `drive is BLOCKED_BY_TASK` as shorthand for "was blocked", which made a
            # cached, derived field the gatekeeper of a real question — so a task whose
            # drive said anything else stayed locked forever with every blocker finished.
            # The edges are the fact; the drive is a summary of it.
            if not await uow.dependencies.all_blockers_done(dependent.id):
                continue
            now = utcnow()
            before = str(dependent.status)
            if dependent.status in (TaskStatus.BACKLOG, TaskStatus.BLOCKED):
                dependent.transition_to(TaskStatus.TODO, now, deps_satisfied=True)
            _mark_provisional(dependent, now)
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
        """Close the scope question once the draft has been decided, either way.

        Filtered by kind, because this call only knows that *its own* question is settled.
        A task can be holding a stalled-task escalation at the same time, and closing that
        one here would be worse than noise: it is the patron's only copy of a question the
        system cannot re-ask, and the task would keep the stale *waiting on the patron*
        answer with no deadline — outside the sweep, with nobody left to notice.
        """
        if self._inbox is not None:
            await self._inbox.resolve_pending_for_task(
                task_id, kind=InboxItemKind.MAJOR_CHANGE_APPROVAL
            )

    async def _wake_the_freed(self, freed: Task, *, cleared_by: Task) -> None:
        """Call whoever holds a task that just stopped waiting (FR-048, SC-009).

        Two conditions, and both are about not calling somebody to look at nothing.

        *Somebody holds it* — an unassigned task has no one to wake; it needs the Leader to
        put a name on it, and the recovery ladder is the road there (FR-059).

        *It is on the board* — being unblocked is not the same as being approved. A draft
        stops waiting exactly like any other task, but it is still a proposal, and telling
        a worker "your part is ready" about a proposal is telling it something untrue. The
        status is read after the unlock, so this is the question "is it work now", not "was
        it moved just now": a task already *in progress* has somebody on it who does not
        need to be interrupted to be told they may continue.
        """
        if freed.assigned_marius_id is None or freed.status is not TaskStatus.TODO:
            return
        await self._wake.enqueue(
            marius_id=freed.assigned_marius_id,
            task_id=freed.id,
            source=WakeSource.DEPENDENCY_CLEARED,
            reason=wake_reason(
                "dependency_cleared", blocker=cleared_by.identifier or cleared_by.id
            ),
        )

    async def _notify_leader(
        self,
        project_id: UUID | None,
        *,
        reason: WakeReason,
        source: WakeSource,
        detail: str = "",
    ) -> None:
        if self._leader_chat is None or project_id is None:
            return
        await self._leader_chat.notify(
            project_id=project_id, source=source, reason=reason, detail=detail
        )

    async def _publish_status(
        self, project_id: UUID | None, task_id: UUID, status: TaskStatus
    ) -> None:
        await self._publish(
            project_id,
            EVENT_TASK_STATUS,
            {"task_id": str(task_id), "status": str(status)},
        )

    async def _publish_dependencies(
        self, project_id: UUID | None, task_id: UUID
    ) -> None:
        await self._publish(
            project_id, EVENT_TASK_DEPENDENCIES, {"task_id": str(task_id)}
        )

    async def _publish(
        self, project_id: UUID | None, event: str, data: dict[str, object]
    ) -> None:
        """Identifiers and labels only — never task content (contracts/push-events §4)."""
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

    async def _cycle_closed_by(
        self, uow: UnitOfWork, task_id: UUID, blocks_task_id: UUID
    ) -> list[UUID]:
        """The ring adding "task_id blocked_by blocks_task_id" would close — empty if none.

        Answers with the ring itself rather than yes/no because FR-032 asks the refusal to
        say *which* tasks the cycle runs through. A reader told only that "this would make
        a cycle" has to find it by hand on a board where the one edge that would reveal it
        is precisely the edge that was just refused.

        Walks "what does this wait on" outwards from ``blocks_task_id``, keeping a parent
        for each hop so the path home can be read back the moment ``task_id`` turns up.
        """
        parent: dict[UUID, UUID] = {}
        seen: set[UUID] = set()
        frontier: list[UUID] = [blocks_task_id]
        while frontier:
            current = frontier.pop()
            if current == task_id:
                back: list[UUID] = [current]
                while current in parent:
                    current = parent[current]
                    back.append(current)
                back.reverse()
                # Named from the edge being added, and closing on itself, so the ring reads
                # as a ring: A → B → … → A.
                return [task_id, *back]
            if current in seen:
                continue
            seen.add(current)
            for edge in await uow.dependencies.list_blockers(current):
                if edge.blocks_task_id is not None and edge.blocks_task_id not in seen:
                    parent[edge.blocks_task_id] = current
                    frontier.append(edge.blocks_task_id)
        return []

    async def _name_ring(self, uow: UnitOfWork, ring: Sequence[UUID]) -> str:
        """The ring as a reader sees it on the board: task codes, in order."""
        names: list[str] = []
        for tid in ring:
            found = await uow.tasks.get(tid)
            names.append((found.identifier if found else None) or str(tid))
        return " → ".join(names)


def _actor_kind(user_id: str | None, marius_id: UUID | None) -> ActorKind:
    if user_id:
        return ActorKind.USER
    if marius_id:
        return ActorKind.AGENT
    return ActorKind.SYSTEM


def _mark_provisional(task: Task, now: datetime) -> None:
    """Stamp the drive a status implies, pending the authoritative refresh (FR-056).

    Always inside the transaction that changed the status, so a task is never committed
    with a drive left over from the status it used to be in. The value is deliberately
    short-lived: `provisional_drive` gives every placeholder a clock precisely because it
    is a guess, and a guess that never expires is how a forgotten task stays invisible.
    """
    reason = provisional_drive(task.status, now=now)
    task.drive = reason.kind if reason else None
    task.drive_expires_at = reason.expires_at if reason else None
    task.drive_code = reason.code if reason else None
