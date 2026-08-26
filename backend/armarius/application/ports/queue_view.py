"""QueueView port — what the queue knows about one task's work (FR-008a, FR-056b).

The safety net asks whether a task is still moving. Two of its answers cannot be found in
any table the business layer owns, because both are about *where* the work would run:

  * a task that is ready and has nowhere to start is waiting, not dropped — and the thing
    it is waiting on is the runs already filling every slot it could use (FR-008a);
  * a task whose work was taken once and given back has been waiting since it was given
    back, not since it was first booked (FR-056b).

Both come back from one call, on purpose. Asked separately they are two readings of the
same queue taken at two moments, and a task can look full in one and empty in the other —
which produces a drive and a deadline that disagree about the same task.

Deliberately says nothing about machines, daemons or workplaces: the caller learns that a
slot is taken and by which run, never where the slot is (Constitution III).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class QueuePosition:
    """Where one task's work stands among the places it could run."""

    # The runs holding every slot this task could start in. Empty means slots are not what
    # is holding this task up — either there is room, or the task is not waiting for any.
    runs_filling_every_slot: tuple[str, ...] = ()
    # The last time anything took this task's work, whether or not it still holds it. An
    # accept is evidence; a booking is a promise, and the two should not share a clock.
    last_taken_at: datetime | None = None


class QueueView(ABC):
    @abstractmethod
    async def position_of(self, task_id: UUID) -> QueuePosition:
        """Both answers about one task, read together."""
        ...
