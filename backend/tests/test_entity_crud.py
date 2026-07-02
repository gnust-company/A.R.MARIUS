"""Entity CRUD — delete/edit for Workspace, Skill and Marius (issue #19).

Every entity you can create must be editable + deletable, with ownership scoping,
constraint guards (built-in skills, the Workspace Agent, the last workspace) and 404s.
"""

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


async def _register(c: AsyncClient, email: str) -> tuple[str, str]:
    """Register a user; return (access_token, personal_workspace_id)."""
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["tokens"]["access_token"]
    ws = await c.get("/v1/workspaces", headers={"Authorization": f"Bearer {token}"})
    return token, ws.json()[0]["id"]


async def _make_workspace(c: AsyncClient, h: dict, name: str) -> str:
    r = await c.post("/v1/workspaces", headers=h, json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ─────────────────────────────────────────────────────────────── workspace edit
async def test_rename_workspace():
    async with await _client() as c:
        token, ws_id = await _register(c, "wsrename@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        r = await c.patch(f"/v1/workspaces/{ws_id}", headers=h, json={"name": "Atelier"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Atelier"
    assert r.json()["slug"] == "atelier"


async def test_rename_workspace_not_owned_is_404():
    async with await _client() as c:
        _, ws_a = await _register(c, "wsa@armarius.dev")
        token_b, _ = await _register(c, "wsb@armarius.dev")
        hb = {"Authorization": f"Bearer {token_b}"}
        r = await c.patch(f"/v1/workspaces/{ws_a}", headers=hb, json={"name": "Nope"})
    assert r.status_code == 404


# ───────────────────────────────────────────────────────────── workspace delete
async def test_delete_workspace_removes_it_and_cascades():
    async with await _client() as c:
        token, _ = await _register(c, "wsdel@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        # A second workspace, filled with a project + a manual skill + an agent.
        ws_id = await _make_workspace(c, h, "Scratch")
        await c.post(
            f"/v1/workspaces/{ws_id}/projects", headers=h, json={"name": "Thing"}
        )
        await c.post(
            f"/v1/workspaces/{ws_id}/skills/manual",
            headers=h,
            json={"name": "Scratch Skill", "description": "x"},
        )
        await c.post(
            f"/v1/workspaces/{ws_id}/mariuses",
            headers=h,
            json={"name": "Aide", "role": "Backend", "skills": [], "skill_ids": [],
                  "adapter_type": "echo", "adapter_config": {}},
        )

        deleted = await c.delete(f"/v1/workspaces/{ws_id}", headers=h)
        assert deleted.status_code == 204, deleted.text

        remaining = (await c.get("/v1/workspaces", headers=h)).json()
    assert all(w["id"] != ws_id for w in remaining)


async def test_delete_only_workspace_is_rejected():
    async with await _client() as c:
        token, ws_id = await _register(c, "wsonly@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        r = await c.delete(f"/v1/workspaces/{ws_id}", headers=h)
    assert r.status_code == 400
    assert "only workspace" in r.json()["detail"]


async def test_delete_workspace_not_owned_is_404():
    async with await _client() as c:
        token_a, _ = await _register(c, "wso-a@armarius.dev")
        ha = {"Authorization": f"Bearer {token_a}"}
        ws_a = await _make_workspace(c, ha, "A-only")
        token_b, _ = await _register(c, "wso-b@armarius.dev")
        hb = {"Authorization": f"Bearer {token_b}"}
        r = await c.delete(f"/v1/workspaces/{ws_a}", headers=hb)
    assert r.status_code == 404


# ───────────────────────────────────────────────────────────────── skill delete
async def test_delete_manual_skill():
    async with await _client() as c:
        token, ws_id = await _register(c, "skdel@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        made = await c.post(
            f"/v1/workspaces/{ws_id}/skills/manual",
            headers=h,
            json={"name": "Disposable", "description": "x"},
        )
        skill_id = made.json()["id"]
        gone = await c.delete(f"/v1/workspaces/{ws_id}/skills/{skill_id}", headers=h)
        assert gone.status_code == 204, gone.text
        skills = (await c.get(f"/v1/workspaces/{ws_id}/skills", headers=h)).json()
    assert all(s["id"] != skill_id for s in skills)


async def test_delete_builtin_skill_is_rejected():
    async with await _client() as c:
        token, ws_id = await _register(c, "skbuiltin@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        skills = (await c.get(f"/v1/workspaces/{ws_id}/skills", headers=h)).json()
        builtin_id = next(s["id"] for s in skills if s["slug"] == "armarius-http")
        r = await c.delete(f"/v1/workspaces/{ws_id}/skills/{builtin_id}", headers=h)
    assert r.status_code == 400
    assert "Built-in" in r.json()["detail"]


async def test_delete_skill_not_owned_is_404():
    async with await _client() as c:
        token_a, ws_a = await _register(c, "ska@armarius.dev")
        ha = {"Authorization": f"Bearer {token_a}"}
        made = await c.post(
            f"/v1/workspaces/{ws_a}/skills/manual",
            headers=ha,
            json={"name": "A Secret", "description": "x"},
        )
        skill_id = made.json()["id"]
        token_b, ws_b = await _register(c, "skb@armarius.dev")
        hb = {"Authorization": f"Bearer {token_b}"}
        # B deletes via their own (owned) workspace path → skill isn't in it → 404.
        r = await c.delete(f"/v1/workspaces/{ws_b}/skills/{skill_id}", headers=hb)
    assert r.status_code == 404


# ──────────────────────────────────────────────────────────────── marius delete
async def test_delete_marius():
    async with await _client() as c:
        token, ws_id = await _register(c, "mdel@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        created = await c.post(
            f"/v1/workspaces/{ws_id}/mariuses",
            headers=h,
            json={"name": "Temp", "role": "Backend", "skills": [], "skill_ids": [],
                  "adapter_type": "echo", "adapter_config": {}},
        )
        marius_id = created.json()["id"]
        gone = await c.delete(f"/v1/workspaces/{ws_id}/mariuses/{marius_id}", headers=h)
        assert gone.status_code == 204, gone.text
        directory = (await c.get(f"/v1/workspaces/{ws_id}/mariuses", headers=h)).json()
    assert all(m["id"] != marius_id for m in directory)


async def test_delete_workspace_agent_is_rejected():
    async with await _client() as c:
        token, ws_id = await _register(c, "mwa@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        # A Marius whose role is the Workspace Agent role is system-managed.
        created = await c.post(
            f"/v1/workspaces/{ws_id}/mariuses",
            headers=h,
            json={"name": "Host", "role": "Workspace Agent", "skills": [], "skill_ids": [],
                  "adapter_type": "echo", "adapter_config": {}},
        )
        marius_id = created.json()["id"]
        r = await c.delete(f"/v1/workspaces/{ws_id}/mariuses/{marius_id}", headers=h)
    assert r.status_code == 400
    assert "Workspace Agent" in r.json()["detail"]


async def test_delete_marius_missing_is_404():
    async with await _client() as c:
        token, ws_id = await _register(c, "mmiss@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        r = await c.delete(
            f"/v1/workspaces/{ws_id}/mariuses/00000000-0000-0000-0000-000000000000",
            headers=h,
        )
    assert r.status_code == 404
