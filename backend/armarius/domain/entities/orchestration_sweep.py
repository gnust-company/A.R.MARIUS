"""One pass of the orchestration cadence over one project (spec 001 FR-052 → FR-055).

Why a row at all, when most sweeps do nothing? Because "the Leader was not woken" is the
pass condition of a healthy project (FR-053) **and** the symptom of a loop that never ran.
Nothing in the rest of the system can tell those two apart. A sweep that leaves a line
behind can: swept at this time, looked at the board, found nothing, next look in N seconds.

The row is also what makes the rhythm honest across a restart. The quiet streak that earns
a project its slack, and the ceiling on wakes per hour, are both read back from these rows
rather than held in a counter on a live object — a counter that a redeploy resets is a
ceiling that a redeploy lifts.

Append-only, like the task log: a sweep is something that happened.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from armarius.domain.services.orchestration_cadence import Snag


@dataclass
class OrchestrationSweep:
    id: UUID = field(default_factory=uuid4)
    project_id: UUID | None = None
    swept_at: datetime | None = None
    # What the sweep found. Kept whole rather than as a count so the board can show the
    # Leader's last look without re-deriving it, and so a sweep stays readable months later.
    snags: list[Snag] = field(default_factory=list)
    # Whether this sweep **spent** a wake against the hourly ceiling. A wake the Leader
    # could not receive still counts as spent: it is on the record as a pending cause and
    # the Leader reads it when it returns, so charging it keeps an hour offline from
    # handing the same backlog over four times.
    woke_leader: bool = False
    # Why the Leader did not hear about this sweep, when it did not. Two different cases
    # land here and they must stay tellable apart afterwards, so they are stated in words:
    #   * `woke_leader` false — no wake was sent at all (the ceiling stopped it);
    #   * `woke_leader` true — a wake was spent but could not be delivered.
    # A boolean would collapse "the ceiling is working" and "the Leader has been offline
    # all hour" into one indistinguishable silence, and only the second needs a human.
    skipped_reason: str | None = None
    # The gap this sweep decided on. Stored, not recomputed, so the board can say when the
    # next look is due and so a rhythm change is visible in the record.
    next_interval_seconds: int = 0
    # Per-task deadline marks announced so far, `{task_id: hours}`. Carried forward so a
    # warning fires when it is crossed and not on every sweep afterwards (FR-052).
    reported_marks: dict[str, int] = field(default_factory=dict)

    @property
    def snag_count(self) -> int:
        return len(self.snags)
