"""T167 — a run's lifecycle on the workspace channel (FR-080, Hiến pháp IV).

The agent detail screen watches an *agent*. Before this, the two channels a run announced
itself on were keyed by run and by task, so that screen had nothing to listen to and asked
the server again every fifteen seconds instead.

What matters is not that *an* event fires — it is that **every** transition fires one. A
run's status is moved from five places, and a screen that hears four of them shows a run
frozen at whatever the missing one left behind. So there is a test per path, plus one that
pins the payload: the workspace channel is held open for a whole session, and principle 4
of ``contracts/push-events.md`` keeps content off it.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from armarius.application.ports.workspace_trace import EVENT_RUN_STATE_CHANGED
from armarius.application.use_cases.liveness import LivenessEngine
from armarius.application.use_cases.liveness_watchdog import LivenessWatchdog
from armarius.application.use_cases.mariuses import MariusService
from armarius.application.use_cases.runs import RunQueryService
from armarius.application.use_cases.tasks import TaskService
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.entities.run import Run, RunStatus, WakeSource
from armarius.domain.entities.task import TaskStatus
from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus
from armarius.infrastructure.events.topic_bus import TopicEventBus
from armarius.infrastructure.events.workspace_trace import ControlBusWorkspaceTrace
from tests.support.fakes import FakeLivenessProbe
from tests.support.projects import force_phase

NOW = datetime(2026, 8, 11, 9, 0, 0, tzinfo=UTC)
SUSPECT, GRACE = 600, 120

_TERMINAL = (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.TIMED_OUT, RunStatus.STOPPED)


def _run_events(bus: TopicEventBus, workspace_id) -> list[dict]:
    """Every run-lifecycle event on one workspace's channel, oldest first."""
    return [
        event.data
        for event in bus.backlog(f"ws:{workspace_id}")
        if event.type == EVENT_RUN_STATE_CHANGED
    ]


async def _world(uow_factory, bus: TopicEventBus):
    """A project past the plan gate, one agent, one assignable task."""
    workspaces = WorkspaceService(uow_factory)
    ws = await workspaces.create_workspace("WS")
    project = await workspaces.create_project(ws.id, "P")
    await force_phase(uow_factory, project.id)  # FR-003 — the run channel is the subject
    registry = InMemoryAdapterRegistry()
    registry.register(EchoAdapter(step_delay=0.0))
    wake = WakeEngine(
        uow_factory,
        registry,
        InMemoryEventBus(),
        run_timeout_seconds=30,
        workspace_trace=ControlBusWorkspaceTrace(bus),
    )
    alice = await MariusService(uow_factory).register(
        workspace_id=ws.id,
        name="Alice",
        role="Backend",
        skills=[],
        adapter_type="echo",
        adapter_config={},
    )
    tasks = TaskService(uow_factory, wake)
    task = await tasks.create(
        project_id=project.id,
        title="Dựng cổng đăng nhập",
        description="Dựng cổng đăng nhập bằng thư điện tử và mật khẩu cho ứng dụng.",
    )
    return ws, project, alice, task, wake, tasks


async def _settle(runs: RunQueryService, task_id, attempts: int = 400) -> list:
    """Wait until every run on the task is terminal and the count has stopped moving."""
    stable, last = 0, -1
    for _ in range(attempts):
        items = await runs.list_by_task(task_id)
        if items and all(r.status in _TERMINAL for r in items) and len(items) == last:
            stable += 1
            if stable >= 8:
                return items
        else:
            stable = 0
        last = len(items)
        await asyncio.sleep(0.02)
    return await runs.list_by_task(task_id)


async def test_a_run_says_so_when_it_opens_starts_and_ends(uow_factory) -> None:
    bus = TopicEventBus()
    ws, _project, alice, task, wake, tasks = await _world(uow_factory, bus)

    await tasks.assign(task.id, alice.id)
    await _settle(RunQueryService(uow_factory), task.id)
    await wake.drain()

    statuses = [event["status"] for event in _run_events(bus, ws.id)]
    # Queued when the row is opened, running when the turn starts, then a terminal status.
    # Without all three the screen either misses the run entirely or leaves it spinning.
    assert statuses[:2] == [str(RunStatus.QUEUED), str(RunStatus.RUNNING)]
    assert statuses[-1] in {str(s) for s in _TERMINAL}


