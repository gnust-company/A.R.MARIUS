from __future__ import annotations

from armarius.domain.entities.run import RunStatus, WakeSource
from armarius.domain.entities.task import TaskStatus
from armarius.domain.services.wake_policy import (
    LEADER_WAKE_CAUSES,
    SYSTEM_WAKE_CAUSES,
    WORKER_WAKE_CAUSES,
    decide_self_wake,
)


def _decide(**kw):
    base = dict(
        task_status=TaskStatus.IN_PROGRESS,
        run_status=RunStatus.COMPLETED,
        has_next_action=False,
        has_block_reason=False,
        continuation_attempt=0,
        max_attempts=3,
    )
    base.update(kw)
    return decide_self_wake(**base)


def test_in_review_is_silent() -> None:
    assert _decide(task_status=TaskStatus.IN_REVIEW).should_wake is False


def test_todo_is_silent() -> None:
    assert _decide(task_status=TaskStatus.TODO).should_wake is False


def test_completed_with_next_action_continues() -> None:
    d = _decide(has_next_action=True)
    assert d.should_wake is True
    assert d.source == WakeSource.CONTINUATION


def test_dropped_run_continues() -> None:
    d = _decide(run_status=RunStatus.TIMED_OUT)
    assert d.should_wake is True
    assert d.source == WakeSource.CONTINUATION


def test_completed_no_progress_nudges() -> None:
    d = _decide(has_next_action=False)
    assert d.should_wake is True
    assert d.source == WakeSource.NUDGE


def test_blocked_with_reason_is_silent() -> None:
    d = _decide(task_status=TaskStatus.BLOCKED, has_block_reason=True)
    assert d.should_wake is False


def test_blocked_without_reason_nudges() -> None:
    d = _decide(task_status=TaskStatus.BLOCKED, has_block_reason=False)
    assert d.should_wake is True
    assert d.source == WakeSource.NUDGE


def test_budget_exhausted_escalates() -> None:
    d = _decide(has_next_action=True, continuation_attempt=3, max_attempts=3)
    assert d.should_wake is False
    assert d.escalate_to_human is True


def test_terminal_status_is_silent() -> None:
    assert _decide(task_status=TaskStatus.DONE).should_wake is False
    assert _decide(task_status=TaskStatus.CANCELLED).should_wake is False


# ── the closed lists are closed (spec 001 FR-047, FR-048) ──────────────────────


def test_every_wake_cause_is_assigned_to_somebody() -> None:
    """A cause nobody claimed is a cause that can wake anyone — which is the opposite of
    what "when and only when" means. Adding a new one without deciding who it may wake
    fails here rather than quietly widening both lists."""
    claimed = LEADER_WAKE_CAUSES | WORKER_WAKE_CAUSES | SYSTEM_WAKE_CAUSES
    unclaimed = set(WakeSource) - claimed
    assert not unclaimed, f"cớ chưa ai nhận: {sorted(str(s) for s in unclaimed)}"


def test_the_two_lists_do_not_overlap() -> None:
    """Overlap would mean a cause reads as both 'the Leader owes something' and 'a worker
    owes something', which is exactly the ambiguity FR-049 removes."""
    assert not (LEADER_WAKE_CAUSES & WORKER_WAKE_CAUSES)


def test_a_worker_is_not_on_the_hook_for_reviewing_or_deciding() -> None:
    """FR-049 in the concrete: a task reaching review, or the patron deciding something,
    is not the worker's business — it has nothing left to do until someone answers."""
    assert WakeSource.TASK_IN_REVIEW not in WORKER_WAKE_CAUSES
    assert WakeSource.PATRON_DECISION not in WORKER_WAKE_CAUSES
    assert WakeSource.TASK_DONE not in WORKER_WAKE_CAUSES


def test_being_unblocked_is_the_workers_business_and_nobody_elses() -> None:
    """FR-048 names it in the worker's list, and only there: the blocker clearing is a
    call to *start*, and the only person who can start is whoever holds the task."""
    assert WakeSource.DEPENDENCY_CLEARED in WORKER_WAKE_CAUSES
    assert WakeSource.DEPENDENCY_CLEARED not in LEADER_WAKE_CAUSES
