"""ProjectService — the roster it fixes for itself, system-only grants, activation.

LLD §3.1, §4, and FR-007l for the roster: a project is born with two rows nobody supplies —
the leader seat and the bench — so the only thing a caller says about the team is which agents
are on it.
"""

from __future__ import annotations

import pytest

from armarius.application.use_cases.projects import (
    LEADER_ROLE_KEY,
    MEMBERS_ROLE_KEY,
    ProjectService,
    SystemOnlyOperation,
)
from armarius.domain.entities.marius import Liveness, Marius
from armarius.domain.entities.project import ProjectStatus
from armarius.domain.entities.workspace import Workspace
from armarius.domain.services.project_rules import InvalidProjectPlan
from armarius.shared.errors import BadRequest, NotFound
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


async def test_create_project_persists_roster_in_setup() -> None:
    factory, ws = _factory_with_workspace()
    svc = ProjectService(factory)

    project = await svc.create_project(ws.id, "Apollo", leader_description="Leads.")

    assert project.status == ProjectStatus.SETUP
    roles = await svc.list_roles(project.id)
    assert {r.key for r in roles} == {LEADER_ROLE_KEY, MEMBERS_ROLE_KEY}
    assert all(r.project_id == project.id for r in roles)


async def test_create_project_rejects_a_leader_with_no_brief() -> None:
    """The one thing a caller still says about the roster, and it may not be blank.

    It is what tells the Leader — in the packet it is woken with — that it is the Leader of
    this project rather than a worker on it.
    """
    factory, ws = _factory_with_workspace()
    svc = ProjectService(factory)

    with pytest.raises(InvalidProjectPlan):
        await svc.create_project(ws.id, "Apollo", leader_description="   ")
    # nothing persisted on a rejected plan
    assert factory.store.projects == {}
    assert factory.store.roles == {}


async def test_grant_seat_is_system_only() -> None:
    factory, ws = _factory_with_workspace()
    svc = ProjectService(factory)
    project = await svc.create_project(ws.id, "Apollo", leader_description="Leads.")
    m = _seed_marius(factory, ws, Liveness.ONLINE)

    with pytest.raises(SystemOnlyOperation):
        await svc.grant_seat(project.id, LEADER_ROLE_KEY, m.id)  # system defaults to False


async def test_system_grant_creates_active_grant() -> None:
    factory, ws = _factory_with_workspace()
    svc = ProjectService(factory)
    project = await svc.create_project(ws.id, "Apollo", leader_description="Leads.")
    m = _seed_marius(factory, ws, Liveness.ONLINE)

    grant = await svc.seat_leader(project.id, m.id)

    assert grant.marius_id == m.id
    assert grant.role_key == LEADER_ROLE_KEY

    # T199 — seating the same agent in the same place again is the seat it already has,
    # not a second row that would read as a second filled seat.
    again = await svc.seat_leader(project.id, m.id)
    assert again.id == grant.id
    assert len(await svc.list_seat_grants(project.id)) == 1


async def test_project_activates_when_all_seats_online() -> None:
    factory, ws = _factory_with_workspace()
    svc = ProjectService(factory)
    project = await svc.create_project(ws.id, "Apollo", leader_description="Leads.")
    leader = _seed_marius(factory, ws, Liveness.ONLINE)
    worker = _seed_marius(factory, ws, Liveness.ONLINE)

    await svc.seat_leader(project.id, leader.id)
    # not active yet — nobody is on the bench
    assert factory.store.projects[project.id].status == ProjectStatus.SETUP

    await svc.add_member(project.id, worker.id)
    assert factory.store.projects[project.id].status == ProjectStatus.PLANNING


async def test_project_stays_setup_when_a_seat_is_offline() -> None:
    factory, ws = _factory_with_workspace()
    svc = ProjectService(factory)
    project = await svc.create_project(ws.id, "Apollo", leader_description="Leads.")
    leader = _seed_marius(factory, ws, Liveness.ONLINE)
    worker = _seed_marius(factory, ws, Liveness.OFFLINE)

    await svc.seat_leader(project.id, leader.id)
    await svc.add_member(project.id, worker.id)

    assert factory.store.projects[project.id].status == ProjectStatus.SETUP


async def test_recompute_activates_after_agent_comes_online() -> None:
    factory, ws = _factory_with_workspace()
    svc = ProjectService(factory)
    project = await svc.create_project(ws.id, "Apollo", leader_description="Leads.")
    leader = _seed_marius(factory, ws, Liveness.ONLINE)
    worker = _seed_marius(factory, ws, Liveness.OFFLINE)
    await svc.seat_leader(project.id, leader.id)
    await svc.add_member(project.id, worker.id)

    # worker comes online, then the engine/recompute is re-run
    worker.liveness = Liveness.ONLINE
    flipped = await svc.recompute_active(project.id)

    assert flipped is True
    assert factory.store.projects[project.id].status == ProjectStatus.PLANNING


