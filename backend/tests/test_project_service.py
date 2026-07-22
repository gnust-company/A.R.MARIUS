"""ProjectService — roster create rule, system-only grants, activation (LLD §3.1, §4)."""

from __future__ import annotations

import pytest

from armarius.application.use_cases.projects import (
    ProjectService,
    RoleSpec,
    SystemOnlyOperation,
)
from armarius.domain.entities.marius import Liveness, Marius
from armarius.domain.entities.project import ProjectStatus
from armarius.domain.entities.seat_grant import SeatGrantError, SeatGrantStatus
from armarius.domain.entities.workspace import Workspace
from armarius.domain.services.project_rules import InvalidProjectPlan
from tests.support.fakes import FakeUowFactory


def _factory_with_workspace() -> tuple[FakeUowFactory, Workspace]:
    factory = FakeUowFactory()
    ws = Workspace(name="Studio", slug="studio", owner_user_id="u1")
    factory.store.workspaces[ws.id] = ws
    return factory, ws


def _seed_marius(factory: FakeUowFactory, ws: Workspace, liveness: Liveness) -> Marius:
    m = Marius(workspace_id=ws.id, name="Agent", role="Worker", liveness=liveness)
    factory.store.mariuses[m.id] = m
    return m


def _valid_roster() -> list[RoleSpec]:
    return [
        RoleSpec(key="leader", title="Leader", seats=1, is_leader=True, description="Leads."),
        RoleSpec(key="backend", title="Backend", seats=1, description="Owns the API."),
    ]


async def test_create_project_persists_roster_in_setup() -> None:
    factory, ws = _factory_with_workspace()
    svc = ProjectService(factory)

    project = await svc.create_project(ws.id, "Apollo", roles=_valid_roster())

    assert project.status == ProjectStatus.SETUP
    roles = await svc.list_roles(project.id)
    assert {r.key for r in roles} == {"leader", "backend"}
    assert all(r.project_id == project.id for r in roles)


async def test_create_project_rejects_roster_without_leader() -> None:
    factory, ws = _factory_with_workspace()
    svc = ProjectService(factory)
    bad = [RoleSpec(key="backend", title="Backend", seats=1)]  # no leader

    with pytest.raises(InvalidProjectPlan):
        await svc.create_project(ws.id, "Apollo", roles=bad)
    # nothing persisted on a rejected plan
    assert factory.store.projects == {}
    assert factory.store.roles == {}


async def test_grant_seat_is_system_only() -> None:
    factory, ws = _factory_with_workspace()
    svc = ProjectService(factory)
    project = await svc.create_project(ws.id, "Apollo", roles=_valid_roster())
    m = _seed_marius(factory, ws, Liveness.ONLINE)

    with pytest.raises(SystemOnlyOperation):
        await svc.grant_seat(project.id, "leader", m.id)  # system defaults to False


async def test_system_grant_creates_active_grant() -> None:
    factory, ws = _factory_with_workspace()
    svc = ProjectService(factory)
    project = await svc.create_project(ws.id, "Apollo", roles=_valid_roster())
    m = _seed_marius(factory, ws, Liveness.ONLINE)

    grant = await svc.grant_seat(project.id, "leader", m.id, system=True)

    assert grant.status == SeatGrantStatus.GRANTED
    assert grant.marius_id == m.id
    assert grant.role_key == "leader"


async def test_project_activates_when_all_seats_online() -> None:
    factory, ws = _factory_with_workspace()
    svc = ProjectService(factory)
    project = await svc.create_project(ws.id, "Apollo", roles=_valid_roster())
    leader = _seed_marius(factory, ws, Liveness.ONLINE)
    worker = _seed_marius(factory, ws, Liveness.ONLINE)

    await svc.grant_seat(project.id, "leader", leader.id, system=True)
    # not active yet — the worker seat is still empty
    assert factory.store.projects[project.id].status == ProjectStatus.SETUP

    await svc.grant_seat(project.id, "backend", worker.id, system=True)
    assert factory.store.projects[project.id].status == ProjectStatus.ACTIVE


