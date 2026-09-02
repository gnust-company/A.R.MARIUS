"""Sprint 3 — SQLAlchemy persistence round-trips for the new roster/brief/liveness state.

These drive the *real* `SqlAlchemyUnitOfWork` (SQLite via the `uow_factory` fixture), so
they catch what the in-memory fakes cannot: detached-entity writes, column mapping, and
that a `recompute_active` flip is actually flushed to the database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from armarius.application.use_cases.projects import ProjectService, RoleSpec
from armarius.domain.entities.marius import InviteStatus, Liveness, Marius
from armarius.domain.entities.project import Project, ProjectStatus
from armarius.domain.entities.role import Role
from armarius.domain.entities.seat_grant import SeatGrant
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


async def _seed_marius(factory, ws_id, liveness: Liveness, name: str = "Agent") -> Marius:
    # The name has to be given when a test seeds two of these: one name answers for one agent
    # inside a workspace, and the database is what says so (FR-007h).
    m = Marius(workspace_id=ws_id, name=name, role="Worker", liveness=liveness)
    async with factory() as uow:
        await uow.mariuses.add(m)
        await uow.commit()
    return m


def _valid_roster() -> list[RoleSpec]:
    return [
        RoleSpec(key="leader", title="Leader", seats=1, is_leader=True, description="Leads."),
        RoleSpec(key="backend", title="Backend", seats=1, description="Owns the API.",
                 skill_ids=[str(uuid4())]),
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
    leader = await _seed_marius(uow_factory, ws.id, Liveness.ONLINE, name="Lead")
    worker = await _seed_marius(uow_factory, ws.id, Liveness.ONLINE, name="Worker")

    await svc.grant_seat(project.id, "leader", leader.id, system=True)
    async with uow_factory() as uow:
        assert (await uow.projects.get(project.id)).status == ProjectStatus.SETUP

    await svc.grant_seat(project.id, "backend", worker.id, system=True)

    # Re-read from a brand-new UoW: the SETUP→ACTIVE flip must be durable.
    async with uow_factory() as uow:
        reloaded = await uow.projects.get(project.id)
    assert reloaded.status == ProjectStatus.PLANNING


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
        status=ProjectStatus.PLANNING,
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
    assert got.status == ProjectStatus.PLANNING
    assert got.created_by_user_id == "u1"


async def test_marius_invite_and_liveness_timers_round_trip(uow_factory) -> None:
    ws = await _seed_workspace(uow_factory)
    m = Marius(
        workspace_id=ws.id,
        name="Marin",
        role="Backend",
        agent_token="arm_secrettoken",
        invite_status=InviteStatus.APPROVED,
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
    assert got.approved_at == _T
    assert got.agent_token == "arm_secrettoken"
    assert got.liveness == Liveness.CHECKING
    assert got.probe_attempts == 2
    assert got.backoff_step == 1
    # Bốn mốc thời gian mà luật liveness đem ra trừ nhau đọc lên **luôn** có múi giờ, dù
    # ghi xuống kiểu gì và dù nằm trên engine nào. Cột khai là có múi giờ, PostgreSQL tôn
    # trọng còn SQLite thì không, nên nếu để nguyên như đọc được thì cùng một hàng về hai
    # dạng khác nhau ở hai nơi — và trừ nó cho `utcnow()` thì **nổ**, chứ không phải sai
    # âm thầm. Chuẩn hoá ở biên chính là điều `shared/clock` viết ra để nói.
    aware = _T.replace(tzinfo=UTC)
    assert got.last_seen_at == aware
    assert got.next_probe_at == aware
    assert got.offline_since == aware
    assert got.turn_started_at == aware


async def test_seat_grant_round_trip_and_vacate(uow_factory) -> None:
    """T199 — một ghế là một dòng sống; trả ghế là xoá dòng, không phải đổi cờ."""
    ws = await _seed_workspace(uow_factory)
    agent = await _seed_marius(uow_factory, ws.id, Liveness.ONLINE)
    project = Project(workspace_id=ws.id, name="Apollo", slug="apollo")
    async with uow_factory() as uow:
        await uow.projects.add(project)
        role = await uow.roles.add(
            Role(project_id=project.id, key="leader", title="Leader", seats=1,
                 is_leader=True)
        )
        await uow.commit()

    grant = SeatGrant(
        project_id=project.id,
        role_id=role.id,
        marius_id=agent.id,
        granted_at=_T,
        created_at=_T,
    )
    async with uow_factory() as uow:
        await uow.seat_grants.add(grant)
        await uow.commit()

    async with uow_factory() as uow:
        grants = await uow.seat_grants.list_by_project(project.id)
        assert len(grants) == 1
        assert grants[0].role_id == role.id
        assert grants[0].marius_id == agent.id
        await uow.seat_grants.remove(grants[0].id)
        await uow.commit()

    async with uow_factory() as uow:
        assert await uow.seat_grants.get(grant.id) is None
        assert await uow.seat_grants.list_by_project(project.id) == []
