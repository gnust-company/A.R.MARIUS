from __future__ import annotations

from armarius.domain.entities.run import RunStatus, WakeSource
from armarius.domain.entities.task import TaskStatus
from armarius.domain.services.wake_policy import decide_self_wake


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