async def test_activated_project_never_rolls_back() -> None:
    factory, ws = _factory_with_workspace()
    svc = ProjectService(factory)
    project = await svc.create_project(ws.id, "Apollo", leader_description="Leads.")
    leader = _seed_marius(factory, ws, Liveness.ONLINE)
    worker = _seed_marius(factory, ws, Liveness.ONLINE)
    await svc.seat_leader(project.id, leader.id)
    await svc.add_member(project.id, worker.id)
    assert factory.store.projects[project.id].status == ProjectStatus.PLANNING

    worker.liveness = Liveness.OFFLINE  # an agent drops
    flipped = await svc.recompute_active(project.id)

    assert flipped is False  # nothing changed
    assert factory.store.projects[project.id].status == ProjectStatus.PLANNING


async def test_the_roster_does_not_grow_a_row_however_many_agents_join() -> None:
    """The whole of T039j, measured at the layer that used to grow one.

    Adding an agent used to mean adding a role first. Four agents therefore meant four more
    rows in the roster, each with a title and a description of the work somebody typed by
    hand — beside the instructions already written on each of those agents.
    """
    factory, ws = _factory_with_workspace()
    svc = ProjectService(factory)
    project = await svc.create_project(ws.id, "Apollo", leader_description="Leads.")

    for i in range(4):
        m = Marius(workspace_id=ws.id, name=f"Agent {i}", liveness=Liveness.ONLINE)
        factory.store.mariuses[m.id] = m
        await svc.add_member(project.id, m.id)

    assert {r.key for r in await svc.list_roles(project.id)} == {
        LEADER_ROLE_KEY,
        MEMBERS_ROLE_KEY,
    }
    assert len(await svc.list_seat_grants(project.id)) == 4


async def test_the_bench_says_it_holds_as_many_as_are_on_it() -> None:
    """What the patron is shown, and the reason it is not the stored number.

    The bench asks for one agent, meaning *at least* one — so a project of three would read
    as having one place if the stored number were reported as it stands.
    """
    factory, ws = _factory_with_workspace()
    svc = ProjectService(factory)
    project = await svc.create_project(ws.id, "Apollo", leader_description="Leads.")
    for i in range(3):
        m = Marius(workspace_id=ws.id, name=f"Agent {i}", liveness=Liveness.ONLINE)
        factory.store.mariuses[m.id] = m
        await svc.add_member(project.id, m.id)

    bench = next(r for r in await svc.get_roster(project.id) if r.key == MEMBERS_ROLE_KEY)
    assert (bench.seats, bench.filled) == (3, 3)


async def test_an_agent_taken_off_the_project_leaves_no_seat_behind() -> None:
    factory, ws = _factory_with_workspace()
    svc = ProjectService(factory)
    project = await svc.create_project(ws.id, "Apollo", leader_description="Leads.")
    m = _seed_marius(factory, ws, Liveness.ONLINE)
    await svc.add_member(project.id, m.id)

    gone = await svc.remove_member(project.id, m.id)

    assert gone.marius_id == m.id
    assert await svc.list_seat_grants(project.id) == []
    with pytest.raises(NotFound):
        await svc.remove_member(project.id, m.id)


async def test_the_leader_is_not_also_a_member() -> None:
    """Refused rather than seated twice: the agent is already on this project."""
    factory, ws = _factory_with_workspace()
    svc = ProjectService(factory)
    project = await svc.create_project(ws.id, "Apollo", leader_description="Leads.")
    m = _seed_marius(factory, ws, Liveness.ONLINE)
    await svc.seat_leader(project.id, m.id)

    with pytest.raises(BadRequest) as caught:
        await svc.add_member(project.id, m.id)
    assert caught.value.code == "agent_leads_this_project"
    assert len(await svc.list_seat_grants(project.id)) == 1


async def test_revoke_seat_is_system_only_and_leaves_nothing_behind() -> None:
    """T199 — trả ghế là **xoá dòng**: không còn dòng chết để ai đó quên lọc."""
    factory, ws = _factory_with_workspace()
    svc = ProjectService(factory)
    project = await svc.create_project(ws.id, "Apollo", leader_description="Leads.")
    m = _seed_marius(factory, ws, Liveness.ONLINE)
    grant = await svc.seat_leader(project.id, m.id)

    with pytest.raises(SystemOnlyOperation):
        await svc.revoke_seat(grant.id)  # non-system

    vacated = await svc.revoke_seat(grant.id, system=True)
    assert vacated.id == grant.id
    assert await svc.list_seat_grants(project.id) == []
    with pytest.raises(NotFound):
        await svc.revoke_seat(grant.id, system=True)  # the seat is gone
