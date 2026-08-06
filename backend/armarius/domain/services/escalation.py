"""Thang phục hồi ba mức — pure rules (FR-059, FR-060).

When a task stops moving, three parties can do something about it, and they cost wildly
different amounts. The system re-waking the assignee costs an agent turn. The Leader
deciding a recovery action costs a Leader turn and a judgement. The patron being asked
costs a human's attention, and that is the one thing this system cannot mint more of.

So the ladder is ordered by cost and climbed one rung at a time (FR-059). **No skipping**
is the rule that carries the weight: a ladder that can jump straight to the patron is a
ladder that asks a person for something the system had not even tried once, and after two
of those the person stops reading.

Two things this module deliberately does *not* know: what counts as "real progress" (that
is a judgement about comments, artifacts and status moves, and it belongs to the
application layer, which passes the verdict in), and what the recovery action actually is.
It knows only which rung the task is on and what moves it between rungs.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import IntEnum

# The gap between Level-1 attempts doubles, but never past this. Doubling without a ceiling
# turns the eighth attempt into a wait measured in days — a retry that is a *never* dressed
# as a retry. The ladder is supposed to run out of patience and escalate, not to schedule
# itself past the end of the project.
MAX_BACKOFF_SECONDS = 2 * 60 * 60


class EscalationLevel(IntEnum):
    """Which rung a stuck task is on. Ordered — the comparisons below rely on it."""

    NONE = 0  # nothing wrong, or just recovered
    LEVEL_1 = 1  # the system re-wakes the same assignee; nothing new is decided
    LEVEL_2 = 2  # the Leader decides an explicit recovery action
    LEVEL_3 = 3  # the patron is asked, with the record of everything already tried


@dataclass(frozen=True)
class EscalationState:
    """Where one task stands on the ladder, for one cause.

    ``cause`` is part of the state rather than a label on the side because FR-060 counts
    the Level-1 budget **per cause per task**. A task that burned three attempts on an
    offline assignee, got fixed, and later hit a missing artifact is at the start of a new
    problem — charging it for the old one would leave it out of tries the first time the
    new problem appeared.
    """

    level: EscalationLevel = EscalationLevel.NONE
    attempts: int = 0
    cause: str = ""


def advance(
    state: EscalationState,
    *,
    cap: int,
    progressed: bool,
    leader_acted: bool,
    cause: str | None = None,
) -> EscalationState:
    """Where the ladder stands after one more sweep found this task still stuck.

    ``progressed`` — the task genuinely moved since the last look. ``leader_acted`` — the
    Leader decided the recovery action Level 2 was waiting for. ``cause`` — what the task
    is stuck on now; a different cause than the one on record starts a fresh budget.
    """
    # Real progress clears the whole ladder, budget included (FR-060). Giving back one
    # attempt instead would let a task that recovers four times still hit the ceiling on
    # its fifth stall, having never once exhausted a budget.
    if progressed:
        return EscalationState(level=EscalationLevel.NONE, attempts=0, cause=cause or "")

    # A new cause is a new problem. Same task, same ladder, fresh budget.
    if cause is not None and cause != state.cause:
        return EscalationState(level=EscalationLevel.LEVEL_1, attempts=1, cause=cause)

    if state.level is EscalationLevel.NONE:
        return replace(state, level=EscalationLevel.LEVEL_1, attempts=1)

    if state.level is EscalationLevel.LEVEL_1:
        if state.attempts < cap:
            return replace(state, attempts=state.attempts + 1)
        # Budget spent. Hand over — and leave the counter where it is, because that number
        # is what the dossier reports as "tried this many times" (FR-061).
        return replace(state, level=EscalationLevel.LEVEL_2)

    if state.level is EscalationLevel.LEVEL_2:
        # The Leader deciding is what this rung was waiting for; the task is unstuck by
        # decision even if it has not moved yet. Climbing anyway would tell the patron a
        # decision was never made.
        if leader_acted:
            return EscalationState(level=EscalationLevel.NONE, attempts=0, cause=state.cause)
        # Note the attempt counter is *not* touched here: Level 2 is a decision, not an
        # attempt, and inflating it would make the dossier claim tries that never happened.
        return replace(state, level=EscalationLevel.LEVEL_3)

    # Level 3. There is nothing above the patron, and the inbox item is already waiting on
    # them — further sweeps must leave the state completely alone rather than churn it.
    return state


def backoff_seconds(attempt: int, *, base_seconds: int) -> int:
    """How long to wait before Level-1 attempt number ``attempt`` (1-based).

    Doubling, floored at ``base_seconds`` and capped at :data:`MAX_BACKOFF_SECONDS`.
    """
    if attempt <= 1:
        return base_seconds
    return min(base_seconds * 2 ** (attempt - 1), MAX_BACKOFF_SECONDS)
