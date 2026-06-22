"""Wake policy — pure decision logic for self/liveness-wake (PROJECT_DESCRIPTION §4.3).

This encodes the status-policy table: given a task status and the outcome of the
last run, decide whether Armarius should fire a *self* wake, and of what kind.
Event-wakes (assign/mention/comment) are handled separately and always fire.

No global timer: this function is only consulted when a run finishes or a watchdog
classifies a dropped run. The decision is a function of (task status × run status).
"""

from __future__ import annotations

from dataclasses import dataclass

from armarius.domain.entities.run import RunStatus, WakeSource
from armarius.domain.entities.task import TERMINAL_STATUSES, TaskStatus


@dataclass(frozen=True)
class WakeDecision:
    should_wake: bool
    source: WakeSource | None = None
    reason: str = ""
    escalate_to_human: bool = False


def decide_self_wake(
    *,
    task_status: TaskStatus,
    run_status: RunStatus,
    has_next_action: bool,
    has_block_reason: bool,
    continuation_attempt: int,
    max_attempts: int,
) -> WakeDecision:
    """Decide the follow-up wake after a run ends (or a watchdog fires).

    Mirrors the §4.3 table. The guiding rule: only wake when "the ball is in the
    agent's court". When someone else owes the next move, stay silent and let their
    event wake the agent.
    """
    if task_status in TERMINAL_STATUSES:
        return WakeDecision(False, reason="terminal status")

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
            )
        # Still running — leave it; the watchdog guards liveness.
        return WakeDecision(False, reason="run still in flight")

    return WakeDecision(False, reason="no policy match")
