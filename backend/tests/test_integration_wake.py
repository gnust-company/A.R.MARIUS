from __future__ import annotations

import asyncio

from armarius.application.use_cases.mariuses import MariusService
from armarius.application.use_cases.projects import ProjectService, RoleSpec
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
from armarius.infrastructure.events.task_trace import ControlBusTaskTrace
from armarius.infrastructure.events.topic_bus import TopicEventBus


def _wake_engine(uow_factory, *, task_trace=None) -> WakeEngine:
    registry = InMemoryAdapterRegistry()
    registry.register(EchoAdapter(step_delay=0.0))
    return WakeEngine(
        uow_factory,
        registry,
        InMemoryEventBus(),
        run_timeout_seconds=30,
        task_trace=task_trace,
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


async def test_wake_directory_is_project_scoped_with_project_roles(uow_factory) -> None:
    """The wake directory is the seat-holders of THIS project, each with their project role
    resolved via SeatGrant.role_key → Role — never the whole workspace, never Marius.role
    (issue #87 / spec 03 §3.1, §3.2)."""
    wake = _wake_engine(uow_factory)
    workspaces = WorkspaceService(uow_factory)
    mariuses = MariusService(uow_factory)
    projects = ProjectService(uow_factory)

    ws = await workspaces.create_workspace("WS")
    project = await projects.create_project(
        ws.id,
        "P",
        roles=[
            RoleSpec(key="leader", title="Leader", seats=1, is_leader=True, description="Leads."),
            RoleSpec(key="backend", title="Backend", seats=1, description="Owns the API."),
            RoleSpec(key="design", title="Design", seats=1, description="Owns UX."),
        ],
    )

    async def reg(name: str):
        # role="" on purpose: the workspace-level role is empty, so a correct directory
        # MUST come from the project roster, not this field.
        return await mariuses.register(
            workspace_id=ws.id, name=name, role="", skills=[],
            adapter_type="echo", adapter_config={},
        )

    lead, bob, dana, ext = [await reg(n) for n in ("Lead", "Bob", "Dana", "Ext")]
    await projects.grant_seat(project.id, "leader", lead.id, system=True)
    await projects.grant_seat(project.id, "backend", bob.id, system=True)
    await projects.grant_seat(project.id, "design", dana.id, system=True)
    # `ext` is in the workspace but holds NO seat on this project.

    async with uow_factory() as uow:
        directory, self_role = await wake._project_directory(uow, project.id, bob)

    names = {m.name for (m, _role) in directory}
    assert names == {"Lead", "Bob", "Dana"}  # project members only …
    assert "Ext" not in names  # … the off-project workspace agent is excluded

    # Bob's OWN role is resolved from its seat (Backend), not the empty Marius.role.
    assert self_role is not None and self_role.title == "Backend"

    # Teammate roles come from the project roster, with their descriptions.
    role_by_name = {m.name: role for (m, role) in directory}
    assert role_by_name["Dana"].title == "Design"
    assert role_by_name["Dana"].description == "Owns UX."
    assert role_by_name["Lead"].title == "Leader"


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


async def test_run_trace_tees_to_per_task_sse_channel(uow_factory) -> None:
    control_bus = TopicEventBus()
    wake = _wake_engine(uow_factory, task_trace=ControlBusTaskTrace(control_bus))
    workspaces = WorkspaceService(uow_factory)
    mariuses = MariusService(uow_factory)
    tasks = TaskService(uow_factory, wake)
    runs = RunQueryService(uow_factory)

    ws = await workspaces.create_workspace("WS")
    project = await workspaces.create_project(ws.id, "P")
    cara = await mariuses.register(
        workspace_id=ws.id,
        name="Cara",
        role="Backend",
        skills=["api"],
        adapter_type="echo",
        adapter_config={},
    )
    task = await tasks.create(project_id=project.id, title="Wire it up")

    await tasks.assign(task.id, cara.id)
    await _wait_for_completion(runs, task.id)

    # The run's events were teed onto the task's live SSE topic (Sprint-4 channel).
    traced = control_bus.backlog(f"task:{task.id}")
    types = {e.type for e in traced}
    assert "run.queued" in types
    assert "run.finished" in types
