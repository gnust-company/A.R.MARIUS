"""Pure liveness FSM (LLD §10): recency + probe, backoff R→2R→4R, signal-reset."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from armarius.domain.entities.marius import Liveness
from armarius.domain.services.liveness_fsm import (
    LivenessAction,
    LivenessConfig,
    LivenessState,
    begin_turn,
    go_offline,
    on_probe_result,
    on_signal,
    plan_tick,
    register_probe,
    retry_interval,
)

CFG = LivenessConfig()
T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _online(last_seen: datetime) -> LivenessState:
    return LivenessState(liveness=Liveness.ONLINE, last_seen_at=last_seen)


# ── signal reset ─────────────────────────────────────────────────────────────


def test_on_signal_returns_online_and_resets() -> None:
    s = on_signal(T0)
    assert s.liveness == Liveness.ONLINE
    assert s.last_seen_at == T0
    assert s.probe_attempts == 0
    assert s.backoff_step == 0
    assert s.next_probe_at is None


def test_signal_while_offline_snaps_back_online() -> None:
    offline = LivenessState(liveness=Liveness.OFFLINE, backoff_step=3)
    s = on_signal(T0)  # any contact funnels through on_signal
    assert offline.liveness == Liveness.OFFLINE  # input untouched (pure)
    assert s.liveness == Liveness.ONLINE
    assert s.backoff_step == 0


# ── ONLINE → CHECKING after T1 ───────────────────────────────────────────────


def test_online_stays_online_within_idle_timeout() -> None:
    now = T0 + CFG.idle_timeout - timedelta(seconds=1)
    decision = plan_tick(_online(T0), now, CFG)
    assert decision.state.liveness == Liveness.ONLINE
    assert decision.action == LivenessAction.NONE


def test_online_enters_checking_and_probes_after_t1() -> None:
    now = T0 + CFG.idle_timeout + timedelta(seconds=1)
    decision = plan_tick(_online(T0), now, CFG)
    assert decision.state.liveness == Liveness.CHECKING
    assert decision.state.probe_attempts == 0
    assert decision.state.next_probe_at == now
    assert decision.action == LivenessAction.PROBE


# ── probe attempts spacing + 3 misses → OFFLINE ──────────────────────────────


def test_register_probe_counts_and_spaces_by_t2() -> None:
    checking = LivenessState(liveness=Liveness.CHECKING, next_probe_at=T0)
    s = register_probe(checking, T0, CFG)
    assert s.probe_attempts == 1
    assert s.next_probe_at == T0 + CFG.probe_window  # next attempt a full T2 later


def test_probe_failure_below_limit_keeps_checking() -> None:
    s = LivenessState(liveness=Liveness.CHECKING, probe_attempts=1)
    decision = on_probe_result(s, T0, success=False, cfg=CFG)
    assert decision.state.liveness == Liveness.CHECKING
    assert decision.action == LivenessAction.NONE


def test_third_probe_failure_goes_offline_with_first_wait_R() -> None:
    s = LivenessState(liveness=Liveness.CHECKING, probe_attempts=3, backoff_step=0)
    decision = on_probe_result(s, T0, success=False, cfg=CFG)
    assert decision.state.liveness == Liveness.OFFLINE
    assert decision.state.offline_since == T0
    # first OFFLINE wait is exactly R (not 2R)
    assert decision.state.next_probe_at == T0 + CFG.retry_base
    assert decision.state.backoff_step == 1


def test_probe_success_mid_cycle_resets_to_online() -> None:
    s = LivenessState(liveness=Liveness.CHECKING, probe_attempts=2, backoff_step=1)
    decision = on_probe_result(s, T0, success=True, cfg=CFG)
    assert decision.state.liveness == Liveness.ONLINE
    assert decision.state.probe_attempts == 0
    assert decision.state.backoff_step == 0
    assert decision.action == LivenessAction.NONE


# ── backoff doubling + cap ───────────────────────────────────────────────────


def test_retry_interval_doubles_then_caps() -> None:
    assert retry_interval(0, CFG) == CFG.retry_base  # R
    assert retry_interval(1, CFG) == CFG.retry_base * 2  # 2R
    assert retry_interval(2, CFG) == CFG.retry_base * 4  # 4R
    assert retry_interval(99, CFG) == CFG.retry_max  # capped


def test_go_offline_uses_current_step_then_increments() -> None:
    step1 = go_offline(LivenessState(liveness=Liveness.CHECKING, backoff_step=1), T0, CFG)
    assert step1.next_probe_at == T0 + CFG.retry_base * 2  # 2R for step 1
    assert step1.backoff_step == 2


def test_offline_backoff_elapsed_reenters_checking() -> None:
    due = T0
    s = LivenessState(liveness=Liveness.OFFLINE, next_probe_at=due, backoff_step=1)
    decision = plan_tick(s, due, CFG)
    assert decision.state.liveness == Liveness.CHECKING
    assert decision.action == LivenessAction.PROBE


def test_offline_waits_out_its_interval() -> None:
    s = LivenessState(liveness=Liveness.OFFLINE, next_probe_at=T0 + timedelta(seconds=10))
    decision = plan_tick(s, T0, CFG)  # not yet due
    assert decision.state.liveness == Liveness.OFFLINE
    assert decision.action == LivenessAction.NONE


# ── WORKING turn watchdog → HUNG ─────────────────────────────────────────────


def test_working_turn_within_budget_is_not_hung() -> None:
    s = begin_turn(LivenessState(), T0)
    assert s.liveness == Liveness.WORKING
    decision = plan_tick(s, T0 + timedelta(minutes=5), CFG)
    assert decision.state.liveness == Liveness.WORKING
    assert decision.action == LivenessAction.NONE


def test_working_turn_over_budget_becomes_hung() -> None:
    s = begin_turn(LivenessState(), T0)
    decision = plan_tick(s, T0 + CFG.hung_after + timedelta(seconds=1), CFG)
    assert decision.state.liveness == Liveness.HUNG


def test_hung_is_recoverable_via_gateway_probe() -> None:
    """A stalled turn → HUNG, but HUNG now schedules an immediate re-probe (no longer a
    dead-end). The next tick re-enters CHECKING and asks the engine to probe, so a healthy
    gateway flips the agent back ONLINE instead of stranding it forever (#82 liveness fix)."""
    working = begin_turn(LivenessState(), T0)
    hung = plan_tick(working, T0 + CFG.hung_after + timedelta(seconds=1), CFG).state
    assert hung.liveness == Liveness.HUNG
    assert hung.next_probe_at is not None  # recovery probe scheduled immediately

    decision = plan_tick(hung, hung.next_probe_at, CFG)
    assert decision.state.liveness == Liveness.CHECKING
    assert decision.action == LivenessAction.PROBE

    recovered = on_probe_result(
        decision.state, hung.next_probe_at, success=True, cfg=CFG
    ).state
    assert recovered.liveness == Liveness.ONLINE


# ── full decay sequence (engine-style walk) ──────────────────────────────────


def test_full_decay_three_spaced_probes_then_offline() -> None:
    """ONLINE → quiet → CHECKING → 3 probes spaced by T2 → OFFLINE after wait R."""
    state = _online(T0)
    now = T0 + CFG.idle_timeout + timedelta(seconds=1)

    # tick 1: enter CHECKING + first probe due
    d = plan_tick(state, now, CFG)
    assert d.action == LivenessAction.PROBE
    state = register_probe(d.state, now, CFG)
    assert state.probe_attempts == 1
    state = on_probe_result(state, now, success=False, cfg=CFG).state
    assert state.liveness == Liveness.CHECKING

    # ticks 2 & 3: each probe is due exactly T2 later, never bursts
    for expected in (2, 3):
        now = state.next_probe_at
        d = plan_tick(state, now, CFG)
        assert d.action == LivenessAction.PROBE
        state = register_probe(d.state, now, CFG)
        assert state.probe_attempts == expected
        d = on_probe_result(state, now, success=False, cfg=CFG)
        state = d.state

    assert state.liveness == Liveness.OFFLINE
    assert state.next_probe_at == now + CFG.retry_base  # first re-probe one R out
    assert state.backoff_step == 1
