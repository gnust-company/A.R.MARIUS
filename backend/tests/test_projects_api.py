"""Contract-conformance — Projects + Roster + Grant (API_CONTRACT §3).

Drives the roster-driven ProjectService over HTTP: create-with-seat-plan (and the hard
422 composition rule), project detail/brief/delete, roster CRUD by role_key, system-only
seat grants, SETUP→ACTIVE activation, and workspace scoping (cross-workspace = 404).
"""

from __future__ import annotations

from uuid import UUID

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from armarius.infrastructure.database import engine as engine_mod
from armarius.infrastructure.database.models import (
    ArtifactModel,
    RoleModel,
    SeatGrantModel,
    TaskModel,
)
from armarius.main import app


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(c: AsyncClient, email: str) -> tuple[str, str]:
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["tokens"]["access_token"]
    ws = await c.get("/v1/workspaces", headers={"Authorization": f"Bearer {token}"})
    return token, ws.json()[0]["id"]


def _plan(**overrides) -> dict:
    plan = {
        "name": "Apollo",
        "description": "ship it",
        "objective": "Launch the platform",
        "leader": {"responsibilities": "lead", "marius_id": None},
        "roles": [{"title": "Backend", "seats": 1}],
    }
    plan.update(overrides)
    return plan


async def _create(c: AsyncClient, ws_id: str, h: dict, **overrides) -> dict:
    r = await c.post(
        f"/v1/workspaces/{ws_id}/projects", headers=h, json=_plan(**overrides)
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _online_agent(c: AsyncClient, ws_id: str, h: dict, name: str) -> str:
    """Invite with gateway creds → /agent/me (a signal) so the agent is ONLINE (#63)."""
    from tests.support.agents import invite_and_online

    mid, _token = await invite_and_online(c, ws_id, h, name=name)
    return mid


async def test_create_with_plan_starts_setup_with_roster() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "p1@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        proj = await _create(c, ws_id, h)
    assert proj["status"] == "setup"
    assert proj["objective"] == "Launch the platform"
    keys = {r["key"] for r in proj["roster"]}
    assert keys == {"leader", "backend"}
    leader = next(r for r in proj["roster"] if r["key"] == "leader")
    assert leader["is_leader"] is True and leader["seats"] == 1


async def test_list_projects_exposes_status() -> None:
    """Sprint 6 review fix: the project LIST endpoint exposes `status` so the FE grid
    renders a real status chip — previously `ProjectOut` dropped it and the FE showed the
    raw `projects.status.undefined` i18n key.
    """
    async with await _client() as c:
        token, ws_id = await _register(c, "liststatus@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        await _create(c, ws_id, h)
        listed = (await c.get(f"/v1/workspaces/{ws_id}/projects", headers=h)).json()
    assert listed, "expected the created project in the list"
    assert listed[0]["status"] == "setup"


async def test_list_projects_exposes_seat_counts() -> None:
    """The project LIST endpoint carries roster fill (seats_filled / seats_total) so the grid
    card shows the real count without opening the detail — previously the card read 0/0 for
    every un-opened project because `ProjectOut` had no seat data.
    """
    async with await _client() as c:
        token, ws_id = await _register(c, "seatcounts@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        proj = await _create(c, ws_id, h)  # leader (1) + backend (1) = 2 seats, 0 filled
        pid = proj["id"]

        listed = (await c.get(f"/v1/workspaces/{ws_id}/projects", headers=h)).json()
        assert listed[0]["seats_total"] == 2
        assert listed[0]["seats_filled"] == 0

        # Seat an agent in the leader role → the list reflects the new fill.
        lead = await _online_agent(c, ws_id, h, "Lead")
        grant = await c.post(
            f"/v1/projects/{pid}/grant",
            headers=h,
            json={"marius_id": lead, "role_key": "leader"},
        )
        assert grant.status_code == 201, grant.text

        listed2 = (await c.get(f"/v1/workspaces/{ws_id}/projects", headers=h)).json()
        assert listed2[0]["seats_total"] == 2
        assert listed2[0]["seats_filled"] == 1


async def test_create_without_worker_role_is_422() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "p2@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        r = await c.post(
            f"/v1/workspaces/{ws_id}/projects", headers=h, json=_plan(roles=[])
        )
    assert r.status_code == 422, r.text


async def test_detail_patch_brief_and_delete() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "p3@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        proj = await _create(c, ws_id, h)
        pid = proj["id"]

        patched = await c.patch(
            f"/v1/projects/{pid}",
            headers=h,
            json={"github_url": "https://github.com/acme/apollo", "objective": "v2"},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["github_url"] == "https://github.com/acme/apollo"
        assert patched.json()["objective"] == "v2"

        deleted = await c.delete(f"/v1/projects/{pid}", headers=h)
        assert deleted.status_code == 204
        gone = await c.get(f"/v1/projects/{pid}", headers=h)
    assert gone.status_code == 404


async def test_roster_role_crud_by_key() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "p4@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        pid = (await _create(c, ws_id, h))["id"]

        added = await c.post(
            f"/v1/projects/{pid}/roles", headers=h, json={"title": "QA", "seats": 2}
        )
        assert added.status_code == 201, added.text
        assert added.json()["key"] == "qa"

        edited = await c.patch(
            f"/v1/projects/{pid}/roles/qa",
            headers=h,
            json={"seats": 3, "title": "Quality"},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["seats"] == 3 and edited.json()["title"] == "Quality"

        removed = await c.delete(f"/v1/projects/{pid}/roles/qa", headers=h)
        assert removed.status_code == 204
        roster = await c.get(f"/v1/projects/{pid}/roster", headers=h)
    assert "qa" not in {r["key"] for r in roster.json()}


async def test_grant_is_system_only_and_lists_agent() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "p5@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        pid = (await _create(c, ws_id, h))["id"]
        mid = await _online_agent(c, ws_id, h, "Backend-1")

        grant = await c.post(
            f"/v1/projects/{pid}/grant",
            headers=h,
            json={"marius_id": mid, "role_key": "backend"},
        )
        assert grant.status_code == 201, grant.text
        assert grant.json()["status"] == "granted"

        agents = await c.get(f"/v1/projects/{pid}/agents", headers=h)
        assert agents.status_code == 200
        assert [a["marius_id"] for a in agents.json()] == [mid]

        revoke = await c.request(
            "DELETE",
            f"/v1/projects/{pid}/grant",
            headers=h,
            json={"marius_id": mid, "role_key": "backend"},
        )
        assert revoke.status_code == 200, revoke.text
        assert revoke.json()["status"] == "revoked"
        agents2 = await c.get(f"/v1/projects/{pid}/agents", headers=h)
    assert agents2.json() == []


async def test_remove_role_while_seated_is_rejected() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "p6@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        pid = (await _create(c, ws_id, h))["id"]
        mid = await _online_agent(c, ws_id, h, "Backend-1")
        await c.post(
            f"/v1/projects/{pid}/grant",
            headers=h,
            json={"marius_id": mid, "role_key": "backend"},
        )
        r = await c.delete(f"/v1/projects/{pid}/roles/backend", headers=h)
    assert r.status_code == 400, r.text


async def test_add_duplicate_role_key_is_409() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "dup@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        pid = (await _create(c, ws_id, h))["id"]  # roster already has key "backend"
        # A second role that slugs to the same key must be rejected, not silently duplicated.
        r = await c.post(
            f"/v1/projects/{pid}/roles", headers=h, json={"title": "Backend", "seats": 1}
        )
    assert r.status_code == 409, r.text


async def test_add_role_with_long_title_caps_key_length() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "longkey@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        pid = (await _create(c, ws_id, h))["id"]
        # A 200-char title (allowed by the schema) must not overflow RoleModel.key (120).
        r = await c.post(
            f"/v1/projects/{pid}/roles", headers=h, json={"title": "Q" * 200, "seats": 1}
        )
    assert r.status_code == 201, r.text
    assert len(r.json()["key"]) <= 120


async def test_delete_project_cascades_children() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "cascade@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        pid = (await _create(c, ws_id, h))["id"]
        mid = await _online_agent(c, ws_id, h, "Backend-1")
        await c.post(
            f"/v1/projects/{pid}/grant",
            headers=h,
            json={"marius_id": mid, "role_key": "backend"},
        )
        task = await c.post(f"/v1/projects/{pid}/tasks", headers=h, json={"title": "T"})
        task_id = task.json()["id"]
        art = await c.post(
            f"/v1/tasks/{task_id}/artifacts",
            headers=h,
            json={"name": "PR", "kind": "link", "uri": "https://github.com/a/b/pull/1"},
        )
        assert art.status_code == 201, art.text

        deleted = await c.delete(f"/v1/projects/{pid}", headers=h)
        assert deleted.status_code == 204, deleted.text

    # No orphaned children remain (the bug SQLite hides with FK enforcement off; on
    # Postgres a bare project delete would instead 500 on the FK constraint).
    sm = engine_mod.get_sessionmaker()
    async with sm() as s:
        pid_u, task_u = UUID(pid), UUID(task_id)
        roles = await s.scalar(
            select(func.count()).select_from(RoleModel).where(RoleModel.project_id == pid_u)
        )
        grants = await s.scalar(
            select(func.count())
            .select_from(SeatGrantModel)
            .where(SeatGrantModel.project_id == pid_u)
        )
        tasks = await s.scalar(
            select(func.count()).select_from(TaskModel).where(TaskModel.project_id == pid_u)
        )
        arts = await s.scalar(
            select(func.count())
            .select_from(ArtifactModel)
            .where(ArtifactModel.task_id == task_u)
        )
    assert (roles, grants, tasks, arts) == (0, 0, 0, 0)


async def test_all_seats_granted_to_online_agents_activates() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "p7@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        pid = (await _create(c, ws_id, h))["id"]
        leader = await _online_agent(c, ws_id, h, "Lead")
        worker = await _online_agent(c, ws_id, h, "Worker")

        await c.post(
            f"/v1/projects/{pid}/grant",
            headers=h,
            json={"marius_id": leader, "role_key": "leader"},
        )
        mid_detail = await c.get(f"/v1/projects/{pid}", headers=h)
        assert mid_detail.json()["status"] == "setup"  # one seat still empty

        await c.post(
            f"/v1/projects/{pid}/grant",
            headers=h,
            json={"marius_id": worker, "role_key": "backend"},
        )
        final = await c.get(f"/v1/projects/{pid}", headers=h)
    assert final.json()["status"] == "active"


async def test_cross_workspace_project_is_404() -> None:
    async with await _client() as c:
        token_a, ws_a = await _register(c, "owner@armarius.dev")
        ha = {"Authorization": f"Bearer {token_a}"}
        pid = (await _create(c, ws_a, ha))["id"]

        token_b, _ = await _register(c, "intruder@armarius.dev")
        hb = {"Authorization": f"Bearer {token_b}"}
        r = await c.get(f"/v1/projects/{pid}", headers=hb)
    assert r.status_code == 404, r.text


async def test_create_task_carries_full_definition() -> None:
    """A manually created task persists its full definition — priority/due_date/
    definition_of_done/assigned_marius_id — not just title+description, and TaskOut returns
    them. A task is more than a title (#82)."""
    async with await _client() as c:
        token, ws_id = await _register(c, "taskdef@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        pid = (await _create(c, ws_id, h))["id"]
        mid = await _online_agent(c, ws_id, h, "Doer-1")
        body = {
            "title": "Ship the calculator",
            "description": "Basic + - × ÷",
            "priority": "high",
            "due_date": "2026-08-01T00:00:00+00:00",
            "definition_of_done": "All operations pass and it is deployed",
            "assigned_marius_id": mid,
        }
        created = await c.post(f"/v1/projects/{pid}/tasks", headers=h, json=body)
        assert created.status_code == 201, created.text
        out = created.json()
        assert out["priority"] == "high"
        assert out["due_date"] is not None
        assert out["definition_of_done"] == "All operations pass and it is deployed"
        assert out["assigned_marius_id"] == mid

        # The definition survives the SQL round-trip (the new columns actually persist).
        got = (await c.get(f"/v1/tasks/{out['id']}", headers=h)).json()
        assert got["priority"] == "high"
        assert got["definition_of_done"] == "All operations pass and it is deployed"
        assert got["assigned_marius_id"] == mid


async def test_create_task_lands_in_supplied_status() -> None:
    """The board's per-column "+" passes `status` so a task lands in the right column, not
    always backlog. Omitting status still defaults to backlog (#82)."""
    async with await _client() as c:
        token, ws_id = await _register(c, "taskcol@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        pid = (await _create(c, ws_id, h))["id"]

        in_progress = await c.post(
            f"/v1/projects/{pid}/tasks",
            headers=h,
            json={"title": "Already going", "status": "in_progress"},
        )
        assert in_progress.status_code == 201, in_progress.text
        assert in_progress.json()["status"] == "in_progress"

        defaulted = await c.post(
            f"/v1/projects/{pid}/tasks", headers=h, json={"title": "Just an idea"}
        )
        assert defaulted.status_code == 201, defaulted.text
        assert defaulted.json()["status"] == "backlog"

