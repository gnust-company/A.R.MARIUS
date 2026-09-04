"""Contract-conformance — Chat-with-Leader endpoints (#82).

A light HTTP smoke over the router: open the conversation (Leader offline → box disabled),
reject a message while offline (409), toggle YOLO mode, list proposed tasks, and enforce
workspace scoping (cross-workspace 404). The async streaming turn + task-approval wake
paths are covered by test_integration_leader_chat.
"""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from armarius.main import app
from tests.support.agents import invite_agent, ready_workplace


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
        json={"name": "Apollo", "leader": {"description": "Leads.", "marius_id": None}},
    )
    pid = proj.json()["id"]
    # Through the helper, which moves the newcomer onto a runtime this process can carry
    # out inside the call. Creating an agent puts it wherever its workplace says (FR-007g2),
    # and these tests are about the chat's own doors rather than about that road.
    leader = await invite_agent(
        c, ws_id, h, name="Lead", workplace_id=await ready_workplace(ws_id)
    )
    await c.post(f"/v1/projects/{pid}/leader", headers=h, json={"marius_id": leader["id"]})
    return pid


async def test_leader_chat_get_send_offline_and_proposed_list() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "lc1@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        pid = await _project_with_seated_leader(c, ws_id, h)

        # GET lazily opens the conversation; the Leader is offline → box disabled.
        got = await c.get(f"/v1/projects/{pid}/leader-chat", headers=h)
        assert got.status_code == 200, got.text
        body = got.json()
        assert body["leader_online"] is False
        assert body["state"] == "idle"
        assert body["transcript"] == []

        # Sending while the Leader is offline is a conflict (chat disabled, no queue).
        sent = await c.post(
            f"/v1/projects/{pid}/leader-chat/messages",
            headers=h, json={"message": "are you there?"},
        )
        assert sent.status_code == 409, sent.text

        # The toggle that used to live here is gone (spec 001 T062): what the Leader may
        # start on its own is decided by the approved plan, not by a project-wide switch.
        gone = await c.put(
            f"/v1/projects/{pid}/yolo-mode", headers=h, json={"yolo_mode": True}
        )
        assert gone.status_code in (404, 405), gone.text

        # No Leader-proposed drafts yet.
        proposed = await c.get(f"/v1/projects/{pid}/proposed-tasks", headers=h)
        assert proposed.status_code == 200
        assert proposed.json() == []


async def test_leader_chat_cross_workspace_is_404() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "lc-owner@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        pid = await _project_with_seated_leader(c, ws_id, h)

        token2, _ = await _register(c, "lc-intruder@armarius.dev")
        h2 = {"Authorization": f"Bearer {token2}"}
        blocked = await c.get(f"/v1/projects/{pid}/leader-chat", headers=h2)
        assert blocked.status_code == 404, blocked.text
