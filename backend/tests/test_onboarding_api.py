"""Contract-conformance — Onboarding endpoints (Sprint 7 / Phase G).

An HTTP walk over the agent-assisted project-setup chat: open it, talk to the Workspace
Agent (it proposes a roster), finalize (a real ``setup`` project + roster is created), and
enforce workspace scoping (cross-workspace 404). The scripted brain + SQL persistence are
exercised end-to-end through the global app.
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


async def test_onboarding_start_message_finalize_creates_project() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "onb1@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}

        started = await c.post(f"/v1/workspaces/{ws_id}/onboarding", headers=h)
        assert started.status_code == 201, started.text
        session = started.json()
        assert session["status"] == "open"
        assert session["transcript"][0]["role"] == "agent"  # greeting
        sid = session["id"]

        # Active lookup returns the just-opened session.
        active = await c.get(f"/v1/workspaces/{ws_id}/onboarding/active", headers=h)
        assert active.status_code == 200
        assert active.json()["id"] == sid

        shaped = await c.post(
            f"/v1/onboarding/{sid}/messages",
            headers=h,
            json={"text": "Build a react frontend with a node backend api"},
        )
        assert shaped.status_code == 200, shaped.text
        agent_turns = [t for t in shaped.json()["transcript"] if t["role"] == "agent"]
        assert "Frontend" in agent_turns[-1]["text"]
        assert "Backend" in agent_turns[-1]["text"]

        finalized = await c.post(f"/v1/onboarding/{sid}/finalize", headers=h)
        assert finalized.status_code == 200, finalized.text
        body = finalized.json()
        assert body["status"] == "finalized"
        assert body["created_project_id"] is not None
        pid = body["created_project_id"]

        # The materialised project carries a roster satisfying the hard rule.
        roster = await c.get(f"/v1/projects/{pid}/roster", headers=h)
        assert roster.status_code == 200
        roles = roster.json()
        assert any(r["is_leader"] for r in roles)
        assert any(not r["is_leader"] for r in roles)
        titles = {r["title"] for r in roles}
        assert {"Frontend", "Backend"} <= titles

        # No live chat left once finalized.
        gone = await c.get(f"/v1/workspaces/{ws_id}/onboarding/active", headers=h)
        assert gone.status_code == 404


async def test_onboarding_abandon_ends_chat() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "onb2@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        sid = (await c.post(f"/v1/workspaces/{ws_id}/onboarding", headers=h)).json()["id"]

        abandoned = await c.post(f"/v1/onboarding/{sid}/abandon", headers=h)
        assert abandoned.status_code == 200
        assert abandoned.json()["status"] == "abandoned"

        # An abandoned session rejects further messages (illegal transition → 409).
        again = await c.post(
            f"/v1/onboarding/{sid}/messages", headers=h, json={"text": "hi"}
        )
        assert again.status_code == 409


async def test_onboarding_cross_workspace_is_404() -> None:
    async with await _client() as c:
        token_a, ws_a = await _register(c, "onb_a@armarius.dev")
        token_b, _ws_b = await _register(c, "onb_b@armarius.dev")
        h_a = {"Authorization": f"Bearer {token_a}"}
        h_b = {"Authorization": f"Bearer {token_b}"}

        sid = (await c.post(f"/v1/workspaces/{ws_a}/onboarding", headers=h_a)).json()["id"]

        # Another user cannot read, message, or finalize the session.
        assert (await c.get(f"/v1/onboarding/{sid}", headers=h_b)).status_code == 404
        assert (
            await c.post(f"/v1/onboarding/{sid}/messages", headers=h_b, json={"text": "x"})
        ).status_code == 404
        assert (await c.post(f"/v1/onboarding/{sid}/finalize", headers=h_b)).status_code == 404
