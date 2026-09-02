"""Wake policy — pure decision logic for self/liveness-wake (PROJECT_DESCRIPTION §4.3).

This encodes the status-policy table: given a task status and the outcome of the
last run, decide whether Armarius should fire a *self* wake, and of what kind.
Event-wakes (assign/mention/comment) are handled separately and always fire.

No global timer: this function is only consulted when a run finishes or a watchdog
classifies a dropped run. The decision is a function of (task status × run status).
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum

from armarius.domain.entities.run import RunStatus, WakeSource
from armarius.domain.entities.task import TERMINAL_STATUSES, TaskStatus
from armarius.domain.services.failure_kind import english, needs_a_person
from armarius.shared.errors import CodedError

# ── the two closed lists (FR-047, FR-048) ────────────────────────────────────
#
# "When and only when" is the whole point: an agent that can be woken for anything is an
# agent nobody can reason about, and FR-049 exists precisely to stop project-wide noise
# from reaching someone who has nothing waiting on them.
#
# These lists are not documentation. `may_wake` below is called at both places a wake
# leaves the system — the task-scoped engine and the project-scoped Leader channel — and a
# cause outside the recipient's list is refused there and written down (FR-048a). They
# spent one whole phase as data nothing read, and drifted: the cadence sweep's cause sat in
# the worker list while the only code that fires it wakes the Leader.

#: Causes that may reach **either** role, because the recipient is named rather than
#: deduced from a role. Being called by name is the one wake where the sender, not the
#: system, decides who it is for — and a Leader can be asked a question in a task thread
#: exactly as a teammate can.
EITHER_ROLE_WAKE_CAUSES: frozenset[WakeSource] = frozenset({WakeSource.MENTION})

#: Causes that may wake a **Leader** (FR-047).
LEADER_WAKE_CAUSES: frozenset[WakeSource] = (
    frozenset(
        {
            WakeSource.LEADER_CHAT,  # the patron wrote or asked
            WakeSource.PATRON_DECISION,  # plan approved/changed, output accepted/refused,
            #                              phase changed or a new batch opened
            WakeSource.WORKER_HANDBACK,  # a worker handed work back or said it is stuck
            WakeSource.TASK_IN_REVIEW,  # something is waiting to be judged
            WakeSource.TASK_DONE,  # something closed — go pass the word
            WakeSource.BRIEF_REVIEW,  # three rejections: look at the brief, not the worker
            WakeSource.PROJECT_READY,  # roster complete → go plan
            # The orchestration sweep found real snags on the board (FR-047 last cause,
            # FR-052). It lived in the worker list and never belonged there: the sweep
            # reads the whole board and hands what it found to the one role that can act
            # on a board, and the code that fires it has only ever called the Leader.
            WakeSource.IDLE_REMINDER,
        }
    )
    | EITHER_ROLE_WAKE_CAUSES
)

#: Causes that may wake a **worker** (FR-048).
WORKER_WAKE_CAUSES: frozenset[WakeSource] = (
    frozenset(
        {
            WakeSource.ASSIGNMENT,  # given a task
            WakeSource.COMMENT,  # new comment on a task it owns
            WakeSource.APPROVAL_REJECTED,  # its output came back for rework (FR-040)
            WakeSource.DEPENDENCY_CLEARED,  # what it was waiting on is done (FR-031, SC-009)
            WakeSource.REQUIREMENT_CHANGED,  # the patron rewrote the job under it (FR-070a)
        }
    )
    | EITHER_ROLE_WAKE_CAUSES
)

#: Causes that belong to neither list because they are the system talking to itself: the
#: self-wake policy resuming its own dropped work, the safety net calling a task back, and
#: the manual "wake now" button. Whoever holds the work is who they reach, so they are
#: allowed for both roles.
SYSTEM_WAKE_CAUSES: frozenset[WakeSource] = frozenset(
    {WakeSource.CONTINUATION, WakeSource.NUDGE, WakeSource.ON_DEMAND}
)


class WakeCauseRefused(CodedError):
    """A wake was asked for with a cause the recipient's role may not be woken for.

    Raised only where a human is waiting on the answer — the manual wake button. The
    system's own callers get a refusal they can ignore instead, so that one mis-booked
    wake never takes down the action that happened to book it.
    """


class WakeRole(StrEnum):
    """Which hat the recipient wears for the wake being sent.

    Not a property of the agent: one agent can wear both at once. A Leader that took a task
    on itself is the Leader of the project *and* the worker on that task, and both sets of
    causes may legitimately reach it — see `may_wake`.
    """

    LEADER = "leader"
    WORKER = "worker"


def may_wake(source: WakeSource, *, roles: Collection[WakeRole]) -> bool:
    """FR-048a — may this cause wake somebody wearing these hats?

    The allowance is the **union** of the hats worn, never a single guess at "what this
    agent is". Wearing no hat at all still allows the system's own causes and a wake that
    names its recipient; everything else is refused, because a cause that reaches somebody
    with no part in the work is precisely the project-wide noise FR-049 forbids.
    """
    allowed = set(SYSTEM_WAKE_CAUSES | EITHER_ROLE_WAKE_CAUSES)
    if WakeRole.LEADER in roles:
        allowed |= LEADER_WAKE_CAUSES
    if WakeRole.WORKER in roles:
        allowed |= WORKER_WAKE_CAUSES
    return source in allowed


@dataclass(frozen=True)
class WakeDecision:
    should_wake: bool
    source: WakeSource | None = None
    #: Why, for the log — free text, read by people debugging this table.
    reason: str = ""
    #: Why, for the agent — a code from the closed list in ``wake_reason``. The log line
    #: and the wake packet are two different readers; one sentence cannot serve both
    #: (Constitution VII), and only this one crosses the wire.
    code: str = ""
    escalate_to_human: bool = False


def decide_self_wake(
    *,
    task_status: TaskStatus,
    run_status: RunStatus,
    has_next_action: bool,
    has_block_reason: bool,
    continuation_attempt: int,
    max_attempts: int,
    failure: str = "",
) -> WakeDecision:
    """Decide the follow-up wake after a run ends (or a watchdog fires).

    Mirrors the §4.3 table. The guiding rule: only wake when "the ball is in the
    agent's court". When someone else owes the next move, stay silent and let their
    event wake the agent.

    ``failure`` is the machine's own verdict on *why* the run could not go on, when it had
    one. It is checked before anything else that could book a wake, because the budgets
    below all assume the same thing about a retry — that it might land — and that
    assumption is exactly what some endings falsify (FR-032).
    """
    if task_status in TERMINAL_STATUSES:
        return WakeDecision(False, reason="terminal status")

    # A wall, not a hiccup: waiting on a person, and no number of attempts gets past it
    # (FR-007c, FR-014f, FR-032). Checked ahead of every budget below rather than inside
    # them, so that not one attempt is spent — an ending that fails identically every time
    # turns a budget into a delay, and the person who could fix it in a minute is told
    # only once the delay runs out.
    if needs_a_person(failure):
        return WakeDecision(
            False,
            reason=english(failure),
            code=failure,
            escalate_to_human=True,
        )

    # Review / waiting on a human reviewer — the ball is in their court.
    if task_status == TaskStatus.IN_REVIEW:
        return WakeDecision(False, reason="awaiting human review")

    # Freshly assigned but not started — the assignment event already woke it.
    if task_status == TaskStatus.TODO:
        return WakeDecision(False, reason="assignment is the event-wake")

    # Blocked / backlog: silent if there's a clear reason; nudge once if it's in limbo.
    if task_status in (TaskStatus.BLOCKED, TaskStatus.BACKLOG):
        if has_block_reason:
            return WakeDecision(False, reason="blocked with a clear reason; wait for unblock")
        if continuation_attempt >= max_attempts:
            return WakeDecision(
                False, reason="nudge budget exhausted", escalate_to_human=True
            )
        return WakeDecision(
            True,
            source=WakeSource.NUDGE,
            reason="in limbo without a reason; ask for an update",
            code="no_reason_recorded",
        )

    if task_status == TaskStatus.IN_PROGRESS:
        # Run died/timed out — recovery is handled by the watchdog → continuation.
        if run_status in (RunStatus.FAILED, RunStatus.TIMED_OUT, RunStatus.STOPPED):
            if continuation_attempt >= max_attempts:
                return WakeDecision(
                    False, reason="continuation budget exhausted", escalate_to_human=True
                )
            return WakeDecision(
                True,
                source=WakeSource.CONTINUATION,
                reason="run dropped; resume the task session",
                code="run_dropped",
            )
        # Completed cleanly with unfinished work — resume.
        if run_status == RunStatus.COMPLETED and has_next_action:
            if continuation_attempt >= max_attempts:
                return WakeDecision(
                    False, reason="continuation budget exhausted", escalate_to_human=True
                )
            return WakeDecision(
                True,
                source=WakeSource.CONTINUATION,
                reason="work left unfinished (next_action set); continue",
                code="work_unfinished",
            )
        # Completed, nothing recorded, status unchanged — bounded nudge then escalate.
        if run_status == RunStatus.COMPLETED and not has_next_action:
            if continuation_attempt >= max_attempts:
                return WakeDecision(
                    False, reason="nudge budget exhausted", escalate_to_human=True
                )
            return WakeDecision(
                True,
                source=WakeSource.NUDGE,
                reason="stopped without recording progress",
                code="stopped_without_progress",
            )
        # Still running — leave it; the watchdog guards liveness.
        return WakeDecision(False, reason="run still in flight")

    return WakeDecision(False, reason="no policy match")
