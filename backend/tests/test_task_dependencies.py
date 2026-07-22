"""Cổng phụ thuộc đầu-cuối (#91) — cạnh ``blocked_by`` bền + gate ở transition/claim/
approve_proposed/assign, qua SqlAlchemyUnitOfWork thật (SQLite file).

Đích spec 05 §1.3: task còn một ``blocked_by`` chưa ``done`` thì không vào được
``todo``/``in_progress``; cạnh không hợp lệ (tự-trỏ/trùng/khác dự án/tạo vòng) bị từ chối.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from armarius.application.use_cases.mariuses import MariusService
from armarius.application.use_cases.projects import ProjectService, RoleSpec
from armarius.application.use_cases.tasks import TaskService
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.entities.task import DependencyNotMetError, TaskStatus
from armarius.domain.entities.task_dependency import TaskDependencyError
from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus


def _services(uow_factory):
    registry = InMemoryAdapterRegistry()
    registry.register(EchoAdapter(step_delay=0.0))
    wake = WakeEngine(uow_factory, registry, InMemoryEventBus(), run_timeout_seconds=30)
    return (
        ProjectService(uow_factory),
        TaskService(uow_factory, wake),
        WorkspaceService(uow_factory),
    )


def _roster() -> list[RoleSpec]:
    return [
        RoleSpec(key="leader", title="Leader", seats=1, is_leader=True, description="Leads."),
        RoleSpec(key="worker", title="Worker", seats=1, description="Works."),
    ]


async def _make_project(projects, workspaces, *, name="Proj", key="PROJ"):
    ws = await workspaces.create_workspace(name + "-WS")
    project = await projects.create_project(ws.id, name, key=key, roles=_roster())
    return ws, project


async def _mark_done(uow_factory, task_id) -> None:
    """Force a task to DONE for setup (represents a finished blocker; bypasses gates)."""
    async with uow_factory() as uow:
        t = await uow.tasks.get(task_id)
        assert t is not None
        t.status = TaskStatus.DONE
        await uow.tasks.update(t)
        await uow.commit()


async def test_transition_blocked_until_blocker_done(uow_factory) -> None:
    projects, tasks, workspaces = _services(uow_factory)
    _ws, project = await _make_project(projects, workspaces)
    blocker = await tasks.create(project_id=project.id, title="blocker")
    blocked = await tasks.create(project_id=project.id, title="blocked")
    await tasks.add_dependency(blocked.id, blocker.id)

    # blocker chưa done ⇒ vào todo bị chặn
    with pytest.raises(DependencyNotMetError):
        await tasks.transition(blocked.id, TaskStatus.TODO)

    await _mark_done(uow_factory, blocker.id)
    moved = await tasks.transition(blocked.id, TaskStatus.TODO)
    assert moved.status == TaskStatus.TODO


async def test_claim_respects_gate(uow_factory) -> None:
    projects, tasks, workspaces = _services(uow_factory)
    _ws, project = await _make_project(projects, workspaces)
    blocker = await tasks.create(project_id=project.id, title="blocker")
    blocked = await tasks.create(
        project_id=project.id, title="blocked", status=TaskStatus.TODO
    )
    await tasks.add_dependency(blocked.id, blocker.id)

    with pytest.raises(DependencyNotMetError):
        await tasks.claim(blocked.id, uuid4())

    await _mark_done(uow_factory, blocker.id)
    claimed = await tasks.claim(blocked.id, uuid4())
    assert claimed.status == TaskStatus.IN_PROGRESS


async def test_approve_proposed_respects_gate(uow_factory) -> None:
    projects, tasks, workspaces = _services(uow_factory)
    _ws, project = await _make_project(projects, workspaces)
    blocker = await tasks.create(project_id=project.id, title="blocker")
    draft = await tasks.create(
        project_id=project.id, title="draft", status=TaskStatus.DRAFT
    )
    await tasks.add_dependency(draft.id, blocker.id)

    with pytest.raises(DependencyNotMetError):
        await tasks.approve_proposed(draft.id)

    await _mark_done(uow_factory, blocker.id)
    approved = await tasks.approve_proposed(draft.id)
    assert approved.status == TaskStatus.TODO


async def test_assign_leaves_blocked_task_in_backlog(uow_factory) -> None:
    projects, tasks, workspaces = _services(uow_factory)
    mariuses = MariusService(uow_factory)
    ws, project = await _make_project(projects, workspaces)
    alice = await mariuses.register(
        workspace_id=ws.id,
        name="Alice",
        role="Worker",
        skills=[],
        adapter_type="echo",
        adapter_config={},
    )
    blocker = await tasks.create(project_id=project.id, title="blocker")
    blocked = await tasks.create(project_id=project.id, title="blocked")
    await tasks.add_dependency(blocked.id, blocker.id)

    res = await tasks.assign(blocked.id, alice.id)
    assert res.status == TaskStatus.BACKLOG  # không bị đẩy lên todo khi còn bị chặn

    await _mark_done(uow_factory, blocker.id)
    res2 = await tasks.assign(blocked.id, alice.id)
    assert res2.status == TaskStatus.TODO  # hết chặn ⇒ promote như cũ


async def test_add_dependency_rejects_self_loop(uow_factory) -> None:
    projects, tasks, workspaces = _services(uow_factory)
    _ws, project = await _make_project(projects, workspaces)
    t = await tasks.create(project_id=project.id, title="t")
    with pytest.raises(TaskDependencyError):
        await tasks.add_dependency(t.id, t.id)


async def test_add_dependency_rejects_duplicate(uow_factory) -> None:
    projects, tasks, workspaces = _services(uow_factory)
    _ws, project = await _make_project(projects, workspaces)
    a = await tasks.create(project_id=project.id, title="a")
    b = await tasks.create(project_id=project.id, title="b")
    await tasks.add_dependency(a.id, b.id)
    with pytest.raises(TaskDependencyError):
        await tasks.add_dependency(a.id, b.id)


async def test_add_dependency_rejects_cross_project(uow_factory) -> None:
    projects, tasks, workspaces = _services(uow_factory)
    _ws1, p1 = await _make_project(projects, workspaces, name="One", key="ONE")
    _ws2, p2 = await _make_project(projects, workspaces, name="Two", key="TWO")
    a = await tasks.create(project_id=p1.id, title="a")
    b = await tasks.create(project_id=p2.id, title="b")
    with pytest.raises(TaskDependencyError):
        await tasks.add_dependency(a.id, b.id)


async def test_add_dependency_rejects_cycle(uow_factory) -> None:
    projects, tasks, workspaces = _services(uow_factory)
    _ws, project = await _make_project(projects, workspaces)
    a = await tasks.create(project_id=project.id, title="a")
    b = await tasks.create(project_id=project.id, title="b")
    c = await tasks.create(project_id=project.id, title="c")
    await tasks.add_dependency(a.id, b.id)  # a blocked_by b
    await tasks.add_dependency(b.id, c.id)  # b blocked_by c
    with pytest.raises(TaskDependencyError):
        await tasks.add_dependency(c.id, a.id)  # c blocked_by a ⇒ vòng


async def test_remove_dependency_unblocks(uow_factory) -> None:
    projects, tasks, workspaces = _services(uow_factory)
    _ws, project = await _make_project(projects, workspaces)
    blocker = await tasks.create(project_id=project.id, title="blocker")
    blocked = await tasks.create(project_id=project.id, title="blocked")
    await tasks.add_dependency(blocked.id, blocker.id)
    await tasks.remove_dependency(blocked.id, blocker.id)
    moved = await tasks.transition(blocked.id, TaskStatus.TODO)  # hết cạnh ⇒ qua
    assert moved.status == TaskStatus.TODO


async def test_list_blockers_and_project_edges(uow_factory) -> None:
    projects, tasks, workspaces = _services(uow_factory)
    _ws, project = await _make_project(projects, workspaces)
    blocker = await tasks.create(project_id=project.id, title="blocker")
    blocked = await tasks.create(project_id=project.id, title="blocked")
    await tasks.add_dependency(blocked.id, blocker.id)

    blockers = await tasks.list_blockers(blocked.id)
    assert [b.id for b in blockers] == [blocker.id]

    edges = await tasks.list_project_dependencies(project.id)
    assert len(edges) == 1
    assert edges[0].task_id == blocked.id
    assert edges[0].blocks_task_id == blocker.id
