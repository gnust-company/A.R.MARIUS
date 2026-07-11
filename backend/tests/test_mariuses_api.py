"""Contract-conformance — Mariuses operator-invite (issue #63, API_CONTRACT §4.1).

The invite takes the agent's gateway URL + api_key, mints the token at invite time (no
enroll/approve), and pushes a setup prompt over that gateway. The response carries
``send_status`` and NEVER the token — it is a secret the agent alone receives.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

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
                "role": "Backend",
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
                "role": "r",
                "adapter_type": "echo",
                "gateway_url": GATEWAY_URL,
                "api_key": GATEWAY_KEY,
            },
        )
    assert r.status_code == 404, r.text
