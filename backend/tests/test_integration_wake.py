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
from armarius.domain.entities.run import RunStatus, WakeSource
from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus
from armarius.infrastructure.events.task_trace import ControlBusTaskTrace
from armarius.infrastructure.events.topic_bus import TopicEventBus
from tests.support.projects import force_phase


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
    await force_phase(uow_factory, project.id)  # FR-003 — wake routing is the subject here
    alice = await mariuses.register(
        workspace_id=ws.id,
        name="Alice",
        role="Frontend",
        skills=["react"],
        adapter_type="echo",
        adapter_config={},
    )
    task = await tasks.create(
        project_id=project.id,
        title="Add dark mode",
        description="Thêm chế độ nền tối cho toàn bộ giao diện.",
    )

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
    await force_phase(uow_factory, project.id)  # FR-003 — wake routing is the subject here

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
    await force_phase(uow_factory, project.id)  # FR-003 — wake routing is the subject here
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
    await force_phase(uow_factory, project.id)  # FR-003 — wake routing is the subject here
    cara = await mariuses.register(
        workspace_id=ws.id,
        name="Cara",
        role="Backend",
        skills=["api"],
        adapter_type="echo",
        adapter_config={},
    )
    task = await tasks.create(
        project_id=project.id,
        title="Wire it up",
        description="Nối phần giao diện vào lối gọi máy chủ.",
    )

    await tasks.assign(task.id, cara.id)
    await _wait_for_completion(runs, task.id)

    # The run's events were teed onto the task's live SSE topic (Sprint-4 channel).
    traced = control_bus.backlog(f"task:{task.id}")
    types = {e.type for e in traced}
    assert "run.queued" in types
    assert "run.finished" in types

    # #113: the agent's streamed "thinking" (assistant.delta) is coalesced into durable
    # assistant.message events and teed — the Room shows the agent's actual words, not just
    # lifecycle. Echo emits two delta groups (before/after the tool call) → two messages.
    msg_events = [e for e in traced if e.type == "assistant.message"]
    assert len(msg_events) == 2, [e.type for e in traced]
    joined = " | ".join(str(e.data.get("text", "")) for e in msg_events)
    assert "plan my work" in joined and "recording progress" in joined
    # The tool call is teed with its name (and args), not an empty bubble.
    tool_events = [e for e in traced if e.type == "tool.started"]
    assert tool_events and tool_events[0].data.get("tool_name") == "read_directory"

    # #113: every teed event carries (_run_id, _seq) matching its own RunEvent.seq, so a
    # client that backfills the durable history AND replays the SSE backlog de-dups the overlap.
    run = (await runs.list_by_task(task.id))[0]
    for e in msg_events + tool_events:
        assert e.data.get("_run_id") == str(run.id)
        assert isinstance(e.data.get("_seq"), int)

    # The same assistant.message events are in the durable trace (the backfill source).
    durable = await runs.events(run.id)
    durable_msgs = [ev for ev in durable if ev.type == "assistant.message"]
    assert len(durable_msgs) == 2
    # Durable payload stays clean — the (_run_id,_seq) envelope is a tee-only concern.
    assert "_run_id" not in durable_msgs[0].payload
    assert durable_msgs[0].seq == msg_events[0].data.get("_seq")


async def test_a_plain_comment_wakes_the_worker_who_owns_the_task(uow_factory) -> None:
    """FR-048: a new comment on a task you are responsible for is a cause on its own.

    Only an @mention used to wake anyone, so a question asked the plain way — the way
    people actually write — reached nobody until something else happened to wake the
    worker. Nothing in the wake sources said so; `comment` existed and was never produced.
    """
    wake = _wake_engine(uow_factory)
    workspaces = WorkspaceService(uow_factory)
    mariuses = MariusService(uow_factory)
    tasks = TaskService(uow_factory, wake)
    threads = ThreadService(uow_factory, wake)
    runs = RunQueryService(uow_factory)

    ws = await workspaces.create_workspace("WS")
    project = await workspaces.create_project(ws.id, "P")
    await force_phase(uow_factory, project.id)
    dana = await mariuses.register(
        workspace_id=ws.id, name="Dana", role="Backend", skills=[],
        adapter_type="echo", adapter_config={},
    )
    task = await tasks.create(
        project_id=project.id,
        title="Kết xuất báo cáo",
        description="Gom số liệu tháng rồi kết xuất ra tệp bảng tính.",
    )
    await tasks.assign(task.id, dana.id)
    await _wait_for_completion(runs, task.id)

    await threads.post_comment(
        task_id=task.id,
        body="Nhớ kèm ghi chú nguồn số liệu.",  # no @mention anywhere
        author_kind=AuthorKind.HUMAN,
        author_user_id="patron@acme.dev",
    )
    await _wait_for_completion(runs, task.id)

    async with uow_factory() as uow:
        every = await uow.runs.list_by_task(task.id)
    assert any(r.wake_source == WakeSource.COMMENT for r in every), [
        str(r.wake_source) for r in every
    ]


async def test_a_comment_does_not_wake_a_worker_with_nothing_at_stake(uow_factory) -> None:
    """FR-049, the other side: a comment is not a project-wide announcement. Someone who
    holds a seat but not this task has nothing waiting on them."""
    wake = _wake_engine(uow_factory)
    workspaces = WorkspaceService(uow_factory)
    mariuses = MariusService(uow_factory)
    tasks = TaskService(uow_factory, wake)
    threads = ThreadService(uow_factory, wake)
    runs = RunQueryService(uow_factory)

    ws = await workspaces.create_workspace("WS")
    project = await workspaces.create_project(ws.id, "P")
    await force_phase(uow_factory, project.id)
    dana, eve = [
        await mariuses.register(
            workspace_id=ws.id, name=n, role="Backend", skills=[],
            adapter_type="echo", adapter_config={},
        )
        for n in ("Dana", "Eve")
    ]
    task = await tasks.create(
        project_id=project.id,
        title="Kết xuất báo cáo",
        description="Gom số liệu tháng rồi kết xuất ra tệp bảng tính.",
    )
    await tasks.assign(task.id, dana.id)
    await _wait_for_completion(runs, task.id)

    await threads.post_comment(
        task_id=task.id,
        body="Nhớ kèm ghi chú nguồn số liệu.",
        author_kind=AuthorKind.HUMAN,
        author_user_id="patron@acme.dev",
    )
    await _wait_for_completion(runs, task.id)

    async with uow_factory() as uow:
        every = await uow.runs.list_by_task(task.id)
    assert not [r for r in every if r.marius_id == eve.id]
