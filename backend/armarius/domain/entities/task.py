"""Task entity — the unit of work AND a collaboration room.

Carries the full lifecycle from PROJECT_DESCRIPTION §4.3 plus the durable
`next_action` (so a task can always be resumed from task state, not session).

**Five gates** are enforced here in pure form (spec 001 §E, data-model §6):

  - DONE-gate (evidence) — cannot enter review/done without a published artifact.
  - dependency-gate      — cannot enter todo/in_progress while a `blocked_by`
                           dependency is unfinished.
  - description-gate     — cannot be handed to a worker with an empty description (FR-029).
  - reason-gate          — cannot enter blocked/cancelled, or be sent back for rework,
                           without saying why (FR-030).
  - scope-gate           — a task pointing at no approved plan item stays a draft (FR-027);
                           the rule lives here, the lookup of *which* items are approved
                           belongs to the application layer.

The application layer supplies `has_artifact` / `deps_satisfied`; the domain decides.

Two statuses are **closed** (FR-022): *done* and *cancelled* have no everyday route out.
The only way back is :meth:`Task.reopen`, which demands a reason and leaves a trace — so
"we quietly un-finished it" cannot happen without someone signing their name to it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from armarius.shared.errors import CodedError


class TaskStatus(StrEnum):
    DRAFT = "draft"  # Leader's proposal; → todo only on approve (Leader chat, #82)
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskPriority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskDrive(StrEnum):
    """What is going to move this task forward (FR-056).

    Every unclosed task carries exactly one. The point is not bookkeeping: a task with no
    live drive is a task the system has *dropped*, and that is what the safety net looks
    for. The six are exhaustive on purpose — if a situation does not fit one of them, the
    task is stalled, not "in some other state".

    Story 6 owns keeping this accurate under every failure mode; Story 2 sets it at the
    moments it already knows about (blocked by another task, handed back to the Leader).
    """

    RUN_ACTIVE = "run_active"  # an agent run is live on it right now
    WAKE_SCHEDULED = "wake_scheduled"  # a wake is booked (agent or Leader)
    WAITING_EXTERNAL = "waiting_external"  # waiting on a date or an outside party
    WAITING_PATRON = "waiting_patron"  # parked on a patron decision
    BLOCKED_BY_TASK = "blocked_by_task"  # waiting on another task to finish
    WAITING_RECOVERY = "waiting_recovery"  # waiting on a recovery attempt


TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED})

# Statuses that require a published artifact to be linked (§3.4 "definition of done").
ARTIFACT_REQUIRED_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.IN_REVIEW, TaskStatus.DONE}
)

# Statuses you may only enter with both signatures on the record (FR-033). *Done* is the
# only one — that is the whole point: review is where the work is judged, but closing it
# takes the Leader **and** the patron responsible for the agent that did it.
SIGNATURE_REQUIRED_STATUSES: frozenset[TaskStatus] = frozenset({TaskStatus.DONE})

# Statuses you may only enter with every acceptance criterion scored *passed* (FR-019).
# The signature gate above asks whether the right people said yes; this one asks whether
# anybody measured the work against the yardstick they were handed before saying it.
CRITERIA_REQUIRED_STATUSES: frozenset[TaskStatus] = frozenset({TaskStatus.DONE})

# Statuses you may only enter once every `blocked_by` dependency is done (LLD §3.2).
DEPENDENCY_GATED_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.TODO, TaskStatus.IN_PROGRESS}
)

VALID_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    # A draft is a Leader proposal: confirmed onto the board, shelved, or dropped.
    TaskStatus.DRAFT: frozenset(
        {TaskStatus.TODO, TaskStatus.BACKLOG, TaskStatus.CANCELLED}
    ),
    TaskStatus.BACKLOG: frozenset({TaskStatus.TODO, TaskStatus.CANCELLED}),
    TaskStatus.TODO: frozenset(
        {TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.BACKLOG, TaskStatus.CANCELLED}
    ),
    # No *in_progress → done*: a worker does not get to declare its own work finished
    # (FR-024). Review is the only door into done.
    TaskStatus.IN_PROGRESS: frozenset(
        {
            TaskStatus.IN_REVIEW,
            TaskStatus.BLOCKED,
            TaskStatus.TODO,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.IN_REVIEW: frozenset(
        {TaskStatus.DONE, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.CANCELLED}
    ),
    TaskStatus.BLOCKED: frozenset(
        {TaskStatus.IN_PROGRESS, TaskStatus.TODO, TaskStatus.BACKLOG, TaskStatus.CANCELLED}
    ),
    # Closed. The way back is `reopen`, not a transition (FR-022).
    TaskStatus.DONE: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}

# Where `reopen` puts a closed task: finished work resumes, a dropped one goes back on the
# shelf rather than straight into someone's queue.
REOPEN_TARGETS: dict[TaskStatus, TaskStatus] = {
    TaskStatus.DONE: TaskStatus.IN_PROGRESS,
    TaskStatus.CANCELLED: TaskStatus.BACKLOG,
}

# Moves that are bad news for somebody, so they must come with a reason (FR-030). The
# third one — *in_review → in_progress*, sending work back for rework — is a pair rather
# than a target, because entering *in_progress* from anywhere else is ordinary progress.
REASON_REQUIRED_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.BLOCKED, TaskStatus.CANCELLED}
)
REASON_REQUIRED_MOVES: frozenset[tuple[TaskStatus, TaskStatus]] = frozenset(
    {(TaskStatus.IN_REVIEW, TaskStatus.IN_PROGRESS)}
)


class TaskTransitionError(CodedError):
    """Raised when an illegal status transition is attempted."""


class ArtifactRequiredError(CodedError):
    """Raised when moving to review/done without a linked published artifact."""


class DependencyNotMetError(CodedError):
    """Raised when entering todo/in_progress while a blocked_by dependency is unfinished.

    Names what is still missing in its parameters (FR-025). "A dependency is not done"
    tells the reader nothing they can act on; "TASK-3, TASK-7" tells them where to look.
    """


class DescriptionRequiredError(CodedError):
    """Raised when handing a task to a worker with an empty description (FR-029)."""


class StatusReasonRequiredError(CodedError):
    """Raised when a move that needs a stated reason arrives without one (FR-030)."""


class StalledTaskError(CodedError):
    """Raised when something tries to close a task the system has dropped (FR-058)."""


class SignaturesRequiredError(CodedError):
    """Raised when a task is closed without both signatures (FR-033).

    Names who is still missing, because "not approved yet" leaves the reader hunting for
    whose turn it is.
    """


class CriteriaNotMetError(CodedError):
    """Raised when a task is closed with a criterion still unrated or failed (FR-019).

    Names them, for the same reason `SignaturesRequiredError` names who is missing.
    """


class DescriptionLockedError(CodedError):
    """Raised when a worker tries to rewrite the requirement it was given (FR-018)."""


def _is_blank(value: str | None) -> bool:
    return value is None or not value.strip()


def assert_assignable(task: Task) -> None:
    """The description-gate (FR-029).

    Called at the moment a task is handed to a worker — assignment, and the approval that
    releases a draft onto the board. Deliberately *not* called at create time: a patron may
    jot down a title and fill in the detail afterwards. What must never happen is a worker
    receiving a one-line title and being left to guess the job.
    """
    if _is_blank(task.description):
        raise DescriptionRequiredError("task_needs_description")


def is_in_scope(task: Task) -> bool:
    """The scope-gate in its pure form (FR-027): does this task point at a plan item?

    Whether that item belongs to an *approved* plan is a lookup, and lookups belong to the
    application layer — which resolves the item first and only then hands a task here.
    """
    return task.plan_item_id is not None


@dataclass
class Task:
    id: UUID = field(default_factory=uuid4)
    project_id: UUID | None = None
    # Project-scoped human-readable code "{project.key}-{seq}", e.g. "CALC-7" — minted
    # by TaskService.create from the project's key + monotonic counter (never reused).
    identifier: str | None = None
    title: str = ""
    description: str | None = None
    status: TaskStatus = TaskStatus.BACKLOG
    status_reason: str | None = None
    priority: TaskPriority = TaskPriority.MEDIUM
    parent_id: UUID | None = None  # subtask of another task
    due_date: datetime | None = None
    # Free-text "definition of done" — superseded by the acceptance-criteria list
    # (`checklist_item.py`, FR-019). Kept because the old prose is still readable history;
    # the migration turned each project's text into a single unrated criterion.
    definition_of_done: str | None = None
    # The plan item this task belongs to (FR-027). Empty means *outside the approved
    # plan* — which is not an error, it is a proposal the patron has to widen scope for.
    plan_item_id: UUID | None = None
    # What is going to move this forward. None on a closed task; Story 6 keeps it honest.
    drive: TaskDrive | None = None
    # When that drive stops being believable (FR-057). None means *this drive has no clock*
    # — a wait on a patron or on another task, both already chased by something else — and
    # never "expired". The stall sweep reads exactly these two fields, which is why they sit
    # on the task rather than beside the ladder state.
    drive_expires_at: datetime | None = None
    # Raised by the safety net when a task loses every live drive (FR-058). Not a status:
    # it is an alarm that the system dropped this task, and it seals every door into done.
    stalled: bool = False
    stalled_reason: str | None = None
    # The task's single assignee (one owner per task) — the sole source of truth.
    assigned_marius_id: UUID | None = None
    created_by_user_id: str | None = None
    created_by_marius_id: UUID | None = None
    # Durable continuation hint — what the agent intends to do next (§4.3).
    next_action: str | None = None
    in_progress_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def can_transition_to(self, target: TaskStatus) -> bool:
        return target in VALID_TRANSITIONS.get(self.status, frozenset())

    def transition_to(
        self,
        target: TaskStatus,
        now: datetime,
        *,
        has_artifact: bool = False,
        deps_satisfied: bool = True,
        reason: str | None = None,
        unmet_blockers: tuple[str, ...] = (),
        signatures_complete: bool = False,
        missing_signatures: tuple[str, ...] = (),
        criteria_met: bool = False,
        unmet_criteria: tuple[str, ...] = (),
    ) -> None:
        """Validate and apply a status transition.

        Enforces, in order: the transition table, the stall seal, the signature gate, the
        criteria gate, the evidence gate, the dependency gate and the reason gate. The
        order matters — the message a caller gets should name the *first* thing wrong with
        the move, not a downstream consequence.

        ``signatures_complete`` and ``criteria_met`` both default to **False**: closing a
        task is the one move that must fail shut. A caller that forgets to look either of
        them up gets a refusal, not a silent close.
        """
        if target == self.status:
            if reason is not None:
                self.status_reason = reason
            return
        if not self.can_transition_to(target):
            raise TaskTransitionError(
                "task_transition_invalid", current=self.status, target=target
            )
        if target is TaskStatus.DONE and self.stalled:
            # The stall verdict is still free text on the row, so it is handed over as a
            # parameter rather than folded into the wording — and when there is none, the
            # refusal says so with its own code instead of a blank pair of brackets (T200).
            if self.stalled_reason:
                raise StalledTaskError(
                    "task_stalled_cannot_finish_named", reason=self.stalled_reason
                )
            raise StalledTaskError("task_stalled_cannot_finish")
        if target in SIGNATURE_REQUIRED_STATUSES and not signatures_complete:
            listed = ", ".join(missing_signatures)
            if listed:
                raise SignaturesRequiredError(
                    "task_needs_signatures_named", missing=listed
                )
            raise SignaturesRequiredError("task_needs_signatures")
        if target in CRITERIA_REQUIRED_STATUSES and not criteria_met:
            listed = ", ".join(unmet_criteria)
            if listed:
                raise CriteriaNotMetError("task_criteria_unmet_named", unmet=listed)
            raise CriteriaNotMetError("task_criteria_unmet")
        if target in ARTIFACT_REQUIRED_STATUSES and not has_artifact:
            raise ArtifactRequiredError("task_needs_artifact")
        if target in DEPENDENCY_GATED_STATUSES and not deps_satisfied:
            listed = ", ".join(unmet_blockers)
            if listed:
                raise DependencyNotMetError(
                    "task_dependencies_unmet_named", blockers=listed
                )
            raise DependencyNotMetError("task_dependencies_unmet")
        if self._reason_required(target) and _is_blank(reason):
            raise StatusReasonRequiredError("task_move_needs_reason", target=target)
        self.status = target
        self.status_reason = reason
        if target == TaskStatus.IN_PROGRESS:
            self.in_progress_at = now
        elif target == TaskStatus.DONE:
            self.completed_at = now

    def _reason_required(self, target: TaskStatus) -> bool:
        return (
            target in REASON_REQUIRED_STATUSES
            or (self.status, target) in REASON_REQUIRED_MOVES
        )

    def reopen(self, now: datetime, *, reason: str | None) -> None:
        """Bring a closed task back to life — the only route out of *done*/*cancelled*.

        Kept off the transition table on purpose: reopening finished work is a decision
        someone makes, not a status change that happens. It always costs a reason, and the
        completion mark is cleared so a task cannot look finished and unfinished at once.
        """
        target = REOPEN_TARGETS.get(self.status)
        if target is None:
            raise TaskTransitionError("task_reopen_not_closed", status=self.status)
        if _is_blank(reason):
            raise StatusReasonRequiredError("task_reopen_needs_reason")
        self.status = target
        self.status_reason = reason
        self.completed_at = None
        self.updated_at = now

    def set_description(self, description: str | None, *, by_worker: bool) -> None:
        """Rewrite the requirement. Workers may not (FR-018).

        A worker reports progress in the task's thread; the brief it was handed stays the
        brief. Otherwise a task quietly drifts into whatever turned out to be easy, and
        the acceptance criteria end up measuring the wrong thing.
        """
        if by_worker:
            raise DescriptionLockedError("task_description_locked")
        self.description = description
