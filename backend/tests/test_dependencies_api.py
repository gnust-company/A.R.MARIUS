"""Contract-conformance — cổng phụ thuộc qua HTTP (#91, API_CONTRACT §4).

Cạnh ``blocked_by`` quản qua ``/v1/tasks/{t}/dependencies``; task còn blocker chưa done
không vào được ``todo`` (409); cạnh tự-trỏ bị từ chối (422).
"""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from armarius.main import app


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(c: AsyncClient, email: str) -> tuple[str, str]:
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    token = r.json()["tokens"]["access_token"]
    ws = await c.get("/v1/workspaces", headers={"Authorization": f"Bearer {token}"})
    return token, ws.json()[0]["id"]


async def _project(c: AsyncClient, ws_id: str, h: dict) -> str:
    proj = await c.post(
        f"/v1/workspaces/{ws_id}/projects",
        headers=h,
        json={
            "name": "Apollo",
            "key": "APO",
            "leader": {"description": "Leads.", "marius_id": None},
            "roles": [{"title": "Backend", "seats": 1, "description": "Owns the API."}],
        },
    )
    return proj.json()["id"]


async def _new_task(c: AsyncClient, pid: str, h: dict, title: str) -> str:
    r = await c.post(f"/v1/projects/{pid}/tasks", headers=h, json={"title": title})
    return r.json()["id"]


async def test_dependency_gate_over_http() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "dep1@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        pid = await _project(c, ws_id, h)
        blocker = await _new_task(c, pid, h, "blocker")
        blocked = await _new_task(c, pid, h, "blocked")

        # Add the blocked_by edge → 201, body is the refreshed blocker list.
        added = await c.post(
            f"/v1/tasks/{blocked}/dependencies",
            headers=h,
            json={"blocks_task_id": blocker},
        )
        assert added.status_code == 201, added.text
        assert [b["id"] for b in added.json()] == [blocker]

        # blocker chưa done ⇒ chuyển blocked→todo bị chặn (409).
        gated = await c.post(
            f"/v1/tasks/{blocked}/status", headers=h, json={"status": "todo"}
        )
        assert gated.status_code == 409, gated.text

        # GET liệt kê blocker.
        listed = await c.get(f"/v1/tasks/{blocked}/dependencies", headers=h)
        assert listed.status_code == 200
        assert [b["id"] for b in listed.json()] == [blocker]

        # Project-level edges cho board.
        edges = await c.get(f"/v1/projects/{pid}/task-dependencies", headers=h)
        assert edges.status_code == 200
        assert edges.json()[0]["blocks_task_id"] == blocker

        # Gỡ cạnh ⇒ 204, sau đó chuyển todo được (200).
        removed = await c.delete(
            f"/v1/tasks/{blocked}/dependencies/{blocker}", headers=h
        )
        assert removed.status_code == 204
        ok = await c.post(
            f"/v1/tasks/{blocked}/status", headers=h, json={"status": "todo"}
        )
        assert ok.status_code == 200, ok.text


async def test_self_loop_dependency_rejected_422() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "dep2@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        pid = await _project(c, ws_id, h)
        t = await _new_task(c, pid, h, "solo")

        bad = await c.post(
            f"/v1/tasks/{t}/dependencies", headers=h, json={"blocks_task_id": t}
        )
        assert bad.status_code == 422, bad.text
