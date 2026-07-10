"""Contract-conformance — Onboarding endpoints (#61).

An HTTP walk over the agent-driven project-setup chat: open it (a FRESH session that asks the
first question), answer each tick-select question until a draft is emitted, finalize (a real
``setup`` project + roster is created), and enforce workspace scoping (cross-workspace 404).
"""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from armarius.main import app

_ANSWERS = {
    "objective": "A web app",
    "name": "Task Tracker",
    "roles": "Frontend, Backend",
    "metric": "Ship it",
    "target": "This month",
    "context": "No, that's it",
}


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


async def _answer_until_complete(c: AsyncClient, h: dict, sid: str, session: dict) -> dict:
    while session["collected"].get("pending_question") is not None:
        key = session["collected"]["pending_question"]["key"]
        r = await c.post(
            f"/v1/onboarding/{sid}/answer", headers=h, json={"answer": _ANSWERS[key]}
        )
        assert r.status_code == 200, r.text
        session = r.json()
    return session


async def test_onboarding_start_answer_finalize_creates_project() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "onb1@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}

        started = await c.post(f"/v1/workspaces/{ws_id}/onboarding", headers=h)
        assert started.status_code == 201, started.text
        session = started.json()
        assert session["status"] == "open"
        assert session["collected"]["pending_question"]["key"] == "objective"
        sid = session["id"]

        # Active lookup returns the just-opened session.
        active = await c.get(f"/v1/workspaces/{ws_id}/onboarding/active", headers=h)
        assert active.status_code == 200
        assert active.json()["id"] == sid

        session = await _answer_until_complete(c, h, sid, session)
        assert session["collected"]["phase"] == "complete"
        draft = session["collected"]["draft"]
        assert draft["name"] == "Task Tracker"
        assert {"Frontend", "Backend"} <= {r["title"] for r in draft["roster"]}

        finalized = await c.post(f"/v1/onboarding/{sid}/finalize", headers=h)
        assert finalized.status_code == 200, finalized.text
        body = finalized.json()
        assert body["status"] == "finalized"
        pid = body["created_project_id"]
        assert pid is not None

        # The materialised project carries a roster satisfying the hard rule.
        roster = await c.get(f"/v1/projects/{pid}/roster", headers=h)
        assert roster.status_code == 200
        roles = roster.json()
        assert any(r["is_leader"] for r in roles)
        assert any(not r["is_leader"] for r in roles)
        assert {"Frontend", "Backend"} <= {r["title"] for r in roles}

        # No live chat left once finalized.
        gone = await c.get(f"/v1/workspaces/{ws_id}/onboarding/active", headers=h)
        assert gone.status_code == 404


async def test_start_opens_a_fresh_session_each_time() -> None:
    """Re-entering the agent flow abandons the stale chat — no old history (#61)."""
    async with await _client() as c:
        token, ws_id = await _register(c, "onbfresh@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}

        first = (await c.post(f"/v1/workspaces/{ws_id}/onboarding", headers=h)).json()
        second = (await c.post(f"/v1/workspaces/{ws_id}/onboarding", headers=h)).json()

        assert second["id"] != first["id"]
        active = await c.get(f"/v1/workspaces/{ws_id}/onboarding/active", headers=h)
        assert active.json()["id"] == second["id"]
        # The prior session is retired.
        prior = await c.get(f"/v1/onboarding/{first['id']}", headers=h)
        assert prior.json()["status"] == "abandoned"


async def test_onboarding_abandon_ends_chat() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "onb2@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        sid = (await c.post(f"/v1/workspaces/{ws_id}/onboarding", headers=h)).json()["id"]

        abandoned = await c.post(f"/v1/onboarding/{sid}/abandon", headers=h)
        assert abandoned.status_code == 200
        assert abandoned.json()["status"] == "abandoned"

        # An abandoned session rejects further answers (illegal transition → 409).
        again = await c.post(
            f"/v1/onboarding/{sid}/answer", headers=h, json={"answer": "A web app"}
        )
        assert again.status_code == 409


async def test_onboarding_cross_workspace_is_404() -> None:
    async with await _client() as c:
        token_a, ws_a = await _register(c, "onb_a@armarius.dev")
        token_b, _ws_b = await _register(c, "onb_b@armarius.dev")
        h_a = {"Authorization": f"Bearer {token_a}"}
        h_b = {"Authorization": f"Bearer {token_b}"}

        sid = (await c.post(f"/v1/workspaces/{ws_a}/onboarding", headers=h_a)).json()["id"]

        # Another user cannot read, answer, or finalize the session.
        assert (await c.get(f"/v1/onboarding/{sid}", headers=h_b)).status_code == 404
        assert (
            await c.post(f"/v1/onboarding/{sid}/answer", headers=h_b, json={"answer": "x"})
        ).status_code == 404
        assert (await c.post(f"/v1/onboarding/{sid}/finalize", headers=h_b)).status_code == 404
