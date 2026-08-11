"""Patron-token workspace guard (T156, FR-081, Hiến pháp I).

The sibling of ``test_agent_ws_guard``: that one proves an *agent* token cannot leave its
workspace, this one proves a *patron* token cannot either. Both halves are needed — the
board, the task detail, the history and the run traces are all read through a patron
token, and a guard on only one of the two surfaces leaves the same rows reachable through
the other.

Two things are asserted about every route:

  * a stranger's token reads **404**, never 403 — *forbidden* would confirm the row is
    there, and that is the other tenant's fact to keep;
  * no token at all reads **401** — a route that names no caller is a route the auth
    dependency never runs for, which is how a read ends up open to anyone who can reach
    the port.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.database.engine import init_db
from armarius.main import app
from armarius.presentation.container import build_container
from tests.support.projects import force_operating


@pytest.fixture(autouse=True)
async def _bootstrap():
    await init_db()
    container = build_container()
    container.registry.register(EchoAdapter(step_delay=0.0))
    app.state.container = container
    yield


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(c: AsyncClient, email: str) -> tuple[dict, str]:
    """Register a patron; return (auth headers, their workspace id)."""
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    assert r.status_code == 201, r.text
    h = {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}
    ws = await c.get("/v1/workspaces", headers=h)
    assert ws.status_code == 200
    return h, ws.json()[0]["id"]


async def _project_with_task(c: AsyncClient, h: dict, ws_id: str) -> tuple[str, str]:
    project = await c.post(
        f"/v1/workspaces/{ws_id}/projects",
        headers=h,
        json={
            "name": "Private",
            "objective": "Nobody else's business",
            "leader": {"description": "lead", "marius_id": None},
            "roles": [{"title": "Backend", "seats": 1, "description": "Owns the API."}],
        },
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    await force_operating(project_id)
    task = await c.post(
        f"/v1/projects/{project_id}/tasks",
        headers=h,
        json={"title": "Confidential", "description": "Trade secret"},
    )
    assert task.status_code == 201, task.text
    return project_id, task.json()["id"]


def _reads(project_id: str, task_id: str) -> list[str]:
    """Every GET on the patron task surface, including the ones spec 001 added."""
    return [
        f"/v1/projects/{project_id}/tasks",
        f"/v1/projects/{project_id}/task-dependencies",
        f"/v1/tasks/{task_id}",
        f"/v1/tasks/{task_id}/approvals",
        f"/v1/tasks/{task_id}/criteria",
        f"/v1/tasks/{task_id}/dependencies",
        f"/v1/tasks/{task_id}/comments",
        f"/v1/tasks/{task_id}/artifacts",
        f"/v1/tasks/{task_id}/log",
        f"/v1/tasks/{task_id}/runs",
    ]


async def test_a_stranger_cannot_read_another_patrons_task():
    async with await _client() as c:
        ha, ws_a = await _register(c, "pat-a@armarius.dev")
        project_id, task_id = await _project_with_task(c, ha, ws_a)
        hb, _ = await _register(c, "pat-b@armarius.dev")

        for path in _reads(project_id, task_id):
            r = await c.get(path, headers=hb)
            assert r.status_code == 404, f"{path} → {r.status_code}: {r.text}"

        # Positive control: the owner still reads every one of them.
        for path in _reads(project_id, task_id):
            r = await c.get(path, headers=ha)
            assert r.status_code == 200, f"{path} → {r.status_code}: {r.text}"


async def test_a_stranger_cannot_move_another_patrons_task():
    async with await _client() as c:
        ha, ws_a = await _register(c, "pat-c@armarius.dev")
        project_id, task_id = await _project_with_task(c, ha, ws_a)
        hb, _ = await _register(c, "pat-d@armarius.dev")

        writes = [
            c.post(
                f"/v1/projects/{project_id}/tasks", headers=hb, json={"title": "theirs"}
            ),
            c.post(f"/v1/tasks/{task_id}/status", headers=hb, json={"status": "todo"}),
            c.post(
                f"/v1/tasks/{task_id}/reopen", headers=hb, json={"reason": "because"}
            ),
            c.post(f"/v1/tasks/{task_id}/approval", headers=hb, json={"approve": True}),
            c.put(
                f"/v1/tasks/{task_id}/criteria",
                headers=hb,
                json={"items": [{"text": "mine now"}]},
            ),
            c.post(
                f"/v1/tasks/{task_id}/next-action",
                headers=hb,
                json={"next_action": "do as I say"},
            ),
            c.post(
                f"/v1/tasks/{task_id}/comments",
                headers=hb,
                json={"body": "hello", "author_kind": "user"},
            ),
            c.post(
                f"/v1/tasks/{task_id}/artifacts",
                headers=hb,
                json={"name": "n", "kind": "note", "content": "x"},
            ),
        ]
        for coro in writes:
            r = await coro
            assert r.status_code == 404, f"{r.request.url} → {r.status_code}: {r.text}"

        # And nothing moved: the task is exactly where its owner left it.
        still = await c.get(f"/v1/tasks/{task_id}", headers=ha)
        assert still.status_code == 200
        assert still.json()["status"] == "backlog"
        assert still.json()["title"] == "Confidential"


async def test_the_task_surface_is_not_readable_without_a_token_at_all():
    """The failure mode worth naming separately: several of these routes named no caller,
    so nothing ever asked for a token and the rows were readable from the open port."""
    async with await _client() as c:
        ha, ws_a = await _register(c, "pat-e@armarius.dev")
        project_id, task_id = await _project_with_task(c, ha, ws_a)

        for path in _reads(project_id, task_id):
            r = await c.get(path)
            assert r.status_code == 401, f"{path} → {r.status_code}: {r.text}"


async def test_a_stranger_cannot_reach_another_patrons_run_trace():
    """A run trace carries the prompt sent to the agent and everything it said back."""
    async with await _client() as c:
        ha, ws_a = await _register(c, "pat-f@armarius.dev")
        _, task_id = await _project_with_task(c, ha, ws_a)
        hb, _ = await _register(c, "pat-g@armarius.dev")

        # A run id that does not resolve for the caller reads the same as one that does
        # not exist — which is the point: the answer must not sort ids into real and not.
        ghost = "00000000-0000-0000-0000-0000000000ff"
        for path in (f"/v1/runs/{ghost}", f"/v1/runs/{ghost}/events"):
            assert (await c.get(path, headers=hb)).status_code == 404
            assert (await c.get(path, headers=ha)).status_code == 404
            assert (await c.get(path)).status_code == 401

        assert (await c.get(f"/v1/tasks/{task_id}/runs", headers=hb)).status_code == 404
        assert (await c.get(f"/v1/tasks/{task_id}/runs", headers=ha)).status_code == 200


async def test_an_edge_cannot_be_pointed_at_a_task_in_another_workspace():
    """Both ends of a dependency are checked, not just the one in the path.

    Otherwise a caller adds *their own* task as blocked by a stranger's, then reads their
    own blocker list — and the row comes back with its title on it.
    """
    async with await _client() as c:
        ha, ws_a = await _register(c, "pat-h@armarius.dev")
        _, secret_task = await _project_with_task(c, ha, ws_a)
        hb, ws_b = await _register(c, "pat-i@armarius.dev")
        _, my_task = await _project_with_task(c, hb, ws_b)

        r = await c.post(
            f"/v1/tasks/{my_task}/dependencies",
            headers=hb,
            json={"blocks_task_id": secret_task},
        )
        assert r.status_code == 404, r.text

        blockers = await c.get(f"/v1/tasks/{my_task}/dependencies", headers=hb)
        assert blockers.status_code == 200
        assert blockers.json() == []
