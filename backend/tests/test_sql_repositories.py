"""Sprint 3 — SQLAlchemy persistence round-trips for the new roster/brief/liveness state.

These drive the *real* `SqlAlchemyUnitOfWork` (SQLite via the `uow_factory` fixture), so
they catch what the in-memory fakes cannot: detached-entity writes, column mapping, and
that a `recompute_active` flip is actually flushed to the database.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from armarius.application.use_cases.projects import ProjectService, RoleSpec
from armarius.domain.entities.marius import InviteStatus, Liveness, Marius
from armarius.domain.entities.project import Project, ProjectStatus
from armarius.domain.entities.seat_grant import SeatGrant, SeatGrantStatus
from armarius.domain.entities.workspace import Workspace
from armarius.shared.clock import utcnow

# Naive on purpose: SQLite's DateTime(timezone=True) drops tzinfo on read-back (Postgres
# preserves it), so we assert value fidelity here, not timezone fidelity.
_T = datetime(2026, 1, 1, 12, 0, 0)


async def _seed_workspace(factory) -> Workspace:
    ws = Workspace(name="Studio", slug="studio", owner_user_id="u1")
    async with factory() as uow:
        await uow.workspaces.add(ws)
        await uow.commit()
    return ws


async def _seed_marius(factory, ws_id, liveness: Liveness) -> Marius:
    m = Marius(workspace_id=ws_id, name="Agent", role="Worker", liveness=liveness)
    async with factory() as uow:
        await uow.mariuses.add(m)
        await uow.commit()
    return m


def _valid_roster() -> list[RoleSpec]:
    return [
        RoleSpec(key="leader", title="Leader", seats=1, is_leader=True),
        RoleSpec(key="backend", title="Backend", seats=1, skill_ids=[str(uuid4())]),
    ]


async def test_roster_persists_and_reloads(uow_factory) -> None:
    ws = await _seed_workspace(uow_factory)
    svc = ProjectService(uow_factory)

    project = await svc.create_project(ws.id, "Apollo", roles=_valid_roster())

    # Reload through a fresh UoW — proves the roster hit the database, not just memory.
    roles = await svc.list_roles(project.id)
    by_key = {r.key: r for r in roles}
    assert set(by_key) == {"leader", "backend"}
    assert by_key["leader"].is_leader is True
    assert by_key["leader"].seats == 1
    assert len(by_key["backend"].skill_ids) == 1
    assert all(r.project_id == project.id for r in roles)


async def test_activation_flip_persists_to_db(uow_factory) -> None:
    ws = await _seed_workspace(uow_factory)
    svc = ProjectService(uow_factory)
    project = await svc.create_project(ws.id, "Apollo", roles=_valid_roster())
    leader = await _seed_marius(uow_factory, ws.id, Liveness.ONLINE)
    worker = await _seed_marius(uow_factory, ws.id, Liveness.ONLINE)

    await svc.grant_seat(project.id, "leader", leader.id, system=True)
    async with uow_factory() as uow:
        assert (await uow.projects.get(project.id)).status == ProjectStatus.SETUP

    await svc.grant_seat(project.id, "backend", worker.id, system=True)

    # Re-read from a brand-new UoW: the SETUP→ACTIVE flip must be durable.
    async with uow_factory() as uow:
        reloaded = await uow.projects.get(project.id)
    assert reloaded.status == ProjectStatus.ACTIVE


async def test_project_brief_round_trips(uow_factory) -> None:
    ws = await _seed_workspace(uow_factory)
    project = Project(
        workspace_id=ws.id,
        name="Apollo",
        slug="apollo",
        description="ship it",
        objective="Launch the platform",
        success_metrics={"signups": 1000},
        target_date=_T,
        github_url="https://github.com/acme/apollo",
        context="greenfield",
        settings={"require_review_before_done": False},
        status=ProjectStatus.ACTIVE,
        created_by_user_id="u1",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    async with uow_factory() as uow:
        await uow.projects.add(project)
        await uow.commit()

    async with uow_factory() as uow:
        got = await uow.projects.get(project.id)
    assert got.objective == "Launch the platform"
    assert got.success_metrics == {"signups": 1000}
    assert got.target_date == _T
    assert got.github_url == "https://github.com/acme/apollo"
    assert got.context == "greenfield"
    assert got.settings == {"require_review_before_done": False}
    assert got.status == ProjectStatus.ACTIVE
    assert got.created_by_user_id == "u1"


async def test_marius_invite_and_liveness_timers_round_trip(uow_factory) -> None:
    ws = await _seed_workspace(uow_factory)
    m = Marius(
        workspace_id=ws.id,
        name="Hermes",
        role="Backend",
        agent_token="arm_secrettoken",
        invite_status=InviteStatus.APPROVED,
        enrollment_code="enr-code-123",
        approved_at=_T,
        liveness=Liveness.CHECKING,
        last_seen_at=_T,
        probe_attempts=2,
        backoff_step=1,
        next_probe_at=_T,
        offline_since=_T,
        turn_started_at=_T,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    async with uow_factory() as uow:
        await uow.mariuses.add(m)
        await uow.commit()

    async with uow_factory() as uow:
        got = await uow.mariuses.get(m.id)
    assert got.invite_status == InviteStatus.APPROVED
    assert got.enrollment_code == "enr-code-123"
    assert got.approved_at == _T
    assert got.agent_token == "arm_secrettoken"
    assert got.liveness == Liveness.CHECKING
    assert got.probe_attempts == 2
    assert got.backoff_step == 1
    assert got.next_probe_at == _T
    assert got.offline_since == _T
    assert got.turn_started_at == _T


async def test_seat_grant_round_trip_and_revoke(uow_factory) -> None:
    ws = await _seed_workspace(uow_factory)
    project = Project(workspace_id=ws.id, name="Apollo", slug="apollo")
    async with uow_factory() as uow:
        await uow.projects.add(project)
        await uow.commit()

    grant = SeatGrant(
        project_id=project.id,
        role_key="leader",
        marius_id=uuid4(),
        status=SeatGrantStatus.GRANTED,
        granted_at=_T,
        created_at=_T,
    )
    async with uow_factory() as uow:
        await uow.seat_grants.add(grant)
        await uow.commit()

    async with uow_factory() as uow:
        grants = await uow.seat_grants.list_by_project(project.id)
        assert len(grants) == 1
        reloaded = grants[0]
        assert reloaded.role_key == "leader"
        assert reloaded.status == SeatGrantStatus.GRANTED
        reloaded.revoke()
        await uow.seat_grants.update(reloaded)
        await uow.commit()

    async with uow_factory() as uow:
        after = await uow.seat_grants.get(grant.id)
    assert after.status == SeatGrantStatus.REVOKED
