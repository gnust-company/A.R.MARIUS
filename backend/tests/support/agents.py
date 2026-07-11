"""HTTP-level helpers for the operator-invite flow (issue #63).

Inviting an agent now mints the token at invite time and pushes a setup prompt over the
agent's gateway — the token is **never** returned by the API (it is a secret). Tests that
need to act as the agent (e.g. call ``/agent/me`` to flip it ONLINE) read the token back
from the repo via ``agent_token_for``.
"""

from __future__ import annotations

from uuid import UUID

from httpx import AsyncClient

# A gateway the echo adapter is happy with (its test_environment is always ok). The values
# are placeholders — the echo runtime ignores them; they just have to be non-empty.
GATEWAY_URL = "http://gateway.test"
GATEWAY_KEY = "test-key"


async def invite_agent(
    c: AsyncClient,
    ws_id: str,
    h: dict,
    *,
    name: str = "Hermes",
    adapter_type: str = "echo",
    gateway_url: str = GATEWAY_URL,
    api_key: str = GATEWAY_KEY,
    is_workspace_agent: bool = False,
    skills: list[str] | None = None,
    skill_ids: list[str] | None = None,
) -> dict:
    """Invite an agent with operator-supplied gateway creds → APPROVED + setup pushed.

    Role is intentionally not taken — it is a project-roster concept (#63)."""
    body: dict = {
        "name": name,
        "adapter_type": adapter_type,
        "gateway_url": gateway_url,
        "api_key": api_key,
        "is_workspace_agent": is_workspace_agent,
    }
    if skills is not None:
        body["skills"] = skills
    if skill_ids is not None:
        body["skill_ids"] = skill_ids
    r = await c.post(f"/v1/workspaces/{ws_id}/mariuses", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def agent_token_for(marius_id: str | UUID) -> str:
    """Read an agent's minted token from the repo (the API never exposes it)."""
    from armarius.main import app

    async with app.state.container.uow_factory() as uow:
        marius = await uow.mariuses.get(UUID(str(marius_id)))
    assert marius is not None and marius.agent_token
    return marius.agent_token


async def invite_and_online(
    c: AsyncClient,
    ws_id: str,
    h: dict,
    *,
    name: str = "Hermes",
    is_workspace_agent: bool = False,
    skill_ids: list[str] | None = None,
) -> tuple[str, str]:
    """Invite with creds, then hit /agent/me so the agent flips ONLINE.

    Returns ``(marius_id, agent_token)``.
    """
    data = await invite_agent(
        c,
        ws_id,
        h,
        name=name,
        is_workspace_agent=is_workspace_agent,
        skill_ids=skill_ids,
    )
    mid = data["id"]
    token = await agent_token_for(mid)
    me = await c.get("/agent/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    return mid, token
