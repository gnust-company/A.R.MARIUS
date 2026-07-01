"""Sprint-5 integration — commission over the real stack (SQL + WakeEngine + echo).

Proves the DoD's commission behaviours end-to-end against a real UoW and a real wake engine:
  * confirm flips the draft `draft → todo` and wakes the project's seated workers;
  * a turn requested while the Leader is offline is *queued* (no run) and *drains* — runs —
    once the Leader comes back online.
"""

from __future__ import annotations

import asyncio

from armarius.application.use_cases.commission import CommissionService
from armarius.application.use_cases.liveness import LivenessEngine
from armarius.application.use_cases.mariuses import MariusService
from armarius.application.use_cases.projects import ProjectService, RoleSpec
from armarius.application.use_cases.runs import RunQueryService
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.entities.commission import CommissionStatus, LeaderState
from armarius.domain.entities.run import RunStatus
from armarius.domain.entities.task import TaskStatus
from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus
from tests.support.fakes import FakeLivenessProbe

_TERMINAL = (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.TIMED_OUT)


def _wake_engine(uow_factory) -> WakeEngine:
    registry = InMemoryAdapterRegistry()
    registry.register(EchoAdapter(step_delay=0.0))
    return WakeEngine(uow_factory, registry, InMemoryEventBus(), run_timeout_seconds=30)


def _roster() -> list[RoleSpec]:
    return [
        RoleSpec(key="leader", title="Leader", seats=1, is_leader=True),
        RoleSpec(key="backend", title="Backend", seats=1),
    ]


async def _settle(runs: RunQueryService, task_id, *, want_marius=None, attempts=400):
    """Wait until every run on the task is terminal and the count has stabilised (so no
    background self-nudge outlives the test). Returns the final run list."""
    stable, last = 0, -1
    for _ in range(attempts):
        items = await runs.list_by_task(task_id)
        has_want = want_marius is None or any(r.marius_id == want_marius for r in items)
        all_terminal = bool(items) and all(r.status in _TERMINAL for r in items)
        if has_want and all_terminal and len(items) == last:
            stable += 1
            if stable >= 8:
                return items
        else:
            stable = 0
        last = len(items)
        await asyncio.sleep(0.02)
    return await runs.list_by_task(task_id)


async def test_confirm_flips_draft_to_todo_and_wakes_workers(uow_factory) -> None:
    wake = _wake_engine(uow_factory)
    workspaces = WorkspaceService(uow_factory)
    mariuses = MariusService(uow_factory)
    projects = ProjectService(uow_factory)
    commission = CommissionService(uow_factory, wake)
    runs = RunQueryService(uow_factory)

    ws = await workspaces.create_workspace("WS")
    project = await projects.create_project(ws.id, "Apollo", roles=_roster())
    leader = await mariuses.register(
        workspace_id=ws.id, name="Lead", role="Leader",
        skills=[], adapter_type="echo", adapter_config={},
    )
    worker = await mariuses.register(
        workspace_id=ws.id, name="Dev", role="Backend",
        skills=[], adapter_type="echo", adapter_config={},
    )
    await projects.grant_seat(project.id, "leader", leader.id, system=True)
    await projects.grant_seat(project.id, "backend", worker.id, system=True)

    # Leader is offline → its shaping turn is queued (no leader run pollutes this test).
    session = await commission.commission(project_id=project.id, message="Build /login")
    task_id = session.task_id
    assert session.leader_state == LeaderState.LEADER_OFFLINE

    confirmed = await commission.confirm(session.id)
    assert confirmed.status == CommissionStatus.CONFIRMED

    # The draft is now on the board and the seated worker was woken (a run appears).
    items = await _settle(runs, task_id, want_marius=worker.id)
    assert any(r.marius_id == worker.id for r in items)
    async with uow_factory() as uow:
        task = await uow.tasks.get(task_id)
    assert task.status == TaskStatus.TODO


async def test_offline_leader_queues_then_drains_on_online(uow_factory) -> None:
    wake = _wake_engine(uow_factory)
    workspaces = WorkspaceService(uow_factory)
    mariuses = MariusService(uow_factory)
    projects = ProjectService(uow_factory)
    liveness = LivenessEngine(uow_factory, FakeLivenessProbe(True))
    commission = CommissionService(uow_factory, wake)
    runs = RunQueryService(uow_factory)

    ws = await workspaces.create_workspace("WS")
    project = await projects.create_project(ws.id, "Apollo", roles=_roster())
    leader = await mariuses.register(
        workspace_id=ws.id, name="Lead", role="Leader",
        skills=[], adapter_type="echo", adapter_config={},
    )
    await projects.grant_seat(project.id, "leader", leader.id, system=True)

    # Leader offline → the turn is QUEUED: no run is dispatched.
    session = await commission.commission(project_id=project.id, message="shape it")
    assert session.leader_state == LeaderState.LEADER_OFFLINE
    await asyncio.sleep(0.05)
    assert await runs.list_by_task(session.task_id) == []

    # Leader comes online → the queued turn DRAINS and now runs.
    await liveness.record_signal(leader.id)
    drained = await commission.on_leader_online(leader.id)
    assert drained == 1

    items = await _settle(runs, session.task_id, want_marius=leader.id)
    assert any(r.marius_id == leader.id for r in items)
