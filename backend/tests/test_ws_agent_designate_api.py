"""Workspace Agent designation API (#32) — designate/swap via the pointer, invite
checkbox, and host delete-protection."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.database.engine import init_db
from armarius.main import app
from armarius.presentation.container import build_container
from tests.support.agents import GATEWAY_KEY, GATEWAY_URL


@pytest.fixture(autouse=True)
async def _bootstrap():
    await init_db()
    container = build_container()
    # Zero-delay echo so each invite's setup-push is instant (issue #63).
    container.registry.register(EchoAdapter(step_delay=0.0))
    app.state.container = container
    yield


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(c: AsyncClient, email: str) -> tuple[dict, str]:
    """Register a user; return (auth headers, workspace_id)."""
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    assert r.status_code == 201, r.text
    h = {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}
    ws = await c.get("/v1/workspaces", headers=h)
    assert ws.status_code == 200
    return h, ws.json()[0]["id"]


async def _invite(c: AsyncClient, h: dict, ws_id: str, name: str, **extra) -> dict:
    r = await c.post(
        f"/v1/workspaces/{ws_id}/mariuses",
        headers=h,
        json={
            "name": name,
            "role": "",
            "skills": [],
            "skill_ids": [],
            "adapter_type": "echo",
            "gateway_url": GATEWAY_URL,
            "api_key": GATEWAY_KEY,
            **extra,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _pointer(c: AsyncClient, h: dict, ws_id: str) -> str | None:
    ws = await c.get("/v1/workspaces", headers=h)
    return next(w for w in ws.json() if w["id"] == ws_id)["workspace_agent_id"]


async def test_designate_swap_and_host_deletion():
    async with await _client() as c:
        h, ws_id = await _register(c, "designate@armarius.dev")
        assert await _pointer(c, h, ws_id) is None  # fresh workspace: no host yet

        bob = await _invite(c, h, ws_id, "Bob")
        r = await c.post(
            f"/v1/workspaces/{ws_id}/mariuses/{bob['id']}/designate", headers=h
        )
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "Workspace Agent"
        assert await _pointer(c, h, ws_id) == bob["id"]

        # Invite-with-checkbox seats the newcomer and demotes Bob — kept, not revoked.
        alice = await _invite(c, h, ws_id, "Alice", is_workspace_agent=True)
        assert alice["role"] == "Workspace Agent"
        assert await _pointer(c, h, ws_id) == alice["id"]
        directory = (
            await c.get(f"/v1/workspaces/{ws_id}/mariuses", headers=h)
        ).json()
        demoted = next(m for m in directory if m["id"] == bob["id"])
        assert demoted["role"] == ""

        # Both are deletable now (#50): the demoted agent goes quietly, and deleting the
        # sitting host (Alice) simply vacates the seat — no protection error.
        assert (
            await c.delete(f"/v1/workspaces/{ws_id}/mariuses/{bob['id']}", headers=h)
        ).status_code == 204
        assert (
            await c.delete(f"/v1/workspaces/{ws_id}/mariuses/{alice['id']}", headers=h)
        ).status_code == 204
        assert await _pointer(c, h, ws_id) is None  # host deletion vacated the seat
