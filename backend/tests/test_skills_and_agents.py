"""Skill Shop + agent (Marius) edit flow tests."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.infrastructure.database.engine import init_db
from armarius.main import app
from armarius.presentation.container import build_container


@pytest.fixture(autouse=True)
async def _bootstrap():
    await init_db()
    app.state.container = build_container()
    yield


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(c: AsyncClient, email: str = "p@armarius.dev") -> tuple[str, str]:
    """Register a user; return (access_token, workspace_id)."""
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["tokens"]["access_token"]
    ws = await c.get("/v1/workspaces", headers={"Authorization": f"Bearer {token}"})
    assert ws.status_code == 200
    return token, ws.json()[0]["id"]


async def test_personal_workspace_has_builtin_skill():
    async with await _client() as c:
        token, ws_id = await _register(c, "skill1@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        skills = await c.get(f"/v1/workspaces/{ws_id}/skills", headers=h)
    assert skills.status_code == 200
    body = skills.json()
    assert any(s["slug"] == "armarius-http" for s in body)
    builtin = next(s for s in body if s["slug"] == "armarius-http")
    assert builtin["source"] == "builtin"


async def test_register_without_username_derives_handle():
    async with await _client() as c:
        r = await c.post(
            "/auth/register",
            json={
                "email": "marius.fan@armarius.dev",
                "full_name": "No Username",
                "password": "password1234",
            },
        )
    assert r.status_code == 201, r.text
    assert r.json()["user"]["username"] == "mariusfan"


async def test_provision_agent_links_skill_and_invite_has_steps():
    async with await _client() as c:
        token, ws_id = await _register(c, "prov@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        skills = (await c.get(f"/v1/workspaces/{ws_id}/skills", headers=h)).json()
        skill_id = skills[0]["id"]

        created = await c.post(
            f"/v1/workspaces/{ws_id}/mariuses",
            headers=h,
            json={
                "name": "Marin",
                "role": "Backend",
                "skills": ["api"],
                "skill_ids": [skill_id],
                "adapter_type": "echo",
                "adapter_config": {},
            },
        )
    assert created.status_code == 201, created.text
    data = created.json()
    assert data["skill_ids"] == [skill_id]
    assert data["agent_token"]
    # Invite advertises the skill install + the credential file.
    assert "INSTALL YOUR SKILLS" in data["invite"]
    assert "Armarius HTTP API" in data["invite"]
    assert "~/.armarius/credentials/" in data["invite"]


async def test_edit_agent_updates_skills():
    async with await _client() as c:
        token, ws_id = await _register(c, "edit@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        skills = (await c.get(f"/v1/workspaces/{ws_id}/skills", headers=h)).json()
        skill_id = skills[0]["id"]

        created = (
            await c.post(
                f"/v1/workspaces/{ws_id}/mariuses",
                headers=h,
                json={"name": "Marin", "role": "Backend", "skills": [],
                      "skill_ids": [], "adapter_type": "echo", "adapter_config": {}},
            )
        ).json()
        marius_id = created["id"]

        edited = await c.patch(
            f"/v1/workspaces/{ws_id}/mariuses/{marius_id}",
            headers=h,
            json={"role": "Reviewer", "skill_ids": [skill_id]},
        )
    assert edited.status_code == 200, edited.text
    data = edited.json()
    assert data["role"] == "Reviewer"
    assert data["skill_ids"] == [skill_id]


async def test_custom_skill_is_workspace_scoped():
    async with await _client() as c:
        # User A creates a custom skill
        token_a, ws_a = await _register(c, "a@armarius.dev")
        ha = {"Authorization": f"Bearer {token_a}"}
        await c.post(
            f"/v1/workspaces/{ws_a}/skills",
            headers=ha,
            json={"name": "Secret Sauce", "description": "A-only", "kind": "http"},
        )
        a_skills = (await c.get(f"/v1/workspaces/{ws_a}/skills", headers=ha)).json()
        assert any(s["slug"] == "secret-sauce" for s in a_skills)

        # User B does not see A's custom skill in their own workspace
        token_b, ws_b = await _register(c, "b@armarius.dev")
        hb = {"Authorization": f"Bearer {token_b}"}
        b_skills = (await c.get(f"/v1/workspaces/{ws_b}/skills", headers=hb)).json()
    assert not any(s["slug"] == "secret-sauce" for s in b_skills)
    # ...but B still has the built-in
    assert any(s["slug"] == "armarius-http" for s in b_skills)
