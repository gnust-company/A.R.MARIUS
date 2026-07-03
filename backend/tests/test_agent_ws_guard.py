"""Agent ws-consistency guard (#15) — a per-workspace token can't touch another
workspace's tasks through /agent/tasks/*; same-workspace access keeps working."""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.infrastructure.database.engine import init_db
from armarius.main import app
from armarius.presentation.container import build_container


@pytest.fixture(autouse=True)
async def _bootstrap():
    await init_db()
    app.state.container = build_container()
    yield


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(c: AsyncClient, email: str) -> tuple[str, str]:
    """Register a user; return (access_token, workspace_id)."""
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["tokens"]["access_token"]
    ws = await c.get("/v1/workspaces", headers={"Authorization": f"Bearer {token}"})
    assert ws.status_code == 200
    return token, ws.json()[0]["id"]


async def _provision_agent(c: AsyncClient, h: dict, ws_id: str, name: str) -> str:
    """Invite + enroll + approve a Marius; return its agent_token."""
    created = (
        await c.post(
            f"/v1/workspaces/{ws_id}/mariuses",
            headers=h,
            json={"name": name, "role": "", "skills": [], "skill_ids": [],
                  "adapter_type": "echo", "adapter_config": {}},
        )
    ).json()
    mid, code = created["id"], created["enrollment_code"]
    # enroll holds until approval — run the patron's approve concurrently.
    enroll_task = asyncio.create_task(
        c.post("/agent/enroll", json={"marius_id": mid, "enrollment_code": code})
    )
    for _ in range(100):
        r = await c.post(f"/v1/workspaces/{ws_id}/mariuses/{mid}/approve", headers=h)
        if r.status_code == 200:
            break
        await asyncio.sleep(0.02)
    else:
        raise AssertionError("approve never reached pending_review")
    enrolled = await asyncio.wait_for(enroll_task, timeout=10)
    assert enrolled.status_code == 200, enrolled.text
    return enrolled.json()["agent_token"]


async def _make_task(c: AsyncClient, h: dict, ws_id: str) -> str:
    project = await c.post(
        f"/v1/workspaces/{ws_id}/projects",
        headers=h,
        json={
            "name": "Guarded",
            "objective": "Guard test",
            "leader": {"responsibilities": "lead", "marius_id": None},
            "roles": [{"title": "Backend", "seats": 1}],
        },
    )
    assert project.status_code == 201, project.text
    task = await c.post(
        f"/v1/projects/{project.json()['id']}/tasks", headers=h, json={"title": "T"}
    )
    assert task.status_code == 201, task.text
    task_id = task.json()["id"]
    # backlog → todo so an agent can claim it (backlog tasks aren't claimable).
    moved = await c.post(
        f"/v1/tasks/{task_id}/status", headers=h, json={"status": "todo"}
    )
    assert moved.status_code == 200, moved.text
    return task_id


async def test_agent_token_is_confined_to_its_workspace():
    async with await _client() as c:
        # Workspace A holds the task; workspace B holds the intruding agent.
        token_a, ws_a = await _register(c, "guard-a@armarius.dev")
        ha = {"Authorization": f"Bearer {token_a}"}
        task_id = await _make_task(c, ha, ws_a)

        token_b, ws_b = await _register(c, "guard-b@armarius.dev")
        hb = {"Authorization": f"Bearer {token_b}"}
        intruder = await _provision_agent(c, hb, ws_b, "Mallory")
        ih = {"Authorization": f"Bearer {intruder}"}

        # Every /agent/tasks/* route answers 404 — the task does not exist for
        # this token, whether reading or writing.
        probes = [
            c.get(f"/agent/tasks/{task_id}", headers=ih),
            c.post(f"/agent/tasks/{task_id}/claim", headers=ih, json={}),
            c.post(f"/agent/tasks/{task_id}/comment", headers=ih, json={"body": "hi"}),
            c.post(
                f"/agent/tasks/{task_id}/status",
                headers=ih,
                json={"status": "in_progress", "reason": "x"},
            ),
            c.post(
                f"/agent/tasks/{task_id}/next-action",
                headers=ih,
                json={"next_action": "x"},
            ),
            c.post(
                f"/agent/tasks/{task_id}/artifact",
                headers=ih,
                json={"name": "n", "kind": "note", "content": "x"},
            ),
        ]
        for coro in probes:
            r = await coro
            assert r.status_code == 404, f"{r.request.url} → {r.status_code}: {r.text}"

        # Positive control: the workspace's own agent still works the task.
        insider = await _provision_agent(c, ha, ws_a, "Alice")
        ah = {"Authorization": f"Bearer {insider}"}
        assert (await c.get(f"/agent/tasks/{task_id}", headers=ah)).status_code == 200
        claimed = await c.post(f"/agent/tasks/{task_id}/claim", headers=ah, json={})
        assert claimed.status_code == 200, claimed.text
        assert claimed.json()["status"] == "in_progress"
