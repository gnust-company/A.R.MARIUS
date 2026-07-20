"""Skill Shop + agent (Marius) edit flow tests."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.database.engine import init_db
from armarius.main import app
from armarius.presentation.container import build_container
from tests.support.agents import (
    agent_token_for,
    invite_agent,
)


@pytest.fixture(autouse=True)
async def _bootstrap():
    await init_db()
    container = build_container()
    # Zero-delay echo so each invite's setup-push is instant (default 0.4s/event × ~9).
    container.registry.register(EchoAdapter(step_delay=0.0))
    app.state.container = container
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
    assert any(s["slug"] == "armarius-mcp" for s in body)
    builtin = next(s for s in body if s["slug"] == "armarius-http")
    assert builtin["source"] == "builtin"
    mcp_builtin = next(s for s in body if s["slug"] == "armarius-mcp")
    assert mcp_builtin["source"] == "builtin"


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


async def test_provision_agent_links_skill_and_pushes_setup():
    async with await _client() as c:
        token, ws_id = await _register(c, "prov@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        skills = (await c.get(f"/v1/workspaces/{ws_id}/skills", headers=h)).json()
        skill_id = next(s["id"] for s in skills if s["slug"] == "armarius-http")

        data = await invite_agent(
            c,
            ws_id,
            h,
            name="Marin",
            skills=["api"],
            skill_ids=[skill_id],
        )
    # The linked skill is persisted on the agent.
    assert data["skill_ids"] == [skill_id]
    # Operator-invite (#63): approved at invite time, setup pushed, token never leaked.
    assert data["invite_status"] == "approved"
    assert data["send_status"] == "sent"
    assert "agent_token" not in data
    assert "invite" not in data


async def test_inviting_agent_does_not_create_a_project():
    """#49: inviting an agent is a connection step (#43) — it must NOT conjure a
    "General" project. New workspaces stay empty until the patron commissions one."""
    async with await _client() as c:
        token, ws_id = await _register(c, "noproj@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        before = (await c.get(f"/v1/workspaces/{ws_id}/projects", headers=h)).json()
        assert before == []

        data = await invite_agent(c, ws_id, h, name="Marin")

        after = (await c.get(f"/v1/workspaces/{ws_id}/projects", headers=h)).json()
    assert data["invite_status"] == "approved"
    assert after == []  # still no project after inviting an agent


async def test_directory_exposes_invite_status():
    """The directory list carries invite_status; under operator-invite an agent is
    "approved" the moment it is invited (#63)."""
    async with await _client() as c:
        token, ws_id = await _register(c, "pending@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        data = await invite_agent(c, ws_id, h, name="Knocker")
        mid = data["id"]

        directory = (await c.get(f"/v1/workspaces/{ws_id}/mariuses", headers=h)).json()
    assert next(m for m in directory if m["id"] == mid)["invite_status"] == "approved"


async def test_edit_agent_updates_skills():
    async with await _client() as c:
        token, ws_id = await _register(c, "edit@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        skills = (await c.get(f"/v1/workspaces/{ws_id}/skills", headers=h)).json()
        skill_id = next(s["id"] for s in skills if s["slug"] == "armarius-http")

        created = await invite_agent(c, ws_id, h, name="Marin")
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
        # User A authors a skill manually (generated from a SKILL.md template).
        token_a, ws_a = await _register(c, "a@armarius.dev")
        ha = {"Authorization": f"Bearer {token_a}"}
        created = await c.post(
            f"/v1/workspaces/{ws_a}/skills/manual",
            headers=ha,
            json={"name": "Secret Sauce", "description": "A-only"},
        )
        assert created.status_code == 201, created.text
        sauce = created.json()
        assert sauce["slug"] == "secret-sauce"
        assert sauce["source"] == "manual"
        # A manually authored skill ships a generated SKILL.md the author can edit.
        assert "SKILL.md" in sauce["files"]
        a_skills = (await c.get(f"/v1/workspaces/{ws_a}/skills", headers=ha)).json()
        assert any(s["slug"] == "secret-sauce" for s in a_skills)

        # Editing files persists and re-derives name/description from the frontmatter.
        new_files = {"SKILL.md": "---\nname: Renamed Sauce\ndescription: edited\n---\n# body"}
        edited = await c.put(
            f"/v1/workspaces/{ws_a}/skills/{sauce['id']}",
            headers=ha,
            json={"files": new_files},
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["name"] == "Renamed Sauce"

        # User B does not see A's skill in their own workspace
        token_b, ws_b = await _register(c, "b@armarius.dev")
        hb = {"Authorization": f"Bearer {token_b}"}
        b_skills = (await c.get(f"/v1/workspaces/{ws_b}/skills", headers=hb)).json()
    assert not any(s["slug"] == "secret-sauce" for s in b_skills)
    # ...but B still has both built-ins
    assert any(s["slug"] == "armarius-http" for s in b_skills)
    assert any(s["slug"] == "armarius-mcp" for s in b_skills)


async def test_agent_can_fetch_linked_skill_bundle():
    """An invited agent installs a multi-file skill via the JSON bundle endpoint."""
    async with await _client() as c:
        token, ws_id = await _register(c, "bundle@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}

        # Author a manual skill, then give it a sibling file (multi-file tree).
        made = await c.post(
            f"/v1/workspaces/{ws_id}/skills/manual",
            headers=h,
            json={"name": "Bundle Test", "description": "multi-file"},
        )
        assert made.status_code == 201, made.text
        skill = made.json()
        files = {
            "SKILL.md": "---\nname: Bundle Test\ndescription: multi-file\n---\n# body",
            "scripts/run.sh": "echo hi\n",
        }
        await c.put(
            f"/v1/workspaces/{ws_id}/skills/{skill['id']}", headers=h, json={"files": files}
        )

        # Invite an agent linked to that skill; read its minted token from the repo (#63).
        created = await invite_agent(
            c, ws_id, h, name="Marin", skill_ids=[skill["id"]]
        )
        agent_token = await agent_token_for(created["id"])
        ah = {"Authorization": f"Bearer {agent_token}"}

        # /agent/skills lists the linked skill with its file count.
        listed = await c.get("/agent/skills", headers=ah)
        assert listed.status_code == 200, listed.text
        summary = next(s for s in listed.json() if s["slug"] == skill["slug"])
        assert summary["file_count"] == 2

        # /agent/skills/{slug} returns the full file tree.
        bundle = await c.get(f"/agent/skills/{skill['slug']}", headers=ah)
        assert bundle.status_code == 200, bundle.text
        assert bundle.json()["files"] == files

        # A slug the agent isn't linked to → 404; no token → 401.
        assert (await c.get("/agent/skills/nope", headers=ah)).status_code == 404
        assert (await c.get("/agent/skills")).status_code == 401


async def test_builtin_content_refreshes_unless_owner_edited():
    """Shipping a new builtin SKILL.md reaches workspaces seeded earlier (#15) —
    but an owner-edited copy (updated_at set) is never clobbered."""
    from uuid import UUID

    from armarius.infrastructure.persistence.unit_of_work import make_uow
    from armarius.shared.clock import utcnow

    async with await _client() as c:
        token, ws_id = await _register(c, "refresh@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}

        # Simulate a workspace seeded before the on-disk SKILL.md changed.
        async with make_uow() as uow:
            stale = await uow.skills.get_by_slug(UUID(ws_id), "armarius-http")
            stale.files = {"SKILL.md": "old shipped copy"}
            await uow.skills.update(stale)
            # ...and one the owner edited by hand (update_files stamps updated_at).
            edited = await uow.skills.get_by_slug(UUID(ws_id), "armarius-mcp")
            edited.files = {"SKILL.md": "owner's custom copy"}
            edited.updated_at = utcnow()
            await uow.skills.update(edited)
            await uow.commit()

        skills = (await c.get(f"/v1/workspaces/{ws_id}/skills", headers=h)).json()
    http_skill = next(s for s in skills if s["slug"] == "armarius-http")
    mcp_skill = next(s for s in skills if s["slug"] == "armarius-mcp")
    assert http_skill["files"]["SKILL.md"] != "old shipped copy"  # refreshed
    assert mcp_skill["files"]["SKILL.md"] == "owner's custom copy"  # preserved


async def test_install_skills_links_and_pushes_install_prompt():
    """Issue #74: after an agent is invited, the patron can link MORE skills and the
    system pushes a one-time install prompt. New links merge (de-duped); the push is
    best-effort and returns send_status."""
    async with await _client() as c:
        token, ws_id = await _register(c, "install@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        skills = (await c.get(f"/v1/workspaces/{ws_id}/skills", headers=h)).json()
        http_id = next(s["id"] for s in skills if s["slug"] == "armarius-http")
        mcp_id = next(s["id"] for s in skills if s["slug"] == "armarius-mcp")

        # Invite with one skill already linked.
        data = await invite_agent(c, ws_id, h, name="Marin", skill_ids=[http_id])
        mid = data["id"]

        # Post-invite: link the second skill.
        r = await c.post(
            f"/v1/workspaces/{ws_id}/mariuses/{mid}/install-skills",
            headers=h,
            json={"skill_ids": [mcp_id]},
        )
        # Marius.skills (display NAMES) must mirror skill_ids so the UI pills reflect the
        # link — a regression here means the pill never appears post-invite (#74).
        listed = (await c.get(f"/v1/workspaces/{ws_id}/mariuses", headers=h)).json()
    assert r.status_code == 200, r.text
    out = r.json()
    # The new link is merged in (both skills now linked, order preserved, no dupes).
    assert out["skill_ids"] == [http_id, mcp_id]
    assert out["installed"] == ["armarius-mcp"]  # only the newly linked slug
    # The echo runtime accepts the push.
    assert out["send_status"] == "sent"
    marin = next(m for m in listed if m["id"] == mid)
    assert marin["skills"] == ["Armarius HTTP API", "Armarius MCP"], marin["skills"]


async def test_install_skills_repushes_already_linked():
    """Re-installing a skill the agent already has does NOT duplicate the link, but DOES
    re-push it — so a FIXED/updated skill reaches the agent — and marks it `pending` (#74/#105).
    (The old behaviour dropped already-linked slugs, so a corrected skill never propagated.)"""
    async with await _client() as c:
        token, ws_id = await _register(c, "idem@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        skills = (await c.get(f"/v1/workspaces/{ws_id}/skills", headers=h)).json()
        http_id = next(s["id"] for s in skills if s["slug"] == "armarius-http")

        data = await invite_agent(c, ws_id, h, name="Marin", skill_ids=[http_id])
        mid = data["id"]

        r = await c.post(
            f"/v1/workspaces/{ws_id}/mariuses/{mid}/install-skills",
            headers=h,
            json={"skill_ids": [http_id]},
        )
        listed = (await c.get(f"/v1/workspaces/{ws_id}/mariuses", headers=h)).json()
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["skill_ids"] == [http_id]  # no duplicate link
    assert out["installed"] == ["armarius-http"]  # re-pushed even though already linked
    assert out["send_status"] == "sent"
    marin = next(m for m in listed if m["id"] == mid)
    assert marin["skill_installs"] == {"armarius-http": "pending"}  # awaiting the agent's confirm


async def test_agent_confirms_skill_install():
    """After a push, the agent flips its linked skill to `installed` via the confirm callback;
    a slug it isn't linked to → 404 (#74/#105)."""
    async with await _client() as c:
        token, ws_id = await _register(c, "confirm@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        skills = (await c.get(f"/v1/workspaces/{ws_id}/skills", headers=h)).json()
        http_id = next(s["id"] for s in skills if s["slug"] == "armarius-http")

        created = await invite_agent(c, ws_id, h, name="Marin", skill_ids=[http_id])
        mid = created["id"]
        # Push it so the state starts at pending.
        await c.post(
            f"/v1/workspaces/{ws_id}/mariuses/{mid}/install-skills",
            headers=h,
            json={"skill_ids": [http_id]},
        )

        agent_token = await agent_token_for(mid)
        ah = {"Authorization": f"Bearer {agent_token}"}

        # A slug the agent isn't linked to → 404.
        assert (await c.post("/agent/skills/nope/installed", headers=ah)).status_code == 404

        # Confirm the real one → installed.
        ok = await c.post("/agent/skills/armarius-http/installed", headers=ah)
        assert ok.status_code == 200, ok.text
        assert ok.json() == {"slug": "armarius-http", "status": "installed"}

        listed = (await c.get(f"/v1/workspaces/{ws_id}/mariuses", headers=h)).json()
    marin = next(m for m in listed if m["id"] == mid)
    assert marin["skill_installs"] == {"armarius-http": "installed"}


async def test_install_skills_on_other_workspace_is_404():
    """An agent from workspace B can't be touched via workspace A's path (multi-tenant)."""
    async with await _client() as c:
        token_a, ws_a = await _register(c, "owner_a@armarius.dev")
        _, ws_b = await _register(c, "owner_b@armarius.dev")
        h_a = {"Authorization": f"Bearer {token_a}"}
        skills = (await c.get(f"/v1/workspaces/{ws_a}/skills", headers=h_a)).json()
        http_id = next(s["id"] for s in skills if s["slug"] == "armarius-http")

        data = await invite_agent(c, ws_a, h_a, name="Marin")
        mid = data["id"]

        # Call install-skills through workspace B's path → 404 (agent not found there).
        r = await c.post(
            f"/v1/workspaces/{ws_b}/mariuses/{mid}/install-skills",
            headers=h_a,
            json={"skill_ids": [http_id]},
        )
    assert r.status_code == 404

