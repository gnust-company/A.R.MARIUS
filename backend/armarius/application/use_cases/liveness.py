"""LivenessEngine (LLD §10) — the application wrapper around the pure liveness FSM.

The pure core (`domain.services.liveness_fsm`) decides *what the state should become*;
this engine owns the **clock, the probe I/O and persistence**. There is no heartbeat
endpoint — when a Marius goes quiet past T1 the engine fires one bounded `LivenessProbe`
and folds the result back in. Any real contact funnels through `record_signal` (ONLINE +
reset). The DB transaction is never held open across the probe await.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from armarius.application.ports.liveness_probe import LivenessProbe
from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.marius import Marius
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


class LivenessEngine:
    def __init__(
        self,
        uow_factory: UowFactory,
        probe: LivenessProbe,
        *,
        clock=utcnow,
        cfg: LivenessConfig | None = None,
    ) -> None:
        self._uow = uow_factory
        self._probe = probe
        self._clock = clock
        self._cfg = cfg or LivenessConfig()

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
            decision = plan_tick(snapshot_of(marius), now, self._cfg)
            if decision.action != LivenessAction.PROBE:
                apply_state(marius, decision.state)
                marius.updated_at = now
                await uow.mariuses.update(marius)
                await uow.commit()
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
            result = on_probe_result(
                snapshot_of(marius), now, success=answered, cfg=self._cfg
            )
            apply_state(marius, result.state)
            marius.updated_at = now
            await uow.mariuses.update(marius)
            await uow.commit()
            return result.state
