"""The three snags, and the rhythm that stretches and tightens (spec 001 FR-052, FR-055).

Everything here is a pure function driven off a **fixed** clock. A cadence rule tested
against the real clock is a rule tested once, at whatever moment the suite happened to
run; against a fixed clock every boundary is reachable — the exact moment a deadline mark
is crossed, the sweep that finds nothing.

The spec is specific about all three snags, and the specificity is the point: "the board
looks stuck" is not a rule anybody can implement twice the same way. There used to be a
fourth, *silent*, and its removal is guarded here too: this cadence must not go back to
asking whether anything is about to touch a task.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from armarius.domain.entities.task import TaskStatus
from armarius.domain.services.orchestration_cadence import (
    CadenceState,
    Snag,
    SnagKind,
    TaskSnapshot,
    find_snags,
    next_interval_seconds,
    tightest_mark_crossed,
    within_hourly_cap,
)

NOW = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)
MARKS = (24, 12, 6, 1)


def _snapshot(**kw) -> TaskSnapshot:
    base = dict(
        task_id=uuid4(),
        identifier="P-1",
        title="Kết xuất báo cáo",
        status=TaskStatus.IN_PROGRESS,
        due_date=None,
        awaiting_leader_decision=False,
    )
    base.update(kw)
    return TaskSnapshot(**base)  # type: ignore[arg-type]


def _kinds(snags: list[Snag]) -> set[SnagKind]:
    return {s.kind for s in snags}


# ── mắc kẹt và chờ quyết định ────────────────────────────────────────────────────

async def test_a_blocked_task_is_a_snag_that_names_itself() -> None:
    task = _snapshot(status=TaskStatus.BLOCKED)

    snags = find_snags([task], now=NOW, due_soon_hours=MARKS)

    assert _kinds(snags) == {SnagKind.BLOCKED}
    # FR-054: the packet must name what to look at, so the snag has to carry the identity
    # of the task rather than a bare count.
    assert snags[0].identifier == "P-1"
    assert "P-1" in snags[0].detail


async def test_a_task_waiting_on_the_leader_is_a_snag() -> None:
    task = _snapshot(status=TaskStatus.IN_REVIEW, awaiting_leader_decision=True)

    assert _kinds(find_snags([task], now=NOW, due_soon_hours=MARKS)) == {
        SnagKind.AWAITING_LEADER
    }


async def test_a_task_nobody_is_touching_is_not_this_cadence_s_business() -> None:
    """The retired *silent* snag, guarded so it cannot come back (FR-052).

    A task can sit untouched for a month and still be none of this loop's concern: whether
    anything is about to touch it is the stall sweep's question (FR-057), answered from the
    drive (FR-056), which this cadence does not read and must not guess at. It once did
    guess, and counted a queued-but-not-yet-running wake — and a retry against an offline
    assignee, which FR-063 says explicitly must not count — as silence.

    The snapshot carries no activity timestamp and no live-run flag at all, so the rule has
    nothing to relapse with. This test fails at import if either field returns.
    """
    untouched = _snapshot(status=TaskStatus.IN_PROGRESS)

    assert find_snags([untouched], now=NOW, due_soon_hours=MARKS) == []


async def test_closed_tasks_never_snag() -> None:
    closed = [
        _snapshot(status=TaskStatus.DONE, due_date=NOW - timedelta(days=30)),
        _snapshot(status=TaskStatus.CANCELLED, due_date=NOW - timedelta(days=30)),
    ]

    assert find_snags(closed, now=NOW, due_soon_hours=MARKS) == []


# ── sắp trễ ──────────────────────────────────────────────────────────────────────

async def test_a_task_without_a_deadline_is_never_due_soon() -> None:
    """FR-052 says this in as many words, and it matters: most tasks have no deadline.

    A rule that treated *no deadline* as *infinitely overdue* — or as due now — would put
    every untimed task on every sweep and drown the real ones.
    """
    task = _snapshot(due_date=None)

    assert find_snags([task], now=NOW, due_soon_hours=MARKS) == []


async def test_crossing_a_deadline_mark_is_a_snag_naming_the_mark() -> None:
    task = _snapshot(due_date=NOW + timedelta(hours=5))

    snags = find_snags([task], now=NOW, due_soon_hours=MARKS)

    assert _kinds(snags) == {SnagKind.DUE_SOON}
    # 5 hours left has crossed the 24, 12 and 6 hour marks; the tightest one is the news.
    assert "6" in snags[0].detail


async def test_a_mark_already_reported_does_not_fire_again() -> None:
    """FR-052 says *vừa chạm* — just crossed. Not *is under*.

    Without this the same task would be reported on every sweep for the whole day before
    its deadline, and the hourly cap would spend itself on news the Leader already has.
    """
    task = _snapshot(due_date=NOW + timedelta(hours=5))
    already = {task.task_id: 6}

    snags = find_snags(
        [task],
        now=NOW,
        due_soon_hours=MARKS,
        reported_marks=already,
    )

    assert snags == []


async def test_a_tighter_mark_fires_even_when_a_looser_one_was_reported() -> None:
    task = _snapshot(due_date=NOW + timedelta(minutes=30))
    already = {task.task_id: 6}

    snags = find_snags(
        [task],
        now=NOW,
        due_soon_hours=MARKS,
        reported_marks=already,
    )

    assert _kinds(snags) == {SnagKind.DUE_SOON}
    assert "1" in snags[0].detail


async def test_an_overdue_task_counts_as_having_crossed_the_tightest_mark() -> None:
    assert tightest_mark_crossed(
        due_date=NOW - timedelta(hours=2), now=NOW, marks=MARKS
    ) == 1


async def test_a_deadline_further_out_than_every_mark_has_crossed_nothing() -> None:
    assert tightest_mark_crossed(
        due_date=NOW + timedelta(days=3), now=NOW, marks=MARKS
    ) is None


# ── several at once ──────────────────────────────────────────────────────────────

async def test_three_tasks_in_three_predicaments_produce_three_named_snags() -> None:
    """Kịch bản 5 bước 2, at the level of the rule.

    One sweep, three snags, each naming its own task — that is what FR-054 asks the packet
    to carry, and the rule has to hand it up in that shape.
    """
    blocked = _snapshot(identifier="P-1", status=TaskStatus.BLOCKED)
    due = _snapshot(identifier="P-2", due_date=NOW + timedelta(hours=5))
    waiting = _snapshot(
        identifier="P-3", status=TaskStatus.IN_REVIEW, awaiting_leader_decision=True
    )

    snags = find_snags([blocked, due, waiting], now=NOW, due_soon_hours=MARKS)

    assert _kinds(snags) == {SnagKind.BLOCKED, SnagKind.DUE_SOON, SnagKind.AWAITING_LEADER}
    assert {s.identifier for s in snags} == {"P-1", "P-2", "P-3"}


async def test_a_healthy_board_produces_no_snags_at_all() -> None:
    """FR-053's precondition. A sweep over a project that is running well finds nothing,
    and *nothing* is what stops the Leader being woken.

    None of these three has moved recently, and after FR-052 lost its *silent* snag that
    is exactly as it should be: quiet is not a snag, and a board of quiet open work must
    cost the Leader nothing.
    """
    healthy = [
        _snapshot(identifier="P-1"),
        _snapshot(identifier="P-2", status=TaskStatus.TODO),
        _snapshot(identifier="P-3", status=TaskStatus.IN_REVIEW),
    ]

    assert find_snags(healthy, now=NOW, due_soon_hours=MARKS) == []


# ── giãn và làm dày nhịp (FR-055) ────────────────────────────────────────────────

async def test_a_smooth_project_stretches_the_gap_between_sweeps() -> None:
    base = 900
    stretched = [
        next_interval_seconds(base, state=CadenceState(quiet_streak=n, found_snags=False))
        for n in (0, 1, 2, 3)
    ]

    assert stretched == sorted(stretched)
    # The first quiet sweep buys nothing: an operator who configured fifteen minutes gets
    # fifteen minutes, not thirty because the board was clean the first time anyone looked.
    assert stretched[0] == base
    assert stretched[-1] > stretched[0]


async def test_the_stretch_is_capped_so_a_quiet_project_is_never_abandoned() -> None:
    """The widest gap the spec allows is two hours (Giả định, chốt 2026-07-30).

    Pinned against the default fifteen-minute cadence, because that is the number the
    assumption is written in. A cap expressed only as a multiple can drift away from the
    figure it was chosen to hit without anything noticing.
    """
    base = 900  # the default cadence: fifteen minutes
    very_quiet = next_interval_seconds(
        base, state=CadenceState(quiet_streak=50, found_snags=False)
    )

    assert very_quiet == 2 * 60 * 60


async def test_a_slower_cadence_still_stops_at_two_hours() -> None:
    """The two hours are a real ceiling, not a by-product of the default cadence.

    A multiple alone reads correctly at fifteen minutes and absurdly at sixty: eight times
    an hourly cadence is eight hours, and nothing in the spec contemplates a project going
    unlooked-at for a working day.
    """
    hourly = next_interval_seconds(
        3600, state=CadenceState(quiet_streak=50, found_snags=False)
    )

    assert hourly == 2 * 60 * 60


async def test_a_fast_cadence_is_not_stretched_to_the_absolute_ceiling() -> None:
    """…and the ceiling must not swallow the other half of the rule.

    An operator who sets one minute is saying *watch this closely*. Stretching that to two
    hours because two hours is "the maximum" would answer them with the opposite.
    """
    minutely = next_interval_seconds(
        60, state=CadenceState(quiet_streak=50, found_snags=False)
    )

    assert minutely == 60 * 8


async def test_a_project_slower_than_the_ceiling_keeps_its_own_cadence() -> None:
    """The ceiling caps the *stretch*; it never speeds a project up.

    An operator who asked for a six-hour rhythm has to get six hours. Clamping to two
    would turn a ceiling into a schedule and sweep three times as often as they asked.
    """
    slow = 6 * 60 * 60
    assert next_interval_seconds(
        slow, state=CadenceState(quiet_streak=50, found_snags=False)
    ) == slow
    assert next_interval_seconds(
        slow, state=CadenceState(quiet_streak=0, found_snags=False)
    ) == slow


async def test_a_sweep_that_found_snags_tightens_the_rhythm_below_base() -> None:
    base = 900
    dense = next_interval_seconds(base, state=CadenceState(quiet_streak=9, found_snags=True))

    assert dense < base
    # A long quiet streak must not survive a sweep that found something: the moment work
    # backs up, the slack earned while it was smooth is irrelevant.
    assert dense == next_interval_seconds(
        base, state=CadenceState(quiet_streak=0, found_snags=True)
    )


async def test_the_rhythm_never_collapses_into_a_busy_loop() -> None:
    dense = next_interval_seconds(10, state=CadenceState(quiet_streak=0, found_snags=True))

    assert dense >= 60


# ── trần số lần gọi trong một giờ (FR-055) ───────────────────────────────────────

async def test_the_hourly_cap_lets_wakes_through_until_it_is_reached() -> None:
    assert within_hourly_cap(wakes_in_last_hour=0, cap=4) is True
    assert within_hourly_cap(wakes_in_last_hour=3, cap=4) is True


async def test_the_hourly_cap_blocks_the_wake_once_it_is_reached() -> None:
    assert within_hourly_cap(wakes_in_last_hour=4, cap=4) is False
    assert within_hourly_cap(wakes_in_last_hour=9, cap=4) is False


async def test_a_cap_of_zero_or_less_means_uncapped_not_silenced() -> None:
    """A misconfigured cap must not be able to mute the orchestrator entirely.

    Zero reads as "no ceiling configured", never as "never wake anyone" — the failure mode
    of the second reading is a project nobody drives, which is exactly what this feature
    exists to prevent.
    """
    assert within_hourly_cap(wakes_in_last_hour=99, cap=0) is True
