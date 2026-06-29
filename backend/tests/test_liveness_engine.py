"""LivenessEngine — decay → probe → OFFLINE, backoff doubling, signal reset (LLD §10)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from armarius.application.use_cases.liveness import LivenessEngine
from armarius.domain.entities.marius import Liveness, Marius
from armarius.domain.entities.workspace import Workspace
from armarius.domain.services.liveness_fsm import LivenessConfig
from tests.support.fakes import FakeLivenessProbe, FakeUowFactory

CFG = LivenessConfig()
T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _setup(marius: Marius) -> tuple[FakeUowFactory, Workspace, Marius]:
    factory = FakeUowFactory()
    ws = Workspace(name="Studio", slug="studio", owner_user_id="u1")
    factory.store.workspaces[ws.id] = ws
    marius.workspace_id = ws.id
    factory.store.mariuses[marius.id] = marius
    return factory, ws, marius


async def test_signal_resets_offline_agent_to_online() -> None:
    factory, ws, m = _setup(
        Marius(liveness=Liveness.OFFLINE, backoff_step=3, probe_attempts=2)
    )
    engine = LivenessEngine(factory, FakeLivenessProbe(False), cfg=CFG)

    await engine.record_signal(m.id, now=T0)

    m = factory.store.mariuses[m.id]
    assert m.liveness == Liveness.ONLINE
    assert m.last_seen_at == T0
    assert m.backoff_step == 0
    assert m.probe_attempts == 0
    assert m.next_probe_at is None


async def test_fresh_online_agent_is_not_probed() -> None:
    factory, ws, m = _setup(Marius(liveness=Liveness.ONLINE, last_seen_at=T0))
    probe = FakeLivenessProbe(False)
    engine = LivenessEngine(factory, probe, cfg=CFG)

    await engine.tick(workspace_id=ws.id, now=T0 + CFG.idle_timeout - timedelta(seconds=1))

    assert factory.store.mariuses[m.id].liveness == Liveness.ONLINE
    assert probe.calls == 0


async def test_probe_reply_restores_online() -> None:
    factory, ws, m = _setup(Marius(liveness=Liveness.ONLINE, last_seen_at=T0))
    probe = FakeLivenessProbe(True)  # the agent answers the probe
    engine = LivenessEngine(factory, probe, cfg=CFG)

    now = T0 + CFG.idle_timeout + timedelta(seconds=1)
    await engine.tick(workspace_id=ws.id, now=now)

    m = factory.store.mariuses[m.id]
    assert probe.calls == 1
    assert m.liveness == Liveness.ONLINE
    assert m.last_seen_at == now  # a reply is a fresh signal
    assert m.backoff_step == 0


async def test_three_spaced_misses_go_offline_with_first_wait_R() -> None:
    factory, ws, m = _setup(Marius(liveness=Liveness.ONLINE, last_seen_at=T0))
    engine = LivenessEngine(factory, FakeLivenessProbe(False), cfg=CFG)

    now = T0 + CFG.idle_timeout + timedelta(seconds=1)
    await engine.tick(workspace_id=ws.id, now=now)
    m = factory.store.mariuses[m.id]
    assert m.liveness == Liveness.CHECKING
    assert m.probe_attempts == 1

    for expected in (2, 3):
        now = m.next_probe_at
        await engine.tick(workspace_id=ws.id, now=now)
        m = factory.store.mariuses[m.id]
        if expected < 3:
            assert m.probe_attempts == expected

    assert m.liveness == Liveness.OFFLINE
    assert m.backoff_step == 1
    assert m.next_probe_at == now + CFG.retry_base  # first re-probe exactly R out


async def test_backoff_doubles_on_the_second_offline_cycle() -> None:
    # An agent already one OFFLINE cycle deep, its backoff just elapsed.
    factory, ws, m = _setup(
        Marius(liveness=Liveness.OFFLINE, backoff_step=1, next_probe_at=T0)
    )
    engine = LivenessEngine(factory, FakeLivenessProbe(False), cfg=CFG)

    now = T0
    await engine.tick(workspace_id=ws.id, now=now)  # re-enter CHECKING + probe #1
    m = factory.store.mariuses[m.id]
    for _ in range(2):  # probes #2 and #3
        now = m.next_probe_at
        await engine.tick(workspace_id=ws.id, now=now)
        m = factory.store.mariuses[m.id]

    assert m.liveness == Liveness.OFFLINE
    assert m.backoff_step == 2
    assert m.next_probe_at == now + CFG.retry_base * 2  # 2R on the second cycle


async def test_working_turn_is_not_probed() -> None:
    factory, ws, m = _setup(Marius(liveness=Liveness.ONLINE, last_seen_at=T0))
    probe = FakeLivenessProbe(False)
    engine = LivenessEngine(factory, probe, cfg=CFG)

    await engine.begin_turn(m.id, now=T0)
    assert factory.store.mariuses[m.id].liveness == Liveness.WORKING

    await engine.tick(workspace_id=ws.id, now=T0 + timedelta(minutes=5))

    assert factory.store.mariuses[m.id].liveness == Liveness.WORKING
    assert probe.calls == 0