async def test_the_event_names_the_agent_it_belongs_to(uow_factory) -> None:
    """The channel carries the whole workspace; a screen filters by agent."""
    bus = TopicEventBus()
    ws, project, alice, task, wake, tasks = await _world(uow_factory, bus)

    await tasks.assign(task.id, alice.id)
    await _settle(RunQueryService(uow_factory), task.id)
    await wake.drain()

    events = _run_events(bus, ws.id)
    assert events, "không có sự kiện nào để lọc"
    for event in events:
        assert event["marius_id"] == str(alice.id)
        assert event["project_id"] == str(project.id)
        assert event["task_id"] == str(task.id)


async def test_the_event_carries_no_prompt_and_no_output(uow_factory) -> None:
    """Principle 4: ids and labels on this channel, never the work itself."""
    bus = TopicEventBus()
    ws, _project, alice, task, wake, tasks = await _world(uow_factory, bus)

    await tasks.assign(task.id, alice.id)
    await _settle(RunQueryService(uow_factory), task.id)
    await wake.drain()

    allowed = {"run_id", "marius_id", "task_id", "project_id", "status"}
    for event in _run_events(bus, ws.id):
        assert set(event) == allowed, f"trường lạ trên kênh workspace: {set(event) - allowed}"


async def test_a_run_stopped_mid_turn_says_so_too(uow_factory) -> None:
    """The shutdown path. A run the process abandoned is settled by ``_release_pair``,
    which is the only place that writes *stopped* — a screen told nothing here keeps
    showing it as running."""
    bus = TopicEventBus()
    ws, project, alice, task, wake, _tasks = await _world(uow_factory, bus)

    async with uow_factory() as uow:
        run = Run(
            project_id=project.id,
            marius_id=alice.id,
            task_id=task.id,
            adapter_type="echo",
            wake_source=WakeSource.ASSIGNMENT,
            status=RunStatus.RUNNING,
            created_at=NOW,
        )
        await uow.runs.add(run)
        await uow.commit()

    await wake._release_pair(run.id)  # what a cancelled turn calls on its way out

    events = _run_events(bus, ws.id)
    assert [e["status"] for e in events] == [str(RunStatus.STOPPED)]
    assert events[0]["run_id"] == str(run.id)


async def test_a_run_declared_hung_says_so_without_anyone_asking(uow_factory) -> None:
    """The transition with no request behind it — and the reason the poll existed."""
    bus = TopicEventBus()
    ws, project, alice, task, _wake, _tasks = await _world(uow_factory, bus)

    async with uow_factory() as uow:
        stored = await uow.tasks.get(task.id)
        assert stored is not None
        stored.status = TaskStatus.IN_PROGRESS
        stored.assigned_marius_id = alice.id
        await uow.tasks.update(stored)
        silent = Run(
            project_id=project.id,
            marius_id=alice.id,
            task_id=task.id,
            adapter_type="echo",
            wake_source=WakeSource.ASSIGNMENT,
            status=RunStatus.RUNNING,
            last_output_at=NOW - timedelta(seconds=SUSPECT + GRACE + 60),
            created_at=NOW - timedelta(seconds=SUSPECT + GRACE + 60),
        )
        await uow.runs.add(silent)
        await uow.commit()

    watchdog = LivenessWatchdog(
        uow_factory,
        LivenessEngine(uow_factory, FakeLivenessProbe(False)),
        interval_seconds=0.01,
        hang_suspect_seconds=SUSPECT,
        hang_grace_seconds=GRACE,
        workspace_trace=ControlBusWorkspaceTrace(bus),
    )
    assert await watchdog.reap_hung_runs(now=NOW) == 1

    events = _run_events(bus, ws.id)
    assert [e["status"] for e in events] == [str(RunStatus.TIMED_OUT)]
    assert events[0]["run_id"] == str(silent.id)


async def test_an_unwired_channel_changes_nothing(uow_factory) -> None:
    """Every emitter takes the channel as optional, so a caller that never wires one — every
    test above this file, and the fake worlds elsewhere — must still run a task normally."""
    ws, _project, alice, task, wake, tasks = await _world(uow_factory, TopicEventBus())
    silent = WakeEngine(
        uow_factory,
        wake._registry,
        InMemoryEventBus(),
        run_timeout_seconds=30,
    )
    tasks_no_channel = TaskService(uow_factory, silent)

    await tasks_no_channel.assign(task.id, alice.id)
    runs = await _settle(RunQueryService(uow_factory), task.id)
    await silent.drain()

    assert runs and all(r.status in _TERMINAL for r in runs)
    assert ws is not None
