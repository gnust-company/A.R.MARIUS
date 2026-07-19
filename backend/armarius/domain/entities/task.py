"""Task entity — the unit of work AND a collaboration room.

Carries the full lifecycle from PROJECT_DESCRIPTION §4.3 plus the durable
`next_action` (so a task can always be resumed from task state, not session).

Two gates are enforced here in pure form (LLD §3.2):
  - DONE-gate    — a task cannot enter review/done without a published artifact.
  - dependency-gate — a task cannot enter todo/in_progress while a `blocked_by`
                    dependency is unfinished.
The application layer supplies `has_artifact` / `deps_satisfied`; the domain decides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


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


TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED})

# Statuses that require a published artifact to be linked (§3.4 "definition of done").
ARTIFACT_REQUIRED_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.IN_REVIEW, TaskStatus.DONE}
)

# Statuses you may only enter once every `blocked_by` dependency is done (LLD §3.2).
DEPENDENCY_GATED_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.TODO, TaskStatus.IN_PROGRESS}
)

VALID_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    # A draft is a Leader proposal: it is confirmed into the board (todo) or dropped.
    TaskStatus.DRAFT: frozenset({TaskStatus.TODO, TaskStatus.CANCELLED}),
    TaskStatus.BACKLOG: frozenset({TaskStatus.TODO, TaskStatus.CANCELLED}),
    TaskStatus.TODO: frozenset(
        {TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.BACKLOG, TaskStatus.CANCELLED}
    ),
    TaskStatus.IN_PROGRESS: frozenset(
        {
            TaskStatus.IN_REVIEW,
            TaskStatus.BLOCKED,
            TaskStatus.DONE,
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
    TaskStatus.DONE: frozenset({TaskStatus.IN_PROGRESS}),
    TaskStatus.CANCELLED: frozenset({TaskStatus.BACKLOG}),
}


class TaskTransitionError(Exception):
    """Raised when an illegal status transition is attempted."""


class ArtifactRequiredError(Exception):
    """Raised when moving to review/done without a linked published artifact."""


class DependencyNotMetError(Exception):
    """Raised when entering todo/in_progress while a blocked_by dependency is unfinished."""


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
    definition_of_done: str | None = None
    # assigned_marius_id kept for back-compat; superseded by TaskParticipant (primary).
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
    ) -> None:
        """Validate and apply a status transition.

        Enforces two gates (LLD §3.2):
          - DONE-gate: cannot enter review/done unless a published artifact is linked.
          - dependency-gate: cannot enter todo/in_progress while a blocked_by
            dependency is unfinished.
        """
        if target == self.status:
            if reason is not None:
                self.status_reason = reason
            return
        if not self.can_transition_to(target):
            raise TaskTransitionError(
                f"Cannot move task from '{self.status}' to '{target}'."
            )
        if target in ARTIFACT_REQUIRED_STATUSES and not has_artifact:
            raise ArtifactRequiredError(
                "A published artifact must be linked before review/done."
            )
        if target in DEPENDENCY_GATED_STATUSES and not deps_satisfied:
            raise DependencyNotMetError(
                "A blocked_by dependency is not done yet."
            )
        self.status = target
        self.status_reason = reason
        if target == TaskStatus.IN_PROGRESS:
            self.in_progress_at = now
        elif target == TaskStatus.DONE:
            self.completed_at = now
