"""Skill Shop + agent (Marius) edit flow tests."""

from __future__ import annotations

import asyncio

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


async def test_provision_agent_links_skill_and_invite_has_steps():
    async with await _client() as c:
        token, ws_id = await _register(c, "prov@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        skills = (await c.get(f"/v1/workspaces/{ws_id}/skills", headers=h)).json()
        # Look up by slug — a bare skills[0] is order-fragile now that there are two builtins.
        skill_id = next(s["id"] for s in skills if s["slug"] == "armarius-http")

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
    # Enroll-and-wait (API_CONTRACT §4.1): no token at invite — an enrollment_code instead.
    assert data["agent_token"] is None
    assert data["enrollment_code"]
    assert data["invite_status"] == "invited"
    # Invite advertises enroll-and-wait + the skill install + the credential file.
    assert "ENROLL AND WAIT" in data["invite"]
    assert data["enrollment_code"] in data["invite"]
    assert "INSTALL YOUR SKILLS" in data["invite"]
    assert "Armarius HTTP API" in data["invite"]
    assert "~/.armarius/credentials/" in data["invite"]
    # Skills install via the agent bundle endpoint (no more "(no source URL)" dead end).
    assert "/agent/skills/armarius-http" in data["invite"]
    # Connection-only invite (#43): no project context, and no task-loop STEP 4 — work
    # happens later in a separate wake session that carries its own context.
    assert '"project"' not in data["invite"]
    assert "project:" not in data["invite"]
    assert "STEP 4" not in data["invite"]
    assert "WORK THE LOOP" not in data["invite"]


async def test_inviting_agent_does_not_create_a_project():
    """#49: inviting an agent is a connection step (#43) — it must NOT conjure a
    "General" project. New workspaces stay empty until the patron commissions one."""
    async with await _client() as c:
        token, ws_id = await _register(c, "noproj@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        before = (await c.get(f"/v1/workspaces/{ws_id}/projects", headers=h)).json()
        assert before == []

        created = await c.post(
            f"/v1/workspaces/{ws_id}/mariuses",
            headers=h,
            json={"name": "Marin", "role": "Backend", "skills": [],
                  "skill_ids": [], "adapter_type": "echo", "adapter_config": {}},
        )
        assert created.status_code == 201, created.text

        after = (await c.get(f"/v1/workspaces/{ws_id}/projects", headers=h)).json()
    assert after == []  # still no project after inviting an agent


async def test_edit_agent_updates_skills():
    async with await _client() as c:
        token, ws_id = await _register(c, "edit@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        skills = (await c.get(f"/v1/workspaces/{ws_id}/skills", headers=h)).json()
        skill_id = next(s["id"] for s in skills if s["slug"] == "armarius-http")

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
    """An onboarded agent installs a multi-file skill via the JSON bundle endpoint."""
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

        # Provision a Marius linked to that skill, approve it, then recover its token.
        created = (
            await c.post(
                f"/v1/workspaces/{ws_id}/mariuses",
                headers=h,
                json={"name": "Marin", "role": "Backend", "skills": [],
                      "skill_ids": [skill["id"]], "adapter_type": "echo", "adapter_config": {}},
            )
        ).json()
        mid, code = created["id"], created["enrollment_code"]
        # enroll moves invited→pending_review then HOLDS until approval — run the patron's
        # approve concurrently (approve is a no-op 409 until enroll sets pending_review).
        enroll_task = asyncio.create_task(
            c.post("/agent/enroll", json={"marius_id": mid, "enrollment_code": code})
        )
        for _ in range(100):
            r = await c.post(f"/v1/workspaces/{ws_id}/mariuses/{mid}/approve", headers=h)
            if r.status_code == 200:
                break
            await asyncio.sleep(0.02)
        else:
            raise AssertionError("approve never reached pending_review")
        enrolled = await asyncio.wait_for(enroll_task, timeout=10)
        assert enrolled.status_code == 200, enrolled.text
        agent_token = enrolled.json()["agent_token"]
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
