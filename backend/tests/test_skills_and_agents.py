"""Skill Shop + agent (Marius) edit flow tests."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.application.use_cases.skills import BUILTIN_SKILLS
from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.database.engine import init_db
from armarius.main import app
from armarius.presentation.container import build_container
from tests.support.agents import invite_agent
from tests.support.runs import open_run

#: Tên hiển thị của kỹ năng dựng sẵn, đọc thẳng từ chỗ khai nó. Viết cứng vào đây thì bài này
#: đỏ mỗi lần đổi tên tờ hướng dẫn — mà tên tờ hướng dẫn không phải thứ bài này nói về.
_BUILTIN_NAME = BUILTIN_SKILLS[0]["name"]


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


async def test_creating_an_agent_links_its_skills():
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
    # The linked skill is persisted on the agent. It reaches the machine with the work that
    # needs it (FR-011b), not through a push at creation time.
    assert data["skill_ids"] == [skill_id]
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
    assert data["id"]
    assert after == []  # still no project after inviting an agent


async def test_the_directory_says_nothing_about_an_invite_lifecycle():
    """Một agent vừa thêm là một agent dùng được ngay — không có bước duyệt nào để chờ.

    Trạng thái ấy từng được khai ra trên danh bạ, và nó chỉ đánh dấu đúng một mốc: lúc token
    riêng của agent được đúc (FR-014a). Không còn token thì trạng thái ấy không mô tả gì, và
    một trường luôn trả về cùng một giá trị là một trường dạy người đọc rằng có thứ gì đó
    thay đổi được."""
    async with await _client() as c:
        token, ws_id = await _register(c, "pending@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        data = await invite_agent(c, ws_id, h, name="Knocker")
        mid = data["id"]

        directory = (await c.get(f"/v1/workspaces/{ws_id}/mariuses", headers=h)).json()
    row = next(m for m in directory if m["id"] == mid)
    assert "invite_status" not in row
    assert "approved_at" not in row
    # Cái nó *có* nói là thứ vẫn đổi thật: agent ấy đang sống hay không.
    assert row["liveness"] == "offline"


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
    # ...but B still has the built-in
    assert any(s["slug"] == "armarius-http" for s in b_skills)


async def test_an_agent_has_no_road_left_to_fetch_its_own_skills():
    """There is no longer anywhere for an agent to go and get its skills (FR-011c).

    They arrive with the work: written onto the machine that runs the agent, as real files,
    before the agent reads its first line (FR-011b). A road that let an agent fetch them
    afterwards would be a second answer to *what skills does this agent have* — and the two
    would disagree exactly when it mattered, because one of them is rebuilt every run and the
    other is whatever was there last time.

    Checked as a **404 rather than as an absence in the code**, because that is what anything
    still calling the old road will actually meet.
    """
    async with await _client() as c:
        token, ws_id = await _register(c, "bundle@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        made = await c.post(
            f"/v1/workspaces/{ws_id}/skills/manual",
            headers=h,
            json={"name": "Bundle Test", "description": "multi-file"},
        )
        assert made.status_code == 201, made.text
        skill = made.json()

        created = await invite_agent(c, ws_id, h, name="Marin", skill_ids=[skill["id"]])
        # A live run of that very agent, which is the strongest caller there is on these
        # routes: the 404 is the road being gone, not a credential being refused.
        ah = (await open_run(marius_id=created["id"])).headers

        assert (await c.get("/agent/skills", headers=ah)).status_code == 404
        assert (await c.get(f"/agent/skills/{skill['slug']}", headers=ah)).status_code == 404
        assert (
            await c.post(f"/agent/skills/{skill['slug']}/installed", headers=ah)
        ).status_code == 404


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
            await uow.commit()

        skills = (await c.get(f"/v1/workspaces/{ws_id}/skills", headers=h)).json()
        refreshed = next(s for s in skills if s["slug"] == "armarius-http")
        assert refreshed["files"]["SKILL.md"] != "old shipped copy"

        # Now the owner edits the same skill by hand. `update_files` stamps `updated_at`,
        # and that stamp is the whole difference: a shipped copy never has one, so it is
        # what tells "we changed this upstream" apart from "the owner changed this here".
        async with make_uow() as uow:
            edited = await uow.skills.get_by_slug(UUID(ws_id), "armarius-http")
            edited.files = {"SKILL.md": "owner's custom copy"}
            edited.updated_at = utcnow()
            await uow.skills.update(edited)
            await uow.commit()

        skills = (await c.get(f"/v1/workspaces/{ws_id}/skills", headers=h)).json()
    kept = next(s for s in skills if s["slug"] == "armarius-http")
    assert kept["files"]["SKILL.md"] == "owner's custom copy"  # preserved


async def test_seed_prunes_delisted_builtin_skills():
    """A builtin no longer shipped (e.g. the retired armarius-onboarder) is pruned from a
    workspace seeded by an older version, on the next skills load; real builtins survive and
    a manual skill is never touched (#105)."""
    from uuid import UUID

    from armarius.domain.entities.skill import Skill
    from armarius.infrastructure.persistence.unit_of_work import make_uow
    from armarius.shared.clock import utcnow

    async with await _client() as c:
        token, ws_id = await _register(c, "prune@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        # A manual skill the owner made (must NOT be pruned).
        made = await c.post(
            f"/v1/workspaces/{ws_id}/skills/manual", headers=h,
            json={"name": "Keeper", "description": "owner's own"},
        )
        assert made.status_code == 201, made.text
        # Simulate a stale builtin seeded before it was retired.
        async with make_uow() as uow:
            await uow.skills.add(Skill(
                workspace_id=UUID(ws_id), slug="armarius-onboarder",
                name="Armarius Onboarder", description="retired playbook",
                source="builtin", source_url="/static/skills/armarius-onboarder/SKILL.md",
                files={"SKILL.md": "old"}, created_at=utcnow(),
            ))
            await uow.commit()
        # The GET triggers seed_builtins → prune.
        after = (await c.get(f"/v1/workspaces/{ws_id}/skills", headers=h)).json()
    slugs = {s["slug"] for s in after}
    assert "armarius-onboarder" not in slugs, slugs  # de-listed builtin pruned
    assert "armarius-http" in slugs  # a real builtin survives
    assert any(s["name"] == "Keeper" for s in after)  # manual skill untouched


async def test_linking_more_skills_merges_them():
    """Issue #74: the patron can link more skills to an agent afterwards. New links merge,
    de-duped and in order. Nothing is pushed — the skill travels down with the work."""
    async with await _client() as c:
        token, ws_id = await _register(c, "install@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        skills = (await c.get(f"/v1/workspaces/{ws_id}/skills", headers=h)).json()
        http_id = next(s["id"] for s in skills if s["slug"] == "armarius-http")
        # A second skill to link afterwards. The owner's own rather than a second builtin:
        # this test is about merging links, and tying it to how many skills happen to ship
        # would make it fail the next time that list changes.
        second = await c.post(
            f"/v1/workspaces/{ws_id}/skills/manual",
            headers=h,
            json={"name": "Bảng màu", "description": "owner's own"},
        )
        assert second.status_code == 201, second.text
        second_id = second.json()["id"]
        second_slug = second.json()["slug"]

        # Invite with one skill already linked.
        data = await invite_agent(c, ws_id, h, name="Marin", skill_ids=[http_id])
        mid = data["id"]

        # Post-invite: link the second skill.
        r = await c.post(
            f"/v1/workspaces/{ws_id}/mariuses/{mid}/install-skills",
            headers=h,
            json={"skill_ids": [second_id]},
        )
        # Marius.skills (display NAMES) must mirror skill_ids so the UI pills reflect the
        # link — a regression here means the pill never appears post-invite (#74).
        listed = (await c.get(f"/v1/workspaces/{ws_id}/mariuses", headers=h)).json()
    assert r.status_code == 200, r.text
    out = r.json()
    # The new link is merged in (both skills now linked, order preserved, no dupes).
    assert out["skill_ids"] == [http_id, second_id]
    assert out["installed"] == [second_slug]  # only the newly linked slug
    marin = next(m for m in listed if m["id"] == mid)
    assert marin["skills"] == [_BUILTIN_NAME, "Bảng màu"], marin["skills"]


async def test_relinking_a_skill_the_agent_already_has_does_not_duplicate_it():
    """Naming a skill that is already linked leaves one link, and puts it back to `pending`.

    That second half matters: it is how a corrected skill reaches an agent again. The old
    behaviour dropped already-linked slugs, so a fix never propagated (#74/#105)."""
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
    assert out["installed"] == ["armarius-http"]  # named again even though already linked
    marin = next(m for m in listed if m["id"] == mid)
    # No install state to carry any more: linking *is* the install, because the files are
    # written onto the machine with every run (FR-011b, FR-011c).
    assert "skill_installs" not in marin
    assert marin["skill_ids"] == [http_id]


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

