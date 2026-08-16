"""Thang phục hồi ba mức — pure rules (FR-059, FR-060).

When a task stops moving, three parties can do something about it, and they cost wildly
different amounts. The system re-waking the assignee costs an agent turn. The Leader
deciding a recovery action costs a Leader turn and a judgement. The patron being asked
costs a human's attention, and that is the one thing this system cannot mint more of.

So the ladder is ordered by cost and climbed one rung at a time (FR-059). **No skipping**
is the rule that carries the weight: a ladder that can jump straight to the patron is a
ladder that asks a person for something the system had not even tried once, and after two
of those the person stops reading.

Each rung also has an **entry condition**, checked before the rung is entered rather than
discovered inside it (FR-059a). Level 1 is defined as *re-wake the same assignee*, so a
task with nobody on it has no rung to enter: it goes straight to Level 2, and spends no
budget on the way. That is not skipping. Skipping is passing over a rung that could still
work; this is a rung that does not apply. Before the check existed, an unassigned task
burned its whole Level-1 budget — three attempts, spaced 5, 10 and 20 minutes — calling a
number nobody was on, and only then asked the Leader.

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

    ``handovers`` is the same idea one rung up: how many times the Leader has been asked
    about this cause. Two budgets, one law, one place — a second counter kept outside this
    state was free to disagree with the first, and did.
    """

    level: EscalationLevel = EscalationLevel.NONE
    attempts: int = 0
    handovers: int = 0
    cause: str = ""


def advance(
    state: EscalationState,
    *,
    cap: int,
    handover_cap: int,
    progressed: bool,
    cause: str | None = None,
    level1_available: bool = True,
) -> EscalationState:
    """Where the ladder stands after one more sweep found this task still stuck.

    ``progressed`` — the task genuinely moved since the last look. ``cause`` — what the
    task is stuck on now; a different cause than the one on record starts a fresh budget.
    ``level1_available`` — whether Level 1 has anything to act on, i.e. whether the task
    has an assignee to re-wake (FR-059a). False sends the task straight to Level 2 without
    spending a single attempt, and keeps it there if it is already on Level 1: a rung that
    stopped applying halfway through is no more enterable than one that never applied.

    The flag is phrased as *is this rung available* rather than *is somebody assigned* on
    purpose. This module knows rungs and budgets; who is on a task is the application
    layer's fact to look up and pass in, the same way ``progressed`` is.

    There is deliberately no "the Leader answered" input. Answering is not the thing this
    ladder measures — a Leader can say *I reassigned it to Bob* and leave a task exactly as
    dead as it was. What ends Level 2 is the same fact that ends Level 1 and the same fact
    that started the whole thing: **something is scheduled to touch the task again**. The
    caller reports that as ``progressed``, and it is checked against the task row rather
    than taken on anybody's word.
    """
    # Real progress clears the whole ladder, budget included (FR-060). Giving back one
    # attempt instead would let a task that recovers four times still hit the ceiling on
    # its fifth stall, having never once exhausted a budget.
    if progressed:
        return EscalationState(level=EscalationLevel.NONE, cause=cause or "")

    # A new cause is a new problem. Same task, same ladder, fresh budget — both budgets.
    if cause is not None and cause != state.cause:
        return _enter_from_scratch(cause, level1_available=level1_available)

    if state.level is EscalationLevel.NONE:
        return _enter_from_scratch(state.cause, level1_available=level1_available)

    if state.level is EscalationLevel.LEVEL_1:
        # Entry condition re-checked, not assumed to hold for the rest of the rung: a task
        # can lose its assignee mid-budget, and from that moment Level 1 has nothing left
        # to act on. The attempts already spent stay on record for the dossier (FR-061).
        if not level1_available:
            return replace(state, level=EscalationLevel.LEVEL_2, handovers=1)
        if state.attempts < cap:
            return replace(state, attempts=state.attempts + 1)
        # Budget spent. Hand over — and leave the counter where it is, because that number
        # is what the dossier reports as "tried this many times" (FR-061). The handover
        # itself is the first ask, so it is counted here rather than on the sweep after.
        return replace(state, level=EscalationLevel.LEVEL_2, handovers=1)

    if state.level is EscalationLevel.LEVEL_2:
        # Same shape as Level 1, one rung up: a budget of spaced asks, then hand on. The
        # symmetry is the point. Before this, an unanswered Leader was walked past on the
        # very next sweep — sixty seconds, less time than it takes an agent to read the
        # question — while an *unreachable* Leader got three tries over half an hour. The
        # rung that could still work was the one given no time at all.
        if state.handovers < handover_cap:
            return replace(state, handovers=state.handovers + 1)
        return replace(state, level=EscalationLevel.LEVEL_3)

    # Level 3. There is nothing above the patron, and the inbox item is already waiting on
    # them — further sweeps must leave the state completely alone rather than churn it.
    return state


def _enter_from_scratch(cause: str, *, level1_available: bool) -> EscalationState:
    """The rung a fresh problem starts on, entry condition checked first (FR-059a).

    ``attempts`` stays at zero on the Level-2 path, and that zero is load-bearing: it is
    what the Level-2 question and the Level-3 dossier read to tell *nobody was assigned*
    apart from *the assignee was called and never came*.
    """
    if not level1_available:
        return EscalationState(level=EscalationLevel.LEVEL_2, handovers=1, cause=cause)
    return EscalationState(level=EscalationLevel.LEVEL_1, attempts=1, cause=cause)


def backoff_seconds(attempt: int, *, base_seconds: int) -> int:
    """How long to wait before Level-1 attempt number ``attempt`` (1-based).

    Doubling, floored at ``base_seconds`` and capped at :data:`MAX_BACKOFF_SECONDS`.
    """
    if attempt <= 1:
        return base_seconds
    return int(min(base_seconds * 2 ** (attempt - 1), MAX_BACKOFF_SECONDS))
