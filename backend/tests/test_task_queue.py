"""Xếp hàng khi nhiều đầu việc cùng cần một thợ (FR-067).

Three keys in order: priority, then deadline, then age. They answer different questions —
priority is what somebody *decided*, a deadline is what the outside world will do regardless
of anyone's opinion, and age is the tiebreaker that keeps the queue honest.

The ageing is what turns the rule from a sort into a promise. A plain priority-first sort
starves the bottom: on a busy project there is always another *high* task, so a *low* one
waits forever while the board cheerfully reports it as queued. These tests exist mostly to
hold that line.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from armarius.domain.services.push_reason_rules import QueueCandidate, queue_order

NOW = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)


def task(
    name: str,
    *,
    priority: str = "medium",
    due: datetime | None = None,
    age_days: float = 0.0,
) -> QueueCandidate:
    return QueueCandidate(
        task_id=uuid4(),
        identifier=name,
        priority=priority,
        due_date=due,
        created_at=NOW - timedelta(days=age_days),
    )


def order(*candidates: QueueCandidate) -> list[str]:
    return [c.identifier for c in queue_order(candidates, now=NOW)]


# ── ba khoá, đúng thứ tự ────────────────────────────────────────────────────────


def test_priority_comes_first() -> None:
    assert order(
        task("A-low", priority="low"),
        task("A-critical", priority="critical"),
        task("A-medium", priority="medium"),
        task("A-high", priority="high"),
    ) == ["A-critical", "A-high", "A-medium", "A-low"]


def test_a_deadline_breaks_a_priority_tie() -> None:
    assert order(
        task("B-later", priority="high", due=NOW + timedelta(days=5)),
        task("B-sooner", priority="high", due=NOW + timedelta(days=1)),
    ) == ["B-sooner", "B-later"]


def test_a_task_with_no_deadline_waits_behind_one_that_has_one() -> None:
    """A deadline is a fact about the world; its absence is not a claim of urgency."""
    assert order(
        task("C-none", priority="high"),
        task("C-dated", priority="high", due=NOW + timedelta(days=30)),
    ) == ["C-dated", "C-none"]


def test_age_breaks_a_tie_when_priority_and_deadline_match() -> None:
    same_due = NOW + timedelta(days=2)
    assert order(
        task("D-new", priority="high", due=same_due, age_days=0),
        task("D-old", priority="high", due=same_due, age_days=0.5),
    ) == ["D-old", "D-new"]


# ── chống bỏ đói ────────────────────────────────────────────────────────────────


def test_a_low_task_that_has_waited_long_enough_overtakes_a_fresh_high_one() -> None:
    """The whole point. Without this, "we will get to it" is a lie the queue tells forever:
    a busy project always has another *high* task, and the bottom of the list is never
    reached."""
    assert order(
        task("E-high-today", priority="high", age_days=0),
        task("E-low-for-days", priority="low", age_days=4),
    ) == ["E-low-for-days", "E-high-today"]


def test_priority_still_means_something_day_to_day() -> None:
    """Ageing must not be so aggressive that priority stops working. Filed the same
    morning, urgent work still goes first — otherwise the queue is just a FIFO wearing a
    priority field."""
    assert order(
        task("F-low", priority="low", age_days=0),
        task("F-critical", priority="critical", age_days=0),
    ) == ["F-critical", "F-low"]

    # And a few hours of waiting is not enough to overturn two whole priority steps.
    assert order(
        task("G-critical", priority="critical", age_days=0),
        task("G-low", priority="low", age_days=0.5),
    ) == ["G-critical", "G-low"]


def test_nothing_waits_forever() -> None:
    """Stated as the property rather than as one example: whatever the queue looks like,
    the oldest low-priority item eventually reaches the front."""
    starved = task("H-forgotten", priority="low", age_days=10)
    flood = [task(f"H-urgent-{i}", priority="high", age_days=0) for i in range(20)]

    assert order(starved, *flood)[0] == "H-forgotten"


# ── ổn định ─────────────────────────────────────────────────────────────────────


def test_the_same_board_always_produces_the_same_order() -> None:
    """An unstable queue makes every "why did it pick that one?" unanswerable."""
    board = [
        task("I-a", priority="high", age_days=1),
        task("I-b", priority="high", age_days=1),
        task("I-c", priority="high", age_days=1),
    ]
    assert order(*board) == order(*reversed(board)) == ["I-a", "I-b", "I-c"]


def test_an_unknown_priority_is_treated_as_middling_not_as_urgent() -> None:
    """Junk in a priority field must never win. Failing towards the front would let a typo
    jump the whole queue."""
    assert order(
        task("J-junk", priority="rất gấp"),
        task("J-high", priority="high"),
    ) == ["J-high", "J-junk"]


# ── nhánh nào chạy tiếp trong lúc chờ người chủ (FR-066) ────────────────────────
#
# Stated as "what must wait" rather than "what may run", so the default is *keep going*.
# Written the other way round, any branch the closure forgot to mention would quietly
# stop — and a project that halts because one question went unanswered on a Friday is
# exactly the failure this requirement exists to prevent.

from armarius.domain.services.push_reason_rules import (  # noqa: E402
    blocked_behind,
    keeps_running,
)

A, B, C, D, PARKED = (uuid4() for _ in range(5))


def test_a_branch_that_does_not_touch_the_question_carries_on() -> None:
    assert keeps_running([A, B], waiting_on=[PARKED], edges=[(B, PARKED)]) == [A]


def test_the_whole_chain_behind_the_question_waits_not_just_the_first_step() -> None:
    """A task waiting on a task waiting on the parked decision is every bit as parked.
    Stopping one level down would leave the middle of a chain looking runnable."""
    edges = [(B, PARKED), (C, B), (D, C)]
    assert blocked_behind([PARKED], edges) == {B, C, D}
    assert keeps_running([A, B, C, D], waiting_on=[PARKED], edges=edges) == [A]


def test_nothing_is_parked_when_nothing_is_waiting() -> None:
    assert keeps_running([A, B, C], waiting_on=[], edges=[(B, A)]) == [A, B, C]


def test_a_dependency_cycle_does_not_hang_the_walk() -> None:
    """Cycles should not exist, and the dependency service rejects them — but this walk
    runs on stored data written over months by several code paths, and a rule that loops
    forever on bad input takes the whole board with it."""
    edges = [(B, PARKED), (C, B), (B, C)]
    assert blocked_behind([PARKED], edges) == {B, C}


def test_the_order_of_what_keeps_running_is_left_to_the_caller() -> None:
    """Membership and ordering are separate questions; mixing them would hide one of the
    two rules inside the other."""
    assert keeps_running([C, A, B], waiting_on=[PARKED], edges=[(B, PARKED)]) == [C, A]
