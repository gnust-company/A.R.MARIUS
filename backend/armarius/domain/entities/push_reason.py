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
    # How many times the Level-2 handover was tried and did not reach the Leader.
    # Zero also means "the Leader was actually reached", which is what the Level-3
    # dossier reads to decide whether it may say the Leader was asked.
    handover_attempts: int = 0
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
        """Write a rung the rules decided back onto the row.

        The handover budget lives and dies with the Level-1 budget, and it has to, because
        the patron's dossier prints the two side by side. `advance` already owns that
        lifetime — it hands back a fresh budget when the task made real progress, when the
        Leader decided, and when the cause changed — so the handover count is cleared off
        the same decision rather than from a second place that could disagree with it.

        Miss this and the count stops measuring *this problem* and starts measuring the
        task's whole history: one unreachable Leader, months ago, and every later stall
        arrives at the patron labelled "the Leader was never reached" — while the Leader is
        sitting there answering. That is the exact lie the counter was added to prevent,
        told along the time axis instead of the column axis.
        """
        if state.level is EscalationLevel.NONE or (state.cause or "") != (self.cause or ""):
            self.handover_attempts = 0
        self.level = state.level
        self.attempts = state.attempts
        self.cause = state.cause or None
        self.updated_at = now
