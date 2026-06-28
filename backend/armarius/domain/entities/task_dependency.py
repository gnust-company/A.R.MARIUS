"""TaskDependency — a blocked_by edge between two tasks (LLD §2.9).

`task_id` is blocked; it waits on `blocks_task_id`. No self-loops, unique per pair.
The dependency-gate (task.py) keeps a task out of todo/in_progress until every task it
is blocked_by is done.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4


class TaskDependencyError(Exception):
    """Raised for an invalid dependency edge (e.g. a self-loop)."""


@dataclass
class TaskDependency:
    id: UUID = field(default_factory=uuid4)
    task_id: UUID | None = None  # the blocked task
    blocks_task_id: UUID | None = None  # the task it waits on

    def __post_init__(self) -> None:
        if (
            self.task_id is not None
            and self.blocks_task_id is not None
            and self.task_id == self.blocks_task_id
        ):
            raise TaskDependencyError("A task cannot depend on itself.")
