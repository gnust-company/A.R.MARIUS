"""End-to-end: drive the MCP tool layer against the REAL backend, in-process.

Opt-in (`-m integration`); needs `armarius-backend` installed (dev extra). Uses
``httpx.ASGITransport`` so no socket/port is opened — the same pattern the backend's
own tests use. Proves the whole loop is tool calls: enroll (with a concurrent patron
approve) → whoami → get_task → claim_task → comment → status → artifact → review →
next_action. No curl anywhere.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid

import httpx
import pytest

# Point the backend at an isolated temp SQLite file BEFORE it is imported (the fixture
# imports it lazily). Otherwise its default `./armarius.db` would land in whatever dir
# pytest runs from — e.g. littering `mcp/armarius.db`.
_TMP_DB = os.path.join(tempfile.gettempdir(), f"armarius-mcp-int-{uuid.uuid4().hex}.db")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TMP_DB}")

pytestmark = pytest.mark.integration

# Imported lazily inside the fixture so a plain `uv run pytest` (no backend installed)
# doesn't fail at collection — only `-m integration` runs pull these in.


@pytest.fixture
async def backend():
    from armarius.infrastructure.database.engine import init_db
    from armarius.main import app
    from armarius.presentation.container import build_container

    await init_db()
    app.state.container = build_container()
    yield app


async def _register(patron: httpx.AsyncClient) -> tuple[dict, str]:
    email = f"mcp-int-{uuid.uuid4().hex[:8]}@armarius.dev"
    r = await patron.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["tokens"]["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    ws = (await patron.get("/v1/workspaces", headers=h)).json()[0]["id"]
    return h, ws


async def _project_and_task(patron: httpx.AsyncClient, h: dict, ws: str) -> str:
    plan = {
        "name": "Integration",
        "description": "e2e",
        "leader": {"responsibilities": "lead", "marius_id": None},
        "roles": [{"title": "Backend", "seats": 1}],
    }
    pid = (await patron.post(f"/v1/workspaces/{ws}/projects", headers=h, json=plan)).json()["id"]
    task = await patron.post(f"/v1/projects/{pid}/tasks", headers=h, json={"title": "Do the thing"})
    assert task.status_code == 201, task.text
    task_id = task.json()["id"]
    # A new task is `backlog`; the leader puts it on the board (todo) before an agent
    # can claim it (claim only auto-starts a todo task; backlog→in_progress is illegal).
    moved = await patron.post(
        f"/v1/tasks/{task_id}/status", headers=h, json={"status": "todo"}
    )
    assert moved.status_code == 200, moved.text
    return task_id


async def _invite(patron: httpx.AsyncClient, h: dict, ws: str) -> tuple[str, str]:
    r = await patron.post(
        f"/v1/workspaces/{ws}/mariuses",
        headers=h,
        json={"name": "Marin", "role": "Backend", "skills": [], "skill_ids": [],
              "adapter_type": "echo", "adapter_config": {}},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"], r.json()["enrollment_code"]


async def _retry_approve(patron: httpx.AsyncClient, ws: str, mid: str, h: dict) -> None:
    for _ in range(50):
        r = await patron.post(f"/v1/workspaces/{ws}/mariuses/{mid}/approve", headers=h)
        if r.status_code == 200:
            return
        await asyncio.sleep(0.02)
    raise AssertionError("approve never succeeded")


async def test_full_agent_loop_is_all_tools(backend, tmp_path, monkeypatch):
    from armarius_mcp import tools
    from armarius_mcp.client import ArmariusClient
    from armarius_mcp.config import Config
    from armarius_mcp.state import ServerState

    monkeypatch.setattr("armarius_mcp.credentials.CREDENTIALS_DIR", tmp_path)
    transport = httpx.ASGITransport(app=backend)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as patron:
        h, ws = await _register(patron)
        task_id = await _project_and_task(patron, h, ws)
        mid, code = await _invite(patron, h, ws)

        # Agent side: no token yet — the whole loop is MCP tool calls.
        client = ArmariusClient("http://test", None, transport=transport)
        cfg = Config(
            base_url="http://test", token=None,
            agent_name="Marin", agent_role="Backend", workspace="Acme", project="Integration",
        )
        state = ServerState(cfg, client)

        # enroll blocks until approve; run them concurrently.
        enroll_task = asyncio.create_task(tools.enroll(state, mid, code, timeout_seconds=10))
        await _retry_approve(patron, ws, mid, h)
        enrolled = await asyncio.wait_for(enroll_task, timeout=10)
        assert enrolled["enrolled"] is True
        assert state.config.token and state.config.token.startswith("arm_")

        # Credential file was written at the onboarding path with all six keys.
        cred_file = tmp_path / "acme_marin.json"
        assert cred_file.is_file()

        me = await tools.whoami(state)
        assert me["marius"]["name"] == "Marin"

        view = await tools.get_task(state, task_id)
        assert view["task"]["id"] == task_id

        claimed = await tools.claim_task(state, task_id)
        assert claimed["assigned_marius_id"] == mid

        await tools.post_comment(state, task_id, "On it. @Patron will update shortly.")
        await tools.update_status(state, task_id, "in_progress", "starting")

        # in_review is gated on an artifact — publish first, then transition.
        from armarius_mcp.http_error import ArmariusApiError

        with pytest.raises(ArmariusApiError) as gate:
            await tools.update_status(state, task_id, "in_review")
        assert gate.value.status_code == 409
        await tools.publish_artifact(
            state, task_id, "result.txt", kind="file", content="done"
        )
        reviewed = await tools.update_status(state, task_id, "in_review")
        assert reviewed["status"] == "in_review"

        await tools.set_next_action(state, task_id, "await review feedback")

        await client.aclose()
