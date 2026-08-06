"""Thang phục hồi ba mức — pure rules (FR-059, FR-060).

Three levels, in order, no skipping: the system re-wakes the same assignee (Mức 1), then
the Leader decides an explicit recovery action (Mức 2), then — and only then — the patron
is pulled in (Mức 3).

The ordering is the whole rule. A ladder that can skip a rung is a ladder that wakes the
patron for something the system had not even tried once, which is exactly how a person
learns to ignore it. And the Level-1 budget is per cause, not per lifetime: a task that
gets genuinely unstuck and later stalls for a different reason starts from zero, otherwise
one bad afternoon spends the task's entire budget forever.
"""

from __future__ import annotations

import pytest

from armarius.domain.services.escalation import (
    EscalationLevel,
    EscalationState,
    advance,
    backoff_seconds,
)

CAP = 3  # trần số lần tự gọi lại ở Mức 1


def fresh(cause: str = "mất động cơ đẩy") -> EscalationState:
    return EscalationState(level=EscalationLevel.NONE, attempts=0, cause=cause)


def climb(state: EscalationState, times: int, *, cap: int = CAP) -> EscalationState:
    for _ in range(times):
        state = advance(state, cap=cap, progressed=False, leader_acted=False)
    return state


# ── không nhảy cóc ──────────────────────────────────────────────────────────────


def test_the_first_rung_is_always_level_one() -> None:
    step = advance(fresh(), cap=CAP, progressed=False, leader_acted=False)
    assert step.level is EscalationLevel.LEVEL_1
    assert step.attempts == 1


def test_the_ladder_never_skips_a_rung() -> None:
    """Walk it one call at a time and record every level it passes through. Nothing may be
    missing from the sequence — a jump straight to the patron is the failure this exists
    to prevent."""
    seen = []
    state = fresh()
    for _ in range(CAP + 4):
        state = advance(state, cap=CAP, progressed=False, leader_acted=False)
        seen.append(state.level)

    assert seen[0] is EscalationLevel.LEVEL_1
    assert EscalationLevel.LEVEL_2 in seen, "không bao giờ chạm Mức 2"
    assert EscalationLevel.LEVEL_3 in seen, "không bao giờ chạm Mức 3"
    assert seen.index(EscalationLevel.LEVEL_2) < seen.index(EscalationLevel.LEVEL_3), (
        "leo lên người chủ trước khi Trưởng dự án kịp quyết"
    )
    # Monotonic: the level never drops while nothing improves.
    assert seen == sorted(seen), f"thang tụt xuống giữa chừng: {seen}"


# ── trần Mức 1 ──────────────────────────────────────────────────────────────────


def test_level_one_spends_exactly_the_budget_then_hands_over() -> None:
    state = climb(fresh(), CAP)
    assert state.level is EscalationLevel.LEVEL_1
    assert state.attempts == CAP, "chưa tiêu hết ngân sách đã bỏ cuộc"

    state = advance(state, cap=CAP, progressed=False, leader_acted=False)
    assert state.level is EscalationLevel.LEVEL_2, "hết ngân sách rồi vẫn tự thử tiếp"


def test_level_two_waits_for_the_leader_rather_than_retrying() -> None:
    """Mức 2 is a decision, not an attempt. The attempt counter must stop moving, or the
    dossier handed to the patron would claim the system tried things it never tried."""
    state = climb(fresh(), CAP + 1)
    assert state.level is EscalationLevel.LEVEL_2
    spent = state.attempts

    state = advance(state, cap=CAP, progressed=False, leader_acted=False)
    assert state.level is EscalationLevel.LEVEL_3
    assert state.attempts == spent, "số lần tự thử bị đội lên trong lúc chờ Trưởng dự án"


def test_the_top_of_the_ladder_stays_put() -> None:
    """There is nothing above the patron. Further sweeps must not churn the state — the
    inbox item is already waiting on them."""
    state = climb(fresh(), CAP + 5)
    assert state.level is EscalationLevel.LEVEL_3
    assert advance(state, cap=CAP, progressed=False, leader_acted=False) == state


def test_the_leader_acting_at_level_two_settles_it() -> None:
    """A recovery action the Leader decided is what Mức 2 was waiting for. Climbing to the
    patron anyway would tell them a decision was never made."""
    state = climb(fresh(), CAP + 1)
    assert state.level is EscalationLevel.LEVEL_2

    settled = advance(state, cap=CAP, progressed=False, leader_acted=True)
    assert settled.level is EscalationLevel.NONE
    assert settled.attempts == 0


# ── đặt lại bộ đếm khi có tiến triển thật (FR-060) ──────────────────────────────


def test_real_progress_resets_the_counter_to_zero() -> None:
    state = climb(fresh(), 2)
    assert state.attempts == 2

    moved = advance(state, cap=CAP, progressed=True, leader_acted=False)
    assert moved.level is EscalationLevel.NONE
    assert moved.attempts == 0, "đầu việc đã tiến mà bộ đếm vẫn giữ nợ cũ"


def test_progress_gives_back_the_whole_budget_not_one_attempt() -> None:
    """The difference matters on a task that stalls repeatedly: decrementing would let a
    task that recovers four times still hit the ceiling on its fifth stall, having never
    exhausted a single budget."""
    state = climb(fresh(), CAP)
    state = advance(state, cap=CAP, progressed=True, leader_acted=False)

    state = climb(state, CAP)
    assert state.level is EscalationLevel.LEVEL_1, "chưa gì đã leo lên Trưởng dự án"
    assert state.attempts == CAP


def test_progress_at_level_three_brings_it_all_the_way_down() -> None:
    state = climb(fresh(), CAP + 5)
    assert state.level is EscalationLevel.LEVEL_3

    moved = advance(state, cap=CAP, progressed=True, leader_acted=False)
    assert moved.level is EscalationLevel.NONE


def test_a_new_cause_starts_its_own_budget() -> None:
    """FR-060 counts per cause per task. A task that burned its budget on an offline
    assignee, got fixed, then later hit a missing artifact must get three fresh tries at
    the new problem."""
    state = climb(fresh("người phụ trách ngoại tuyến"), CAP)
    assert state.attempts == CAP

    state = advance(
        state, cap=CAP, progressed=False, leader_acted=False, cause="thành phẩm đã mất"
    )
    assert state.attempts == 1
    assert state.level is EscalationLevel.LEVEL_1
    assert state.cause == "thành phẩm đã mất"


# ── khoảng cách giãn dần ────────────────────────────────────────────────────────


def test_the_gap_between_attempts_grows() -> None:
    gaps = [backoff_seconds(n, base_seconds=60) for n in range(1, CAP + 1)]
    assert gaps == sorted(gaps) and len(set(gaps)) == len(gaps), (
        f"khoảng cách giữa các lần tự gọi lại không giãn ra: {gaps}"
    )
    assert gaps[0] >= 60


@pytest.mark.parametrize("attempt", [1, 2, 3, 8, 40])
def test_the_gap_is_capped_so_a_retry_never_becomes_a_never(attempt: int) -> None:
    """Doubling without a ceiling turns attempt 40 into a wait measured in centuries. The
    ladder is meant to give up and escalate, not to schedule a retry past the heat death of
    the project."""
    assert backoff_seconds(attempt, base_seconds=60) <= 2 * 60 * 60
