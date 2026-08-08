"""LivenessEngine (LLD §10) — the application wrapper around the pure liveness FSM.

The pure core (`domain.services.liveness_fsm`) decides *what the state should become*;
this engine owns the **clock, the probe I/O and persistence**. There is no heartbeat
endpoint — when a Marius goes quiet past T1 the engine fires one bounded `LivenessProbe`
and folds the result back in. Any real contact funnels through `record_signal` (ONLINE +
reset). The DB transaction is never held open across the probe await.

One consequence is handled here rather than left to whoever notices: **being declared
offline has fallout** (FR-064). An agent that is gone is not going to finish what it was
holding, and a task left pointing at it looks assigned and is not. The engine does not
know what to do about that — it knows *when*, which is the part nobody else can see, so
it announces the edge and hands it to a collaborator.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from armarius.application.ports.liveness_probe import LivenessProbe
from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.marius import Liveness, Marius
from armarius.domain.services.liveness_fsm import (
    LivenessAction,
    LivenessConfig,
    LivenessState,
    apply_state,
    begin_turn,
    on_probe_result,
    on_signal,
    plan_tick,
    register_probe,
    snapshot_of,
)
from armarius.shared.clock import utcnow
from armarius.shared.logging import get_logger

logger = get_logger(__name__)


class OfflineFallout(Protocol):
    """What happens to a workspace when one of its agents is declared gone (FR-064).

    Kept behind a port so the liveness engine stays about liveness. The engine owns the
    only thing genuinely hard to observe from outside — the *moment* an agent crosses
    into offline — and nothing about what that should cost the board.
    """

    async def agent_went_offline(self, marius_id: UUID, *, now: datetime) -> None: ...


class LivenessEngine:
    def __init__(
        self,
        uow_factory: UowFactory,
        probe: LivenessProbe,
        *,
        clock: Callable[[], datetime] = utcnow,
        cfg: LivenessConfig | None = None,
        fallout: OfflineFallout | None = None,
    ) -> None:
        self._uow = uow_factory
        self._probe = probe
        self._clock = clock
        self._cfg = cfg or LivenessConfig()
        self._fallout = fallout

    def attach_fallout(self, fallout: OfflineFallout) -> None:
        """Wire the fallout handler after construction (composition root only).

        The handler needs the inbox, the Leader chat and the drive writer; the Leader
        chat needs *this* engine to know whether the Leader can take a turn. A real
        cycle, and this is the smallest honest cut through it: one setter, called once,
        in the one place that builds everything. The alternative — a half-built engine
        handed to the chat service — moves the same cycle to runtime, where it fails
        as an attribute error on a live wake instead of on the first line of boot.
        """
        self._fallout = fallout

    # ── signals (any contact resets to ONLINE) ──────────────────────────────────
    async def record_signal(
        self, marius_id: UUID, now: datetime | None = None
    ) -> Marius:
        """Fold any contact (a probe reply, /agent/me, a task reply) in as a signal."""
        now = now or self._clock()
        async with self._uow() as uow:
            marius = await uow.mariuses.get(marius_id)
            if marius is None:
                raise LookupError("marius not found")
            apply_state(marius, on_signal(now))
            marius.updated_at = now
            await uow.mariuses.update(marius)
            await uow.commit()
            return marius

    async def begin_turn(self, marius_id: UUID, now: datetime | None = None) -> Marius:
        """The wake engine starts a turn → WORKING (a turn counts as liveness)."""
        now = now or self._clock()
        async with self._uow() as uow:
            marius = await uow.mariuses.get(marius_id)
            if marius is None:
                raise LookupError("marius not found")
            apply_state(marius, begin_turn(snapshot_of(marius), now))
            marius.updated_at = now
            await uow.mariuses.update(marius)
            await uow.commit()
            return marius

    # ── the clock tick ──────────────────────────────────────────────────────────
    async def tick(
        self, *, workspace_id: UUID, now: datetime | None = None
    ) -> Sequence[LivenessState]:
        """Advance every Marius in a workspace off the clock; fire probes as decided."""
        now = now or self._clock()
        async with self._uow() as uow:
            mariuses = list(await uow.mariuses.list_by_workspace(workspace_id))
        return [await self.advance(m.id, now) for m in mariuses]

    async def advance(self, marius_id: UUID, now: datetime) -> LivenessState:
        """Advance one Marius: plan → (maybe) probe → fold the result back in."""
        async with self._uow() as uow:
            marius = await uow.mariuses.get(marius_id)
            if marius is None:
                raise LookupError("marius not found")
            was = marius.liveness
            decision = plan_tick(snapshot_of(marius), now, self._cfg)
            if decision.action != LivenessAction.PROBE:
                apply_state(marius, decision.state)
                marius.updated_at = now
                await uow.mariuses.update(marius)
                await uow.commit()
                settled = marius.liveness
                if _crossed_into_offline(was, settled):
                    await self._announce_offline(marius_id, now)
                return decision.state
            # A probe is due — count the attempt + space the next BEFORE firing.
            registered = register_probe(decision.state, now, self._cfg)
            apply_state(marius, registered)
            marius.updated_at = now
            await uow.mariuses.update(marius)
            await uow.commit()
            probe_target = marius

        answered = await self._probe.probe(probe_target)  # bounded I/O, no tx held

        async with self._uow() as uow:
            marius = await uow.mariuses.get(marius_id)
            if marius is None:  # pragma: no cover — vanished mid-probe
                raise LookupError("marius not found")
            before_fold = marius.liveness
            result = on_probe_result(
                snapshot_of(marius), now, success=answered, cfg=self._cfg
            )
            apply_state(marius, result.state)
            marius.updated_at = now
            await uow.mariuses.update(marius)
            await uow.commit()
            crossed = _crossed_into_offline(before_fold, marius.liveness)
        # Outside the transaction: the fallout writes tasks and wakes people, and doing
        # that inside the liveness write would hold a lock across another service's I/O.
        if crossed:
            await self._announce_offline(marius_id, now)
        return result.state

    async def _announce_offline(self, marius_id: UUID, now: datetime) -> None:
        """Hand the crossing to the fallout handler, and never let it break the clock.

        A failure here is logged and swallowed on purpose: this loop advances every agent in
        every workspace, and one project's recovery going wrong must not stop the rest of
        them from being measured at all.
        """
        if self._fallout is None:
            return
        try:
            await self._fallout.agent_went_offline(marius_id, now=now)
        except Exception:  # pragma: no cover - the clock must keep ticking
            logger.exception("offline fallout failed for marius %s", marius_id)


def _crossed_into_offline(before: Liveness, after: Liveness) -> bool:
    """True only on the *edge* into offline.

    The edge, not the state: an agent that has been offline for a week is offline on every
    tick, and acting on the state would re-block the same tasks and re-notify the same
    Leader every thirty seconds until somebody muted the channel.
    """
    return after is Liveness.OFFLINE and before is not Liveness.OFFLINE
