"""End-to-end: drive the MCP tool layer against the REAL backend, in-process.

Opt-in (`-m integration`); needs `armarius-backend` installed (dev extra). Uses
``httpx.ASGITransport`` so no socket/port is opened — the same pattern the backend's
own tests use. Under operator-invite (issue #63) the agent's token is minted at invite
time and delivered in the pushed setup prompt; the MCP server has no ``enroll``/``claim``
anymore (issue #64), so this test reads the token from the repo (as a real agent would
have received it) and proves the whole loop is tool calls: whoami → get_task →
claim_task → comment → status → artifact → review → next_action. No curl anywhere.
"""

from __future__ import annotations

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


async def test_full_agent_loop_is_all_tools(backend, tmp_path, monkeypatch):
    from tests.support.agents import agent_token_for, invite_agent

    from armarius_mcp import tools
    from armarius_mcp.client import ArmariusClient
    from armarius_mcp.config import Config
    from armarius_mcp.state import ServerState

    monkeypatch.setattr("armarius_mcp.credentials.CREDENTIALS_DIR", tmp_path)
    transport = httpx.ASGITransport(app=backend)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as patron:
        h, ws = await _register(patron)
        task_id = await _project_and_task(patron, h, ws)
        # Operator-invite (issue #63): gateway creds in → token minted + setup pushed.
        # The API never returns the token; read it back from the repo as a real agent
        # would have received it in the pushed setup prompt.
        data = await invite_agent(patron, ws, h, name="Marin")
        mid = data["id"]
        token = await agent_token_for(mid)

        # Agent side: the whole loop is MCP tool calls, authenticated with the token.
        client = ArmariusClient("http://test", token, transport=transport)
        cfg = Config(
            base_url="http://test", token=token,
            agent_name="Marin", agent_role="Backend", workspace="Acme", project="Integration",
        )
        state = ServerState(cfg, client)

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
