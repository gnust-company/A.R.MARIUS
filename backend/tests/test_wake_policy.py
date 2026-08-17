from __future__ import annotations

from armarius.domain.entities.run import RunStatus, WakeSource
from armarius.domain.entities.task import TaskStatus
from armarius.domain.services.wake_policy import (
    EITHER_ROLE_WAKE_CAUSES,
    LEADER_WAKE_CAUSES,
    SYSTEM_WAKE_CAUSES,
    WORKER_WAKE_CAUSES,
    WakeRole,
    decide_self_wake,
    may_wake,
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


def test_the_two_lists_overlap_only_where_the_sender_names_the_recipient() -> None:
    """Overlap means a cause reads as both 'the Leader owes something' and 'a worker owes
    something' — the ambiguity FR-049 removes — so it is allowed only for the causes that
    carry their own recipient. Being called by name is the one wake the sender addresses,
    and a Leader can be asked a question in a task thread exactly as a teammate can."""
    assert LEADER_WAKE_CAUSES & WORKER_WAKE_CAUSES == EITHER_ROLE_WAKE_CAUSES
    assert WakeSource.MENTION in EITHER_ROLE_WAKE_CAUSES


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


def test_the_sweeps_findings_go_to_the_role_that_can_act_on_a_board() -> None:
    """The cause sat in the worker's list for a whole phase while the only code that fires
    it called the Leader. Reading a whole board and deciding what to do about it is what a
    Leader is for; a worker holds one task and cannot act on the rest."""
    assert WakeSource.IDLE_REMINDER in LEADER_WAKE_CAUSES
    assert WakeSource.IDLE_REMINDER not in WORKER_WAKE_CAUSES


# ── the lists decide who may be woken (FR-048a) ────────────────────────────────


def test_a_cause_from_the_other_role_is_not_allowed() -> None:
    assert not may_wake(WakeSource.TASK_IN_REVIEW, roles={WakeRole.WORKER})
    assert not may_wake(WakeSource.ASSIGNMENT, roles={WakeRole.LEADER})


def test_wearing_both_hats_allows_both_lists() -> None:
    """A Leader that took a task on itself is the Leader of the project *and* the worker on
    that task. Picking one hat would refuse half of what legitimately reaches it."""
    both = {WakeRole.LEADER, WakeRole.WORKER}
    assert may_wake(WakeSource.ASSIGNMENT, roles=both)
    assert may_wake(WakeSource.TASK_IN_REVIEW, roles=both)


def test_the_systems_own_causes_reach_whoever_holds_the_work() -> None:
    """Resuming a dropped turn, the safety net calling back, the manual button: the
    recipient is whoever was already on the work, so no role can refuse them."""
    for source in SYSTEM_WAKE_CAUSES:
        assert may_wake(source, roles={WakeRole.LEADER})
        assert may_wake(source, roles={WakeRole.WORKER})
        assert may_wake(source, roles=set())


def test_somebody_with_no_part_in_the_work_is_only_reachable_by_name() -> None:
    """FR-049 at its sharpest: an agent that neither holds the task nor leads the project
    has nothing waiting on it, so only a wake that names it explicitly gets through."""
    assert may_wake(WakeSource.MENTION, roles=set())
    assert not may_wake(WakeSource.COMMENT, roles=set())
    assert not may_wake(WakeSource.PATRON_DECISION, roles=set())
