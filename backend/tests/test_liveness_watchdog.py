"""LivenessWatchdog — the background clock that decays silent agents across workspaces (§10)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from armarius.application.use_cases.liveness import LivenessEngine
from armarius.application.use_cases.liveness_watchdog import LivenessWatchdog
from armarius.domain.entities.marius import Liveness, Marius
from armarius.domain.entities.workspace import Workspace
from armarius.domain.services.liveness_fsm import LivenessConfig
from tests.support.fakes import FakeLivenessProbe, FakeUowFactory

CFG = LivenessConfig()
T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


async def test_tick_all_advances_every_workspace() -> None:
    factory = FakeUowFactory()
    marius_ids = []
    for i in range(2):
        ws = Workspace(name=f"WS{i}", slug=f"ws{i}", owner_user_id=f"u{i}")
        factory.store.workspaces[ws.id] = ws
        m = Marius(
            workspace_id=ws.id, name=f"A{i}", role="r",
            liveness=Liveness.ONLINE, last_seen_at=T0,
        )
        factory.store.mariuses[m.id] = m
        marius_ids.append(m.id)

    engine = LivenessEngine(factory, FakeLivenessProbe(False), cfg=CFG)
    watchdog = LivenessWatchdog(factory, engine, interval_seconds=0.01)

    count = await watchdog.tick_all(now=T0 + CFG.idle_timeout + timedelta(seconds=1))

    assert count == 2
    # A silent agent past T1 is probed; the unanswered probe decays it out of ONLINE.
    for mid in marius_ids:
        assert factory.store.mariuses[mid].liveness == Liveness.CHECKING


async def test_background_loop_starts_and_stops_cleanly() -> None:
    factory = FakeUowFactory()
    ws = Workspace(name="WS", slug="ws", owner_user_id="u")
    factory.store.workspaces[ws.id] = ws
    engine = LivenessEngine(factory, FakeLivenessProbe(False), cfg=CFG)
    watchdog = LivenessWatchdog(factory, engine, interval_seconds=0.01)

    watchdog.start()
    watchdog.start()  # idempotent — no second task
    await asyncio.sleep(0.05)  # let a few ticks fire
    await watchdog.stop()  # cancels + awaits the unwind
    await watchdog.stop()  # a second stop is a no-op