async def test_project_stays_setup_when_a_seat_is_offline() -> None:
    factory, ws = _factory_with_workspace()
    svc = ProjectService(factory)
    project = await svc.create_project(ws.id, "Apollo", roles=_valid_roster())
    leader = _seed_marius(factory, ws, Liveness.ONLINE)
    worker = _seed_marius(factory, ws, Liveness.OFFLINE)

    await svc.grant_seat(project.id, "leader", leader.id, system=True)
    await svc.grant_seat(project.id, "backend", worker.id, system=True)

    assert factory.store.projects[project.id].status == ProjectStatus.SETUP


async def test_recompute_activates_after_agent_comes_online() -> None:
    factory, ws = _factory_with_workspace()
    svc = ProjectService(factory)
    project = await svc.create_project(ws.id, "Apollo", roles=_valid_roster())
    leader = _seed_marius(factory, ws, Liveness.ONLINE)
    worker = _seed_marius(factory, ws, Liveness.OFFLINE)
    await svc.grant_seat(project.id, "leader", leader.id, system=True)
    await svc.grant_seat(project.id, "backend", worker.id, system=True)

    # worker comes online, then the engine/recompute is re-run
    worker.liveness = Liveness.ONLINE
    flipped = await svc.recompute_active(project.id)

    assert flipped is True
    assert factory.store.projects[project.id].status == ProjectStatus.ACTIVE


async def test_active_project_never_rolls_back() -> None:
    factory, ws = _factory_with_workspace()
    svc = ProjectService(factory)
    project = await svc.create_project(ws.id, "Apollo", roles=_valid_roster())
    leader = _seed_marius(factory, ws, Liveness.ONLINE)
    worker = _seed_marius(factory, ws, Liveness.ONLINE)
    await svc.grant_seat(project.id, "leader", leader.id, system=True)
    await svc.grant_seat(project.id, "backend", worker.id, system=True)
    assert factory.store.projects[project.id].status == ProjectStatus.ACTIVE

    worker.liveness = Liveness.OFFLINE  # an agent drops
    flipped = await svc.recompute_active(project.id)

    assert flipped is False  # nothing changed
    assert factory.store.projects[project.id].status == ProjectStatus.ACTIVE


async def test_roster_crud_round_trip() -> None:
    factory, ws = _factory_with_workspace()
    svc = ProjectService(factory)
    project = await svc.create_project(ws.id, "Apollo", roles=_valid_roster())

    added = await svc.add_role(
        project.id, RoleSpec(key="qa", title="QA", seats=2, description="Tests the work.")
    )
    assert {r.key for r in await svc.list_roles(project.id)} == {"leader", "backend", "qa"}

    await svc.update_role(added.id, seats=3, title="Quality")
    refreshed = next(r for r in await svc.list_roles(project.id) if r.id == added.id)
    assert refreshed.seats == 3
    assert refreshed.title == "Quality"

    await svc.remove_role(added.id)
    assert {r.key for r in await svc.list_roles(project.id)} == {"leader", "backend"}


async def test_add_role_rejects_a_missing_description() -> None:
    # add_role bypasses validate_plan, so it enforces the description rule itself (#112).
    factory, ws = _factory_with_workspace()
    svc = ProjectService(factory)
    project = await svc.create_project(ws.id, "Apollo", roles=_valid_roster())
    with pytest.raises(InvalidProjectPlan):
        await svc.add_role(project.id, RoleSpec(key="qa", title="QA", seats=1))  # no description


async def test_revoke_seat_is_system_only_and_idempotent_guard() -> None:
    factory, ws = _factory_with_workspace()
    svc = ProjectService(factory)
    project = await svc.create_project(ws.id, "Apollo", roles=_valid_roster())
    m = _seed_marius(factory, ws, Liveness.ONLINE)
    grant = await svc.grant_seat(project.id, "leader", m.id, system=True)

    with pytest.raises(SystemOnlyOperation):
        await svc.revoke_seat(grant.id)  # non-system

    revoked = await svc.revoke_seat(grant.id, system=True)
    assert revoked.status == SeatGrantStatus.REVOKED
    with pytest.raises(SeatGrantError):
        await svc.revoke_seat(grant.id, system=True)  # already revoked
