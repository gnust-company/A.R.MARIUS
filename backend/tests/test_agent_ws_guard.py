"""Agent ws-consistency guard (#15) — a per-workspace token can't touch another
workspace's tasks through /agent/tasks/*; same-workspace access keeps working."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.database.engine import init_db
from armarius.main import app
from armarius.presentation.container import build_container
from tests.support.agents import agent_token_for, invite_agent
from tests.support.projects import force_operating


@pytest.fixture(autouse=True)
async def _bootstrap():
    await init_db()
    container = build_container()
    container.registry.register(EchoAdapter(step_delay=0.0))  # instant setup-push (#63)
    app.state.container = container
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
    """Invite a Marius with gateway creds; return its (repo-read) agent_token (#63)."""
    created = await invite_agent(c, ws_id, h, name=name)
    return await agent_token_for(created["id"])


async def _make_project(c: AsyncClient, h: dict, ws_id: str) -> str:
    project = await c.post(
        f"/v1/workspaces/{ws_id}/projects",
        headers=h,
        json={
            "name": "Guarded",
            "objective": "Guard test",
            "leader": {"description": "lead", "marius_id": None},
            "roles": [{"title": "Backend", "seats": 1, "description": "Owns the API."}],
        },
    )
    assert project.status_code == 201, project.text
    # FR-003 — this file tests the agent-token workspace guard, not the plan gate.
    await force_operating(project.json()["id"])
    return project.json()["id"]


async def _make_task(c: AsyncClient, h: dict, ws_id: str) -> tuple[str, str]:
    """A live task in a fresh project. Returns (project_id, task_id)."""
    project_id = await _make_project(c, h, ws_id)
    task = await c.post(
        f"/v1/projects/{project_id}/tasks", headers=h, json={"title": "T"}
    )
    assert task.status_code == 201, task.text
    task_id = task.json()["id"]
    # backlog → todo so an agent has something live to act on.
    moved = await c.post(
        f"/v1/tasks/{task_id}/status", headers=h, json={"status": "todo"}
    )
    assert moved.status_code == 200, moved.text
    return project_id, task_id


async def test_agent_token_is_confined_to_its_workspace():
    async with await _client() as c:
        # Workspace A holds the task; workspace B holds the intruding agent.
        token_a, ws_a = await _register(c, "guard-a@armarius.dev")
        ha = {"Authorization": f"Bearer {token_a}"}
        _, task_id = await _make_task(c, ha, ws_a)

        token_b, ws_b = await _register(c, "guard-b@armarius.dev")
        hb = {"Authorization": f"Bearer {token_b}"}
        intruder = await _provision_agent(c, hb, ws_b, "Mallory")
        ih = {"Authorization": f"Bearer {intruder}"}

        # Every /agent/tasks/* route answers 404 — the task does not exist for
        # this token, whether reading or writing.
        probes = [
            c.get(f"/agent/tasks/{task_id}", headers=ih),
            c.post(f"/agent/tasks/{task_id}/request", headers=ih, json={}),
            c.post(
                f"/agent/tasks/{task_id}/handback", headers=ih, json={"reason": "x"}
            ),
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
        asked = await c.post(f"/agent/tasks/{task_id}/request", headers=ah, json={})
        assert asked.status_code == 200, asked.text
        # Asking changes nothing about who owns the work — that is the Leader's call.
        assert asked.json()["assigned_marius_id"] is None


async def test_every_door_opened_for_autonomous_operation_is_confined_too():
    """T156 — the same guarantee, checked against the doors spec 001 added.

    The original test covered the seven `/agent/tasks/*` routes that existed when the
    guard was written. Autonomous operation opened eleven more, several of them
    project-scoped rather than task-scoped, and a guard is only worth what its least
    covered door is worth: one route resolving by id alone re-opens everything the other
    twenty close.

    Every probe below is a *stranger's* agent token pointed at workspace A's rows. All
    must read *not found* — never *forbidden*, which would confirm the row exists
    (FR-081, Hiến pháp I).
    """
    async with await _client() as c:
        token_a, ws_a = await _register(c, "doors-a@armarius.dev")
        ha = {"Authorization": f"Bearer {token_a}"}
        project_id, task_id = await _make_task(c, ha, ws_a)

        token_b, ws_b = await _register(c, "doors-b@armarius.dev")
        hb = {"Authorization": f"Bearer {token_b}"}
        intruder = await _provision_agent(c, hb, ws_b, "Mallory")
        ih = {"Authorization": f"Bearer {intruder}"}

        probes = [
            # task-scoped (Đợt 5–6: the ladder's two doors out of Mức 2)
            c.post(
                f"/agent/tasks/{task_id}/recovery",
                headers=ih,
                json={"action": "reassign to me"},
            ),
            c.post(
                f"/agent/tasks/{task_id}/escalate",
                headers=ih,
                json={"reason": "beyond me"},
            ),
            c.post(
                f"/agent/tasks/{task_id}/approval",
                headers=ih,
                json={"approve": True},
            ),
            # project-scoped (Đợt 1–4: brief, plan, phase, batch wrap-up, scope change)
            c.get(f"/agent/projects/{project_id}/queue", headers=ih),
            c.post(
                f"/agent/projects/{project_id}/tasks",
                headers=ih,
                json={"title": "smuggled"},
            ),
            c.post(
                f"/agent/projects/{project_id}/change-request",
                headers=ih,
                json={"area": "scope", "summary": "widen it"},
            ),
            c.post(
                f"/agent/projects/{project_id}/context",
                headers=ih,
                json={"objective": "o", "background": "b"},
            ),
            c.post(
                f"/agent/projects/{project_id}/plan",
                headers=ih,
                json={"summary": "s", "items": []},
            ),
            c.post(
                f"/agent/projects/{project_id}/phase-proposal",
                headers=ih,
                json={"target_phase": "maintaining", "reason": "r"},
            ),
            c.post(
                f"/agent/projects/{project_id}/sprint-summary",
                headers=ih,
                json={"summary": "done"},
            ),
        ]
        for coro in probes:
            r = await coro
            assert r.status_code == 404, f"{r.request.url} → {r.status_code}: {r.text}"

        # Positive control: A's own agent reaches the project-scoped read. It holds no
        # leader seat, so the leader-only doors stay shut for it too — but as *not found*,
        # which is the same answer the stranger got and deliberately so (Constitution V).
        insider = await _provision_agent(c, ha, ws_a, "Alice")
        aih = {"Authorization": f"Bearer {insider}"}
        own = await c.get(f"/agent/projects/{project_id}/queue", headers=aih)
        assert own.status_code == 200, own.text
