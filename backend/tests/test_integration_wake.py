from __future__ import annotations

import asyncio

from armarius.application.use_cases.mariuses import MariusService
from armarius.application.use_cases.runs import RunQueryService
from armarius.application.use_cases.tasks import TaskService
from armarius.application.use_cases.threads import ThreadService
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.entities.comment import AuthorKind
from armarius.domain.entities.run import RunStatus
from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus


def _wake_engine(uow_factory) -> WakeEngine:
    registry = InMemoryAdapterRegistry()
    registry.register(EchoAdapter(step_delay=0.0))
    return WakeEngine(
        uow_factory, registry, InMemoryEventBus(), run_timeout_seconds=30
    )


_TERMINAL = (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.TIMED_OUT)


async def _wait_for_completion(runs: RunQueryService, task_id, attempts: int = 400):
    """Wait until all runs are terminal AND the run count has stabilised.

    The echo agent never records progress, so a limbo task gets bounded self-nudges;
    we wait for that chain to settle so no background run outlives the test fixture.
    """
    stable = 0
    last_count = -1
    for _ in range(attempts):
        items = await runs.list_by_task(task_id)
        all_terminal = bool(items) and all(r.status in _TERMINAL for r in items)
        if all_terminal and len(items) == last_count:
            stable += 1
            if stable >= 8:
                return items
        else:
            stable = 0
        last_count = len(items)
        await asyncio.sleep(0.02)
    return await runs.list_by_task(task_id)


async def test_assignment_wakes_agent_runs_and_persists_session(uow_factory) -> None:
    wake = _wake_engine(uow_factory)
    workspaces = WorkspaceService(uow_factory)
    mariuses = MariusService(uow_factory)
    tasks = TaskService(uow_factory, wake)
    runs = RunQueryService(uow_factory)

    ws = await workspaces.create_workspace("WS")
    project = await workspaces.create_project(ws.id, "P")
    alice = await mariuses.register(
        workspace_id=ws.id,
        name="Alice",
        role="Frontend",
        skills=["react"],
        adapter_type="echo",
        adapter_config={},
    )
    task = await tasks.create(project_id=project.id, title="Add dark mode")

    await tasks.assign(task.id, alice.id)
    completed = await _wait_for_completion(runs, task.id)

    assert len(completed) == 1
    run = completed[0]
    assert run.status == RunStatus.COMPLETED

    # A durable trace was teed from the adapter stream.
    events = await runs.events(run.id)
    types = {e.type for e in events}
    assert "run.completed" in types
    assert "tool.started" in types

    # The (marius, adapter, task) session was persisted for future resume.
    async with uow_factory() as uow:
        session = await uow.sessions.get_for(alice.id, "echo", task.id)
    assert session is not None
    assert session.session_params_json.get("session_id")


async def test_mention_wakes_the_mentioned_agent(uow_factory) -> None:
    wake = _wake_engine(uow_factory)
    workspaces = WorkspaceService(uow_factory)
    mariuses = MariusService(uow_factory)
    tasks = TaskService(uow_factory, wake)
    threads = ThreadService(uow_factory, wake)
    runs = RunQueryService(uow_factory)

    ws = await workspaces.create_workspace("WS")
    project = await workspaces.create_project(ws.id, "P")
    bob = await mariuses.register(
        workspace_id=ws.id,
        name="Bob",
        role="Design",
        skills=["figma"],
        adapter_type="echo",
        adapter_config={},
    )
    task = await tasks.create(project_id=project.id, title="Need a palette")

    comment = await threads.post_comment(
        task_id=task.id,
        body="@Bob can you confirm the dark palette?",
        author_kind=AuthorKind.HUMAN,
        author_user_id="patron@acme.dev",
    )
    assert bob.id in comment.mentions

    completed = await _wait_for_completion(runs, task.id)
    assert any(r.marius_id == bob.id for r in completed)
