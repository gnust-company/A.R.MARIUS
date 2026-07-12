"""Contract-conformance — Mariuses operator-invite (issue #63, API_CONTRACT §4.1).

The invite takes the agent's gateway URL + api_key, mints the token at invite time (no
enroll/approve), and pushes a setup prompt over that gateway. The response carries
``send_status`` and NEVER the token — it is a secret the agent alone receives.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import RunModel
from armarius.main import app
from tests.support.agents import GATEWAY_KEY, GATEWAY_URL, agent_token_for, invite_agent


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


async def test_invite_returns_send_status_and_never_the_token() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "inv@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        data = await invite_agent(c, ws_id, h)

    assert data["invite_status"] == "approved"  # approved at invite time (#63)
    assert data["send_status"] == "sent"  # the setup prompt reached the echo runtime
    # The token is a secret — it must not leak through the API.
    assert "agent_token" not in data
    assert "enrollment_code" not in data
    assert "invite" not in data


async def test_agent_me_after_invite_marks_online() -> None:
    """The agent's token (read from the repo) authenticates /agent/me → ONLINE."""
    async with await _client() as c:
        token, ws_id = await _register(c, "online@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        data = await invite_agent(c, ws_id, h)
        agent_token = await agent_token_for(data["id"])

        me = await c.get("/agent/me", headers={"Authorization": f"Bearer {agent_token}"})
    assert me.status_code == 200, me.text
    assert me.json()["marius"]["liveness"] == "online"


async def test_invite_with_unreachable_gateway_is_422() -> None:
    """A hermes_gateway whose probe fails (closed port) is rejected before persisting."""
    async with await _client() as c:
        token, ws_id = await _register(c, "badgw@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        r = await c.post(
            f"/v1/workspaces/{ws_id}/mariuses",
            headers=h,
            json={
                "name": "Hermes",
                "adapter_type": "hermes_gateway",
                "gateway_url": "http://127.0.0.1:1",  # closed port → probe fails
                "api_key": "k",
            },
        )
    assert r.status_code == 422, r.text


async def test_invite_with_unknown_adapter_is_400() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "noadapter@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        r = await c.post(
            f"/v1/workspaces/{ws_id}/mariuses",
            headers=h,
            json={
                "name": "Hermes",
                "adapter_type": "no-such-runtime",
                "gateway_url": GATEWAY_URL,
                "api_key": GATEWAY_KEY,
            },
        )
    assert r.status_code == 400, r.text


async def _seed_run(marius_id: str, *, created_at: datetime, status: str = "completed") -> UUID:
    """Persist one run for an agent the way the wake engine would (plain-UUID ref)."""
    run_id = uuid4()
    async with get_sessionmaker()() as s:
        s.add(
            RunModel(
                id=run_id,
                marius_id=UUID(marius_id),
                task_id=uuid4(),
                adapter_type="echo",
                wake_source="assignment",
                status=status,
                created_at=created_at,
            )
        )
        await s.commit()
    return run_id


async def test_list_marius_runs_returns_agent_runs_newest_first() -> None:
    """The agent-detail feed reads the agent's runs, newest first, scoped to that agent."""
    async with await _client() as c:
        token, ws_id = await _register(c, "runs@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        agent = await invite_agent(c, ws_id, h, name="Runner")
        other = await invite_agent(c, ws_id, h, name="Bystander")

        older = await _seed_run(
            agent["id"], created_at=datetime(2026, 7, 1, tzinfo=UTC)
        )
        newer = await _seed_run(
            agent["id"], created_at=datetime(2026, 7, 5, tzinfo=UTC)
        )
        # A run for a different agent must NOT leak into this agent's feed.
        await _seed_run(other["id"], created_at=datetime(2026, 7, 9, tzinfo=UTC))

        r = await c.get(f"/v1/workspaces/{ws_id}/mariuses/{agent['id']}/runs", headers=h)

    assert r.status_code == 200, r.text
    runs = r.json()
    assert [run["id"] for run in runs] == [str(newer), str(older)]  # newest first
    assert runs[0]["marius_id"] == agent["id"]
    assert runs[0]["wake_source"] == "assignment"
    assert runs[0]["status"] == "completed"


async def test_list_marius_runs_is_empty_for_a_fresh_agent() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "freshruns@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        agent = await invite_agent(c, ws_id, h)
        r = await c.get(f"/v1/workspaces/{ws_id}/mariuses/{agent['id']}/runs", headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == []


async def test_list_marius_runs_cross_workspace_is_404() -> None:
    """An agent that lives in another workspace 404s — no cross-tenant run leakage."""
    async with await _client() as c:
        token_a, ws_a = await _register(c, "runs-a@armarius.dev")
        token_b, ws_b = await _register(c, "runs-b@armarius.dev")
        ha = {"Authorization": f"Bearer {token_a}"}
        hb = {"Authorization": f"Bearer {token_b}"}
        agent_a = await invite_agent(c, ws_a, ha, name="AOnly")
        # B asks for A's agent under B's own workspace → agent not in this workspace → 404.
        r = await c.get(
            f"/v1/workspaces/{ws_b}/mariuses/{agent_a['id']}/runs", headers=hb
        )
    assert r.status_code == 404, r.text


@pytest.mark.parametrize("missing", ["marius", "workspace"])
async def test_cross_workspace_invite_is_404(missing: str) -> None:
    async with await _client() as c:
        token_a, ws_a = await _register(c, f"a-{missing}@armarius.dev")
        token_b, ws_b = await _register(c, f"b-{missing}@armarius.dev")
        hb = {"Authorization": f"Bearer {token_b}"}
        # User B may not invite into User A's workspace.
        r = await c.post(
            f"/v1/workspaces/{ws_a}/mariuses",
            headers=hb,
            json={
                "name": "X",
                "adapter_type": "echo",
                "gateway_url": GATEWAY_URL,
                "api_key": GATEWAY_KEY,
            },
        )
    assert r.status_code == 404, r.text
