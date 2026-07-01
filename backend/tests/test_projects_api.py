"""Contract-conformance — Projects + Roster + Grant (API_CONTRACT §3).

Drives the roster-driven ProjectService over HTTP: create-with-seat-plan (and the hard
422 composition rule), project detail/brief/delete, roster CRUD by role_key, system-only
seat grants, SETUP→ACTIVE activation, and workspace scoping (cross-workspace = 404).
"""

from __future__ import annotations

import asyncio
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
    """Invite → enroll(held) → approve → /agent/me (a signal) so the agent is ONLINE."""
    inv = (
        await c.post(
            f"/v1/workspaces/{ws_id}/mariuses",
            headers=h,
            json={"name": name, "role": "Worker", "adapter_type": "echo", "adapter_config": {}},
        )
    ).json()
    mid, code = inv["id"], inv["enrollment_code"]
    enroll_task = asyncio.create_task(
        c.post("/agent/enroll", json={"marius_id": mid, "enrollment_code": code})
    )
    await asyncio.sleep(0.05)
    for _ in range(100):
        r = await c.post(f"/v1/workspaces/{ws_id}/mariuses/{mid}/approve", headers=h)
        if r.status_code == 200:
            break
        await asyncio.sleep(0.02)
    agent_token = (await asyncio.wait_for(enroll_task, timeout=5)).json()["agent_token"]
    await c.get("/agent/me", headers={"Authorization": f"Bearer {agent_token}"})
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
