"""The recovery ladder standing on one task (spec 001 §9, FR-059 → FR-061).

The drive itself — *what* is moving the task and *until when* — lives on the task row, so
the stall sweep can find a dropped task with one indexed scan and no join. What lives here
is the part the sweep does not read on every pass: which rung of the recovery ladder this
task is on, how much of the Level-1 budget the current cause has spent, and when the next
attempt comes due.

One row per task, at most. That is a unique key in the schema, not a convention: two
ladders on one task would let two sweeps each think they were the one escalating, and the
patron would be asked twice about the same thing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from armarius.domain.services.escalation import EscalationLevel, EscalationState


@dataclass
class TaskPushReason:
    """Ladder state for one task, plus what its drive points at."""

    id: UUID = field(default_factory=uuid4)
    task_id: UUID | None = None
    # What the drive references, when it references something: the blocking tasks, the
    # inbox item, the run. Text because the six kinds point at four different tables.
    ref: str | None = None
    level: EscalationLevel = EscalationLevel.NONE
    attempts: int = 0
    cause: str | None = None
    last_attempt_at: datetime | None = None
    next_retry_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def state(self) -> EscalationState:
        """The ladder position as the pure rules want it."""
        return EscalationState(
            level=self.level, attempts=self.attempts, cause=self.cause or ""
        )

    def apply(self, state: EscalationState, *, now: datetime) -> None:
        """Write a rung the rules decided back onto the row."""
        self.level = state.level
        self.attempts = state.attempts
        self.cause = state.cause or None
        self.updated_at = now
