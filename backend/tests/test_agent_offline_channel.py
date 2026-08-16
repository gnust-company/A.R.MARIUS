"""T169 — an agent going offline says so on the workspace channel (FR-080a, Hiến pháp IV).

``marius.online`` already existed: /agent/me publishes it when an agent speaks up after
silence. Nothing published the opposite edge, so the directory's status dot could only ever
move one way — and the direction it could not move (an agent that died) is the one a patron
needs to see. The dot stayed green until the page was reloaded.

The payload is the other half of the subject. These events carry an id and nothing else, on
purpose: principle 1 of ``contracts/push-events.md`` makes an event a *signal* to re-read,
never the state itself. A test pins that, because "just put the status in the payload" is
the shortcut that always looks reasonable in review and quietly makes a missed event
unrecoverable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from armarius.application.ports.workspace_trace import (
    EVENT_MARIUS_OFFLINE,
    WorkspaceTracePublisher,
)
from armarius.application.use_cases.liveness import LivenessEngine
from armarius.domain.entities.marius import Liveness, Marius
from armarius.domain.entities.workspace import Workspace
from armarius.domain.services.liveness_fsm import LivenessConfig
from armarius.infrastructure.events.topic_bus import TopicEventBus
from armarius.infrastructure.events.workspace_trace import ControlBusWorkspaceTrace
from tests.support.fakes import FakeLivenessProbe, FakeUowFactory

CFG = LivenessConfig()
T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


class ExplodingTrace(WorkspaceTracePublisher):
    """A channel that always fails — stands in for a bus that is down mid-tick."""

    async def publish(
        self, workspace_id: UUID, type: str, data: dict[str, object]
    ) -> None:
        raise RuntimeError("kênh hỏng")


class RecordingFallout:
    """The rescue side: remembers which agents it was told had vanished."""

    def __init__(self) -> None:
        self.seen: list[UUID] = []

    async def agent_went_offline(self, marius_id: UUID, *, now: datetime) -> None:
        self.seen.append(marius_id)


def _setup(marius: Marius) -> tuple[FakeUowFactory, Workspace, Marius]:
    factory = FakeUowFactory()
    ws = Workspace(name="Studio", slug="studio", owner_user_id="u1")
    factory.store.workspaces[ws.id] = ws
    marius.workspace_id = ws.id
    factory.store.mariuses[marius.id] = marius
    return factory, ws, marius


def _offline_events(bus: TopicEventBus, workspace_id) -> list[dict]:
    return [
        event.data
        for event in bus.backlog(f"ws:{workspace_id}")
        if event.type == EVENT_MARIUS_OFFLINE
    ]


async def _drive_to_offline(engine: LivenessEngine, ws_id, marius: Marius, store) -> None:
    """Three spaced probe misses — the only way an agent legitimately crosses over."""
    now = T0 + CFG.idle_timeout + timedelta(seconds=1)
    await engine.tick(workspace_id=ws_id, now=now)
    for _ in range(2):
        now = store.mariuses[marius.id].next_probe_at
        await engine.tick(workspace_id=ws_id, now=now)


async def test_an_agent_that_dies_says_so_without_anyone_asking() -> None:
    factory, ws, m = _setup(Marius(liveness=Liveness.ONLINE, last_seen_at=T0))
    bus = TopicEventBus()
    engine = LivenessEngine(
        factory,
        FakeLivenessProbe(False),
        cfg=CFG,
        workspace_trace=ControlBusWorkspaceTrace(bus),
    )

    await _drive_to_offline(engine, ws.id, m, factory.store)

    assert factory.store.mariuses[m.id].liveness == Liveness.OFFLINE
    events = _offline_events(bus, ws.id)
    assert len(events) == 1, "chấm sống/chết chỉ đổi được khi có tin báo"
    assert events[0]["marius_id"] == str(m.id)


async def test_the_event_carries_no_liveness_value() -> None:
    """A signal, not a source of truth (contracts/push-events.md, nguyên tắc 1).

    If the state rides in the payload, a listener that misses the event — replay window
    overflow, a reconnect gap — shows a wrong value with no way to notice it is wrong.
    """
    factory, ws, m = _setup(Marius(liveness=Liveness.ONLINE, last_seen_at=T0))
    bus = TopicEventBus()
    engine = LivenessEngine(
        factory,
        FakeLivenessProbe(False),
        cfg=CFG,
        workspace_trace=ControlBusWorkspaceTrace(bus),
    )

    await _drive_to_offline(engine, ws.id, m, factory.store)

    payload = _offline_events(bus, ws.id)[0]
    assert set(payload) == {"marius_id"}


async def test_a_tick_that_changes_nothing_says_nothing() -> None:
    """Announced on the crossing, not on the state.

    Worth stating exactly what "the crossing" turns out to mean, because it is not once
    per outage. A dead agent does not sit in OFFLINE: every time its backoff elapses,
    ``plan_tick`` walks it back to CHECKING and three fresh misses put it back — so one
    long outage re-crosses once per backoff cycle (R, 2R, 4R …), and each re-crossing
    announces again.

    That is harmless *because* the payload carries no state: the listener re-reads and
    finds the same OFFLINE it already had. It would not be harmless if the event were the
    source of truth, which is the second reason principle 1 is worth obeying here.

    What must not happen is a message per tick. The ticks in between — probe attempt 2 of
    3, a backoff still running — change nothing and say nothing.
    """
    factory, ws, m = _setup(Marius(liveness=Liveness.ONLINE, last_seen_at=T0))
    bus = TopicEventBus()
    engine = LivenessEngine(
        factory,
        FakeLivenessProbe(False),
        cfg=CFG,
        workspace_trace=ControlBusWorkspaceTrace(bus),
    )

    await _drive_to_offline(engine, ws.id, m, factory.store)
    assert len(_offline_events(bus, ws.id)) == 1

    # Two more ticks that land mid-cycle: back to CHECKING, then attempt 2 of 3. Neither
    # reaches OFFLINE, so neither may speak.
    for _ in range(2):
        now = factory.store.mariuses[m.id].next_probe_at
        await engine.tick(workspace_id=ws.id, now=now)

    assert factory.store.mariuses[m.id].liveness == Liveness.CHECKING
    assert len(_offline_events(bus, ws.id)) == 1


async def test_a_broken_channel_does_not_cost_the_rescue() -> None:
    """Ordering, not politeness: the tasks the vanished agent was holding cannot be
    rescued later, a lost notification costs one stale dot. Rescue runs first, and a
    publish that throws must not take the clock down with it either."""
    factory, ws, m = _setup(Marius(liveness=Liveness.ONLINE, last_seen_at=T0))
    fallout = RecordingFallout()
    engine = LivenessEngine(
        factory,
        FakeLivenessProbe(False),
        cfg=CFG,
        fallout=fallout,
        workspace_trace=ExplodingTrace(),
    )

    await _drive_to_offline(engine, ws.id, m, factory.store)

    assert fallout.seen == [m.id], "tin báo hỏng đã nuốt mất phần cứu đầu việc"
    assert factory.store.mariuses[m.id].liveness == Liveness.OFFLINE


async def test_an_unwired_channel_changes_nothing() -> None:
    """Every other caller builds the engine without a channel; they must keep working."""
    factory, ws, m = _setup(Marius(liveness=Liveness.ONLINE, last_seen_at=T0))
    fallout = RecordingFallout()
    engine = LivenessEngine(factory, FakeLivenessProbe(False), cfg=CFG, fallout=fallout)

    await _drive_to_offline(engine, ws.id, m, factory.store)

    assert factory.store.mariuses[m.id].liveness == Liveness.OFFLINE
    assert fallout.seen == [m.id]
