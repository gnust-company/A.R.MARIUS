"""Integration — Chat-with-Leader over the real stack (SQL + adapter streaming, #82).

Proves the core behaviours end-to-end against a real UoW and the echo adapter:
  * a patron message wakes the Leader on the project session; the reply is reconstructed
    from the streamed ``assistant.delta`` events and appended to the durable transcript;
  * an offline Leader disables the chat (no queue) — ``send`` raises;
  * turn-taking: a second message while a turn is in flight is rejected;
  * a Leader-proposed draft is approved (→ todo + the assignee is woken) or rejected
    (→ cancelled).
"""

from __future__ import annotations

import asyncio

import pytest

from armarius.application.use_cases.leader_chat import LeaderChatService
from armarius.application.use_cases.liveness import LivenessEngine
from armarius.application.use_cases.mariuses import MariusService
from armarius.application.use_cases.projects import ProjectService, RoleSpec
from armarius.application.use_cases.runs import RunQueryService
from armarius.application.use_cases.tasks import TaskService
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.entities.leader_chat import ChatState, LeaderChatError
from armarius.domain.entities.run import RunStatus
from armarius.domain.entities.task import TaskStatus
from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus
from armarius.infrastructure.events.topic_bus import TopicEventBus
from tests.support.fakes import FakeLivenessProbe

_TERMINAL = (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.TIMED_OUT)


def _roster() -> list[RoleSpec]:
    return [
        RoleSpec(key="leader", title="Leader", seats=1, is_leader=True),
        RoleSpec(key="backend", title="Backend", seats=1),
    ]


def _chat_service(uow_factory, bus: TopicEventBus, *, step_delay: float = 0.0) -> LeaderChatService:
    registry = InMemoryAdapterRegistry()
    registry.register(EchoAdapter(step_delay=step_delay))
    liveness = LivenessEngine(uow_factory, FakeLivenessProbe())
    return LeaderChatService(
        uow_factory,
        registry=registry,
        control_bus=bus,
        liveness=liveness,
        base_url="http://api",
        run_timeout_seconds=30,
    )


def _wake_engine(uow_factory) -> WakeEngine:
    registry = InMemoryAdapterRegistry()
    registry.register(EchoAdapter(step_delay=0.0))
    return WakeEngine(uow_factory, registry, InMemoryEventBus(), run_timeout_seconds=30)


async def _settle_chat(chat: LeaderChatService, project_id, *, attempts: int = 400):
    for _ in range(attempts):
        view = await chat.get_or_open(project_id)
        if view.conversation.state != ChatState.THINKING:
            return view
        await asyncio.sleep(0.02)
    return await chat.get_or_open(project_id)


async def _settle_runs(runs: RunQueryService, task_id, *, want_marius=None, attempts=400):
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


async def _register_leader(mariuses, projects, ws, project, *, online_via=None):
    leader = await mariuses.register(
        workspace_id=ws.id, name="Lead", role="Leader",
        skills=[], adapter_type="echo", adapter_config={},
    )
    await projects.grant_seat(project.id, "leader", leader.id, system=True)
    if online_via is not None:
        await online_via.record_signal(leader.id)  # → ONLINE
    return leader


async def test_send_streams_leader_reply_into_transcript(uow_factory) -> None:
    bus = TopicEventBus()
    workspaces = WorkspaceService(uow_factory)
    mariuses = MariusService(uow_factory)
    projects = ProjectService(uow_factory)
    liveness = LivenessEngine(uow_factory, FakeLivenessProbe(True))
    chat = _chat_service(uow_factory, bus)

    ws = await workspaces.create_workspace("WS")
    project = await projects.create_project(ws.id, "Apollo", roles=_roster())
    await _register_leader(mariuses, projects, ws, project, online_via=liveness)

    view = await chat.send(project_id=project.id, message="How's the project going?")
    assert view.conversation.state == ChatState.THINKING
    assert view.leader_online is True

    settled = await _settle_chat(chat, project.id)
    assert settled.conversation.state == ChatState.IDLE
    roles = [t["role"] for t in settled.conversation.transcript]
    assert roles == ["patron", "leader"]
    assert settled.conversation.transcript[1]["text"]  # reply came from the stream
    # The dedicated project session was seeded and persisted for resume.
    assert (
        settled.conversation.session_params.get("session_id")
        == f"armarius:project:{project.id}:leader"
    )


async def test_offline_leader_disables_chat(uow_factory) -> None:
    bus = TopicEventBus()
    workspaces = WorkspaceService(uow_factory)
    mariuses = MariusService(uow_factory)
    projects = ProjectService(uow_factory)
    chat = _chat_service(uow_factory, bus)

    ws = await workspaces.create_workspace("WS")
    project = await projects.create_project(ws.id, "Apollo", roles=_roster())
    await _register_leader(mariuses, projects, ws, project)  # left OFFLINE

    view = await chat.get_or_open(project.id)
    assert view.leader_online is False
    with pytest.raises(LeaderChatError):
        await chat.send(project_id=project.id, message="are you there?")


async def test_turn_taking_rejects_concurrent_send(uow_factory) -> None:
    bus = TopicEventBus()
    workspaces = WorkspaceService(uow_factory)
    mariuses = MariusService(uow_factory)
    projects = ProjectService(uow_factory)
    liveness = LivenessEngine(uow_factory, FakeLivenessProbe(True))
    chat = _chat_service(uow_factory, bus, step_delay=0.1)  # keep the turn in flight

    ws = await workspaces.create_workspace("WS")
    project = await projects.create_project(ws.id, "Apollo", roles=_roster())
    await _register_leader(mariuses, projects, ws, project, online_via=liveness)

    await chat.send(project_id=project.id, message="first")
    with pytest.raises(LeaderChatError):
        await chat.send(project_id=project.id, message="second (too soon)")
    await _settle_chat(chat, project.id)  # drain so no bg task outlives the test


async def test_proposed_task_approve_flips_todo_and_wakes(uow_factory) -> None:
    wake = _wake_engine(uow_factory)
    workspaces = WorkspaceService(uow_factory)
    mariuses = MariusService(uow_factory)
    projects = ProjectService(uow_factory)
    tasks = TaskService(uow_factory, wake)
    runs = RunQueryService(uow_factory)

    ws = await workspaces.create_workspace("WS")
    project = await projects.create_project(ws.id, "Apollo", roles=_roster())
    worker = await mariuses.register(
        workspace_id=ws.id, name="Dev", role="Backend",
        skills=[], adapter_type="echo", adapter_config={},
    )
    await projects.grant_seat(project.id, "backend", worker.id, system=True)

    draft = await tasks.create(
        project_id=project.id, title="Build /login", status=TaskStatus.DRAFT,
        assigned_marius_id=worker.id,
    )
    assert draft.status == TaskStatus.DRAFT

    approved = await tasks.approve_proposed(draft.id)
    assert approved.status == TaskStatus.TODO

    items = await _settle_runs(runs, draft.id, want_marius=worker.id)
    assert any(r.marius_id == worker.id for r in items)


async def test_proposed_task_reject_cancels(uow_factory) -> None:
    wake = _wake_engine(uow_factory)
    workspaces = WorkspaceService(uow_factory)
    projects = ProjectService(uow_factory)
    tasks = TaskService(uow_factory, wake)

    ws = await workspaces.create_workspace("WS")
    project = await projects.create_project(ws.id, "Apollo", roles=_roster())
    draft = await tasks.create(
        project_id=project.id, title="Maybe later", status=TaskStatus.DRAFT,
    )
    rejected = await tasks.reject_proposed(draft.id)
    assert rejected.status == TaskStatus.CANCELLED
