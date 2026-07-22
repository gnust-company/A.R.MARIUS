"""JIRA-style task keys — ProjectService.create_project(key) + TaskService mints ``{KEY}-{seq}``.

Đầu-cuối qua SqlAlchemyUnitOfWork thật (SQLite file): key duy nhất theo workspace, seq monotonic
cấp phát atomic (``allocate_task_number``), identifier persist qua lưu–tải lại.
"""

from __future__ import annotations

import pytest

from armarius.application.use_cases.projects import (
    DuplicateProjectKey,
    ProjectService,
    RoleSpec,
)
from armarius.application.use_cases.tasks import TaskService
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.services.project_key import InvalidProjectKey
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


async def test_explicit_key_drives_task_identifiers(uow_factory) -> None:
    projects, tasks, workspaces = _services(uow_factory)
    ws = await workspaces.create_workspace("WS")
    project = await projects.create_project(ws.id, "Calculator", key="CALC", roles=_roster())

    assert project.key == "CALC"
    t1 = await tasks.create(project_id=project.id, title="a")
    t2 = await tasks.create(project_id=project.id, title="b")
    t3 = await tasks.create(project_id=project.id, title="c")
    assert (t1.identifier, t2.identifier, t3.identifier) == ("CALC-1", "CALC-2", "CALC-3")


async def test_missing_key_is_suggested_from_name(uow_factory) -> None:
    projects, tasks, workspaces = _services(uow_factory)
    ws = await workspaces.create_workspace("WS")
    project = await projects.create_project(ws.id, "Calculator", roles=_roster())
    assert project.key == "CALC"  # suggested from the name
    task = await tasks.create(project_id=project.id, title="a")
    assert task.identifier == "CALC-1"


async def test_duplicate_key_in_same_workspace_is_rejected(uow_factory) -> None:
    projects, _tasks, workspaces = _services(uow_factory)
    ws = await workspaces.create_workspace("WS")
    await projects.create_project(ws.id, "Calc One", key="CALC", roles=_roster())
    with pytest.raises(DuplicateProjectKey):
        await projects.create_project(ws.id, "Calc Two", key="CALC", roles=_roster())


async def test_same_key_in_different_workspaces_is_allowed(uow_factory) -> None:
    projects, _tasks, workspaces = _services(uow_factory)
    ws1 = await workspaces.create_workspace("WS1")
    ws2 = await workspaces.create_workspace("WS2")
    a = await projects.create_project(ws1.id, "A", key="AB", roles=_roster())
    b = await projects.create_project(ws2.id, "B", key="AB", roles=_roster())
    assert a.key == "AB" and b.key == "AB"


async def test_invalid_key_format_is_rejected(uow_factory) -> None:
    projects, _tasks, workspaces = _services(uow_factory)
    ws = await workspaces.create_workspace("WS")
    with pytest.raises(InvalidProjectKey):
        await projects.create_project(ws.id, "Bad", key="1UP", roles=_roster())  # leading digit


async def test_counter_advances_and_identifier_persists(uow_factory) -> None:
    projects, tasks, workspaces = _services(uow_factory)
    ws = await workspaces.create_workspace("WS")
    project = await projects.create_project(ws.id, "Calculator", key="CALC", roles=_roster())
    created = await tasks.create(project_id=project.id, title="a")

    reloaded_task = await tasks.get(created.id)
    assert reloaded_task is not None
    assert reloaded_task.identifier == "CALC-1"  # survives reload (persisted column)

    reloaded_project = await projects.get_project(project.id)
    assert reloaded_project is not None
    assert reloaded_project.next_task_seq == 2  # counter advanced past the one allocated seq


async def test_each_project_has_its_own_sequence(uow_factory) -> None:
    projects, tasks, workspaces = _services(uow_factory)
    ws = await workspaces.create_workspace("WS")
    calc = await projects.create_project(ws.id, "Calculator", key="CALC", roles=_roster())
    bot = await projects.create_project(ws.id, "AI Bot", key="BOT", roles=_roster())
    c1 = await tasks.create(project_id=calc.id, title="a")
    b1 = await tasks.create(project_id=bot.id, title="a")
    c2 = await tasks.create(project_id=calc.id, title="b")
    assert (c1.identifier, b1.identifier, c2.identifier) == ("CALC-1", "BOT-1", "CALC-2")
