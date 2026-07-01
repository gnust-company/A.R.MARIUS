"""Contract-conformance — Commission endpoints (API_CONTRACT §2.13).

A light HTTP smoke over the router: start a commission (leader offline → queued draft),
read it back, confirm it (draft→todo), and enforce workspace scoping (cross-workspace 404).
The async Leader/worker wake paths are covered by test_integration_commission.
"""

from __future__ import annotations

from uuid import UUID

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from armarius.infrastructure.database import engine as engine_mod
from armarius.infrastructure.database.models import TaskModel
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


async def _project_with_seated_leader(c: AsyncClient, ws_id: str, h: dict) -> str:
    proj = await c.post(
        f"/v1/workspaces/{ws_id}/projects",
        headers=h,
        json={"name": "Apollo", "leader": {"marius_id": None},
              "roles": [{"title": "Backend", "seats": 1}]},
    )
    pid = proj.json()["id"]
    # An invited (offline) Leader — enough to seat the leader role for commissioning.
    leader = await c.post(
        f"/v1/workspaces/{ws_id}/mariuses",
        headers=h,
        json={"name": "Lead", "role": "Leader", "adapter_type": "echo", "adapter_config": {}},
    )
    await c.post(
        f"/v1/projects/{pid}/grant",
        headers=h,
        json={"marius_id": leader.json()["id"], "role_key": "leader"},
    )
    return pid


async def test_commission_flow_start_get_confirm() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "com1@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        pid = await _project_with_seated_leader(c, ws_id, h)

        started = await c.post(
            "/v1/commissions", headers=h,
            json={"project_id": pid, "message": "Build the login page"},
        )
        assert started.status_code == 201, started.text
        body = started.json()
        assert body["status"] == "open"
        # The Leader was offline → the shaping turn is queued, not run.
        assert body["leader_state"] == "leader_offline"
        session_id, task_id = body["id"], body["task_id"]

        got = await c.get(f"/v1/commissions/{session_id}", headers=h)
        assert got.status_code == 200
        assert got.json()["task_id"] == task_id

        confirmed = await c.post(f"/v1/commissions/{session_id}/confirm", headers=h)
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["status"] == "confirmed"

    # The draft was flipped onto the board.
    sm = engine_mod.get_sessionmaker()
    async with sm() as s:
        status = await s.scalar(
            select(TaskModel.status).where(TaskModel.id == UUID(task_id))
        )
    assert status == "todo"


async def test_commission_cross_workspace_is_404() -> None:
    async with await _client() as c:
        token_a, ws_a = await _register(c, "com-a@armarius.dev")
        ha = {"Authorization": f"Bearer {token_a}"}
        pid = await _project_with_seated_leader(c, ws_a, ha)

        token_b, _ = await _register(c, "com-b@armarius.dev")
        hb = {"Authorization": f"Bearer {token_b}"}
        r = await c.post(
            "/v1/commissions", headers=hb,
            json={"project_id": pid, "message": "not my project"},
        )
    assert r.status_code == 404, r.text
