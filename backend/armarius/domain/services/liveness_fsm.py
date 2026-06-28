"""Pure liveness state machine (LLD §10, ARCHITECTURE §5) — no I/O.

This is the decision core the application-layer `LivenessEngine` (Sprint 2) wraps: the
engine owns the clock, the adapter probe and persistence/events; this module owns *what
the state should become*. Recency + probe model, no heartbeat endpoint:

    ONLINE ──quiet past T1──► CHECKING ──probe──► (reply) ONLINE
                                   │
                              3 misses (spaced ~T2)
                                   ▼
    OFFLINE ──wait R, then 2R, 4R… (capped)──► CHECKING ──► …

Any signal (a probe reply, /agent/me, a task reply, an enroll reply) resets to ONLINE and
zeroes the probe/backoff bookkeeping (`on_signal`). A WORKING turn that overruns
`hung_after` becomes HUNG.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum

from armarius.domain.entities.marius import Liveness, Marius


@dataclass(frozen=True)
class LivenessConfig:
    idle_timeout: timedelta = timedelta(seconds=90)  # T1 — no signal ⇒ start probing
    probe_window: timedelta = timedelta(seconds=30)  # T2 — gap between probe attempts
    max_probe_attempts: int = 3  # misses before OFFLINE
    retry_base: timedelta = timedelta(seconds=60)  # R — first OFFLINE re-probe wait
    retry_max: timedelta = timedelta(minutes=30)  # cap on the doubling backoff
    retry_factor: float = 2.0  # R → 2R → 4R …
    hung_after: timedelta = timedelta(minutes=20)  # WORKING turn watchdog


class LivenessAction(StrEnum):
    """The side-effect the engine should perform after a pure decision."""

    NONE = "none"
    PROBE = "probe"  # fire one bounded adapter probe, then call `on_probe_result`


@dataclass(frozen=True)
class LivenessState:
    """The liveness bookkeeping fields, isolated from the rest of Marius."""

    liveness: Liveness = Liveness.OFFLINE
    last_seen_at: datetime | None = None
    probe_attempts: int = 0
    backoff_step: int = 0
    next_probe_at: datetime | None = None
    offline_since: datetime | None = None
    turn_started_at: datetime | None = None


@dataclass(frozen=True)
class LivenessDecision:
    state: LivenessState
    action: LivenessAction = LivenessAction.NONE


def retry_interval(backoff_step: int, cfg: LivenessConfig | None = None) -> timedelta:
    """OFFLINE re-probe wait: step 0 ⇒ R, 1 ⇒ 2R, 2 ⇒ 4R … capped at retry_max.

    Computed in seconds and capped BEFORE building the timedelta so a large
    backoff_step can't overflow `timedelta * float`.
    """
    cfg = cfg or LivenessConfig()
    raw_seconds = cfg.retry_base.total_seconds() * (cfg.retry_factor**backoff_step)
    return timedelta(seconds=min(raw_seconds, cfg.retry_max.total_seconds()))


def on_signal(now: datetime) -> LivenessState:
    """Any contact ⇒ ONLINE and a full reset of the probe/backoff timers (LLD §10)."""
    return LivenessState(
        liveness=Liveness.ONLINE,
        last_seen_at=now,
        probe_attempts=0,
        backoff_step=0,
        next_probe_at=None,
        offline_since=None,
        turn_started_at=None,
    )


def begin_turn(state: LivenessState, now: datetime) -> LivenessState:
    """The wake engine starts a turn ⇒ WORKING (a turn counts as liveness)."""
    return replace(state, liveness=Liveness.WORKING, turn_started_at=now)


def plan_tick(
    state: LivenessState, now: datetime, cfg: LivenessConfig | None = None
) -> LivenessDecision:
    """Advance one Marius off the clock (mirrors LLD §10 `tick`, minus the probe I/O).

    Returns the next state plus whether a probe is now due. The engine fires the probe
    (when `action == PROBE`), then feeds the outcome back via `on_probe_result`.
    """
    cfg = cfg or LivenessConfig()
    s = state

    # A WORKING turn is itself a signal — never probe it; only watch for a hang.
    if s.liveness == Liveness.WORKING:
        if s.turn_started_at is not None and now - s.turn_started_at > cfg.hung_after:
            return LivenessDecision(replace(s, liveness=Liveness.HUNG))
        return LivenessDecision(s)

    # ONLINE gone quiet past T1 → enter CHECKING and schedule the first probe now.
    if (
        s.liveness == Liveness.ONLINE
        and s.last_seen_at is not None
        and now - s.last_seen_at > cfg.idle_timeout
    ):
        s = replace(s, liveness=Liveness.CHECKING, probe_attempts=0, next_probe_at=now)

    # OFFLINE waiting out its backoff → re-enter CHECKING when the interval elapses.
    if (
        s.liveness == Liveness.OFFLINE
        and s.next_probe_at is not None
        and now >= s.next_probe_at
    ):
        s = replace(s, liveness=Liveness.CHECKING, probe_attempts=0, next_probe_at=now)

    # CHECKING and a probe is due → tell the engine to fire one.
    if (
        s.liveness == Liveness.CHECKING
        and s.next_probe_at is not None
        and now >= s.next_probe_at
    ):
        return LivenessDecision(s, LivenessAction.PROBE)

    return LivenessDecision(s)


def register_probe(
    state: LivenessState, now: datetime, cfg: LivenessConfig | None = None
) -> LivenessState:
    """Bookkeeping just BEFORE firing a probe: count the attempt, space the next by T2.

    Spacing here (not after the result) guarantees the 3 attempts are ~T2 apart and never
    burst within a single tick (LLD §10 probe-spacing fix).
    """
    cfg = cfg or LivenessConfig()
    return replace(
        state,
        probe_attempts=state.probe_attempts + 1,
        next_probe_at=now + cfg.probe_window,
    )


def go_offline(
    state: LivenessState, now: datetime, cfg: LivenessConfig | None = None
) -> LivenessState:
    """Schedule the re-probe with the CURRENT backoff_step (so the first wait is R), THEN
    bump the step — first OFFLINE wait exactly R, next 2R, 4R … (LLD §10 backoff fix)."""
    cfg = cfg or LivenessConfig()
    return replace(
        state,
        liveness=Liveness.OFFLINE,
        offline_since=now,
        next_probe_at=now + retry_interval(state.backoff_step, cfg),
        backoff_step=state.backoff_step + 1,
    )


def on_probe_result(
    state: LivenessState,
    now: datetime,
    *,
    success: bool,
    cfg: LivenessConfig | None = None,
) -> LivenessDecision:
    """Fold a probe outcome back in: a reply resets to ONLINE; the 3rd miss goes OFFLINE."""
    cfg = cfg or LivenessConfig()
    if success:
        return LivenessDecision(on_signal(now))
    if state.probe_attempts >= cfg.max_probe_attempts:
        return LivenessDecision(go_offline(state, now, cfg))
    return LivenessDecision(state)  # more attempts remain; wait out the T2 gap


# ── Marius <-> LivenessState adapters (still pure; used by the Sprint-2 engine) ──────
def snapshot_of(marius: Marius) -> LivenessState:
    return LivenessState(
        liveness=marius.liveness,
        last_seen_at=marius.last_seen_at,
        probe_attempts=marius.probe_attempts,
        backoff_step=marius.backoff_step,
        next_probe_at=marius.next_probe_at,
        offline_since=marius.offline_since,
        turn_started_at=marius.turn_started_at,
    )


def apply_state(marius: Marius, state: LivenessState) -> None:
    marius.liveness = state.liveness
    marius.last_seen_at = state.last_seen_at
    marius.probe_attempts = state.probe_attempts
    marius.backoff_step = state.backoff_step
    marius.next_probe_at = state.next_probe_at
    marius.offline_since = state.offline_since
    marius.turn_started_at = state.turn_started_at
