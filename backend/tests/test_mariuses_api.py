"""Contract-conformance — Mariuses invite/approve + enroll-and-wait (API_CONTRACT §4.1, §9).

The headline change: the invite returns an enrollment_code and **no token**; the token is
minted on approval and handed back as the response of the held `/agent/enroll` call.
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

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


async def _invite(c: AsyncClient, ws_id: str, h: dict, name: str = "Hermes") -> dict:
    r = await c.post(
        f"/v1/workspaces/{ws_id}/mariuses",
        headers=h,
        json={"name": name, "role": "Backend", "adapter_type": "echo", "adapter_config": {}},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _retry_approve(c: AsyncClient, ws_id: str, marius_id: str, h: dict) -> dict:
    """Approve, tolerating the brief window before the held enroll flips to pending_review."""
    for _ in range(100):
        r = await c.post(f"/v1/workspaces/{ws_id}/mariuses/{marius_id}/approve", headers=h)
        if r.status_code == 200:
            return r.json()
        await asyncio.sleep(0.02)
    raise AssertionError(f"approve never succeeded: {r.status_code} {r.text}")


async def test_invite_returns_code_and_no_token() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "inv@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        data = await _invite(c, ws_id, h)
    assert data["agent_token"] is None
    assert data["enrollment_code"]
    assert data["invite_status"] == "invited"
    assert "invite" in data and data["invite"]


async def test_enroll_holds_until_approve_then_returns_token() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "enroll@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        invited = await _invite(c, ws_id, h)
        mid, code = invited["id"], invited["enrollment_code"]

        enroll_task = asyncio.create_task(
            c.post("/agent/enroll", json={"marius_id": mid, "enrollment_code": code})
        )
        await asyncio.sleep(0.05)  # let the held call flip the invite to pending_review
        approved = await _retry_approve(c, ws_id, mid, h)
        enroll_resp = await asyncio.wait_for(enroll_task, timeout=5)

    assert approved["agent_token"]
    assert approved["invite_status"] == "approved"
    assert enroll_resp.status_code == 200, enroll_resp.text
    # The token the agent receives on its held enroll call is the one just minted.
    assert enroll_resp.json()["agent_token"] == approved["agent_token"]


async def test_agent_me_with_minted_token_marks_online() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "online@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        invited = await _invite(c, ws_id, h)
        mid, code = invited["id"], invited["enrollment_code"]

        enroll_task = asyncio.create_task(
            c.post("/agent/enroll", json={"marius_id": mid, "enrollment_code": code})
        )
        await asyncio.sleep(0.05)
        await _retry_approve(c, ws_id, mid, h)
        agent_token = (await asyncio.wait_for(enroll_task, timeout=5)).json()["agent_token"]

        me = await c.get("/agent/me", headers={"Authorization": f"Bearer {agent_token}"})
    assert me.status_code == 200, me.text
    assert me.json()["marius"]["liveness"] == "online"


async def test_enroll_with_wrong_code_is_400() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "badcode@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        invited = await _invite(c, ws_id, h)
        r = await c.post(
            "/agent/enroll",
            json={"marius_id": invited["id"], "enrollment_code": "nope-not-it"},
        )
    assert r.status_code == 400, r.text


async def test_claim_is_recovery_only_after_approval() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "claim@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        invited = await _invite(c, ws_id, h)
        mid, code = invited["id"], invited["enrollment_code"]

        # Before approval, claim is rejected (the token does not exist yet).
        early = await c.post("/agent/claim", json={"marius_id": mid, "enrollment_code": code})
        assert early.status_code == 409, early.text

        enroll_task = asyncio.create_task(
            c.post("/agent/enroll", json={"marius_id": mid, "enrollment_code": code})
        )
        await asyncio.sleep(0.05)
        approved = await _retry_approve(c, ws_id, mid, h)
        await asyncio.wait_for(enroll_task, timeout=5)

        recovered = await c.post(
            "/agent/claim", json={"marius_id": mid, "enrollment_code": code}
        )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["agent_token"] == approved["agent_token"]


async def test_approve_cross_workspace_marius_is_404() -> None:
    async with await _client() as c:
        token_a, ws_a = await _register(c, "appr-a@armarius.dev")
        token_b, ws_b = await _register(c, "appr-b@armarius.dev")
        ha = {"Authorization": f"Bearer {token_a}"}
        hb = {"Authorization": f"Bearer {token_b}"}
        marius_b = await _invite(c, ws_b, hb)  # an agent that lives in B's workspace
        # A owns ws_a, but marius_b belongs to ws_b — approving it through A's own
        # workspace must NOT mint a token for someone else's agent.
        r = await c.post(
            f"/v1/workspaces/{ws_a}/mariuses/{marius_b['id']}/approve", headers=ha
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
            json={"name": "X", "role": "r", "adapter_type": "echo", "adapter_config": {}},
        )
    assert r.status_code == 404, r.text
