"""Contract-conformance — Projects, roster and the two seating doors (API_CONTRACT §3).

Drives ProjectService over HTTP: create-with-brief, project detail/brief/delete, the leader
seat and the bench, SETUP→ACTIVE activation, and workspace scoping (cross-workspace = 404).

*Rewritten 2026-09-04 (T039j)*: there is no role CRUD here any more, because there are no
role doors. Putting an agent on a project is one call that names no role — the tests that
used to add, edit, rename and delete roles measured a road that made the patron invent a
description of the work beside the instructions already written on the agent (FR-007l).
"""

from __future__ import annotations

from uuid import UUID

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from armarius.infrastructure.database import engine as engine_mod
from armarius.infrastructure.database.models import (
    ArtifactModel,
    RoleModel,
    SeatGrantModel,
    TaskModel,
)
from armarius.main import app
from tests.support.projects import force_operating


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(c: AsyncClient, email: str) -> tuple[str, str]:
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["tokens"]["access_token"]
    ws = await c.get("/v1/workspaces", headers={"Authorization": f"Bearer {token}"})
    return token, ws.json()[0]["id"]


def _plan(**overrides) -> dict:
    plan = {
        "name": "Apollo",
        "description": "ship it",
        "objective": "Launch the platform",
        "leader": {"description": "lead", "marius_id": None},
    }
    plan.update(overrides)
    return plan


async def _create(c: AsyncClient, ws_id: str, h: dict, **overrides) -> dict:
    r = await c.post(
        f"/v1/workspaces/{ws_id}/projects", headers=h, json=_plan(**overrides)
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _online_agent(c: AsyncClient, ws_id: str, h: dict, name: str) -> str:
    """Invite with gateway creds → /agent/me (a signal) so the agent is ONLINE (#63)."""
    from tests.support.agents import invite_and_online

    mid, _token = await invite_and_online(c, ws_id, h, name=name)
    return mid


async def test_create_with_plan_starts_setup_with_roster() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "p1@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        proj = await _create(c, ws_id, h)
    assert proj["status"] == "setup"
    assert proj["objective"] == "Launch the platform"
    keys = {r["key"] for r in proj["roster"]}
    assert keys == {"leader", "members"}
    leader = next(r for r in proj["roster"] if r["key"] == "leader")
    assert leader["is_leader"] is True and leader["seats"] == 1
    # #93: mô tả vai trò Leader nay lưu vào MỘT trường `description` (trước rơi vào
    # `responsibilities` chết) và phơi ra roster ⇒ sẽ tới được prompt của Leader.
    assert leader["description"] == "lead"


async def test_list_projects_exposes_status() -> None:
    """Sprint 6 review fix: the project LIST endpoint exposes `status` so the FE grid
    renders a real status chip — previously `ProjectOut` dropped it and the FE showed the
    raw `projects.status.undefined` i18n key.
    """
    async with await _client() as c:
        token, ws_id = await _register(c, "liststatus@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        await _create(c, ws_id, h)
        listed = (await c.get(f"/v1/workspaces/{ws_id}/projects", headers=h)).json()
    assert listed, "expected the created project in the list"
    assert listed[0]["status"] == "setup"


async def test_list_projects_exposes_seat_counts() -> None:
    """The project LIST endpoint carries roster fill (seats_filled / seats_total) so the grid
    card shows the real count without opening the detail — previously the card read 0/0 for
    every un-opened project because `ProjectOut` had no seat data.
    """
    async with await _client() as c:
        token, ws_id = await _register(c, "seatcounts@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        proj = await _create(c, ws_id, h)  # the leader seat + a bench waiting for one
        pid = proj["id"]

        listed = (await c.get(f"/v1/workspaces/{ws_id}/projects", headers=h)).json()
        assert listed[0]["seats_total"] == 2
        assert listed[0]["seats_filled"] == 0

        # Seat the Leader → the list reflects the new fill.
        lead = await _online_agent(c, ws_id, h, "Lead")
        seated = await c.post(
            f"/v1/projects/{pid}/leader", headers=h, json={"marius_id": lead}
        )
        assert seated.status_code == 201, seated.text

        listed2 = (await c.get(f"/v1/workspaces/{ws_id}/projects", headers=h)).json()
        assert listed2[0]["seats_total"] == 2
        assert listed2[0]["seats_filled"] == 1

        # Two on the bench, and the card counts them both — the bench holds as many as sit
        # on it, so a project of three agents does not read as a project of two seats.
        for name in ("Dev-1", "Dev-2"):
            joined = await c.post(
                f"/v1/projects/{pid}/members",
                headers=h,
                json={"marius_id": await _online_agent(c, ws_id, h, name)},
            )
            assert joined.status_code == 201, joined.text

        listed3 = (await c.get(f"/v1/workspaces/{ws_id}/projects", headers=h)).json()
        assert listed3[0]["seats_total"] == 3
        assert listed3[0]["seats_filled"] == 3


async def test_a_plan_that_still_carries_roles_is_refused_rather_than_half_read() -> None:
    """A caller sending the old shape is told, not quietly obeyed (FR-007l).

    Ignoring the field would create a project with nobody on it and answer 201, and the
    patron would be looking at an empty team wondering which of their steps failed. The last
    dead parameter in this system was silently accepted for months for exactly that reason.
    """
    async with await _client() as c:
        token, ws_id = await _register(c, "p2@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        r = await c.post(
            f"/v1/workspaces/{ws_id}/projects",
            headers=h,
            json=_plan(roles=[{"title": "Backend", "seats": 1, "description": "API."}]),
        )
    assert r.status_code == 422, r.text


async def test_detail_patch_brief_and_delete() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "p3@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        proj = await _create(c, ws_id, h)
        pid = proj["id"]

        patched = await c.patch(
            f"/v1/projects/{pid}",
            headers=h,
            json={"github_url": "https://github.com/acme/apollo", "objective": "v2"},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["github_url"] == "https://github.com/acme/apollo"
        assert patched.json()["objective"] == "v2"

        deleted = await c.delete(f"/v1/projects/{pid}", headers=h)
        assert deleted.status_code == 204
        gone = await c.get(f"/v1/projects/{pid}", headers=h)
    assert gone.status_code == 404


async def test_there_is_no_door_here_that_makes_a_role() -> None:
    """Measured as absence, which is the only way this rule can be measured (FR-007l).

    All three used to exist — add a role, rename it, delete it — and the first of them was
    step one of putting an agent on a project.
    """
    async with await _client() as c:
        token, ws_id = await _register(c, "p4@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        pid = (await _create(c, ws_id, h))["id"]

        added = await c.post(
            f"/v1/projects/{pid}/roles",
            headers=h,
            json={"title": "QA", "seats": 2, "description": "Tests the work."},
        )
        edited = await c.patch(f"/v1/projects/{pid}/roles/members", headers=h, json={"seats": 3})
        removed = await c.delete(f"/v1/projects/{pid}/roles/members", headers=h)

    assert (added.status_code, edited.status_code, removed.status_code) == (404, 404, 404)


async def test_an_agent_joins_a_project_in_one_call_and_leaves_in_one() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "p5@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        pid = (await _create(c, ws_id, h))["id"]
        mid = await _online_agent(c, ws_id, h, "Backend-1")

        joined = await c.post(
            f"/v1/projects/{pid}/members", headers=h, json={"marius_id": mid}
        )
        assert joined.status_code == 201, joined.text
        # T199 — a seat is a live row; there is no status on the wire any more.
        assert "status" not in joined.json()

        agents = await c.get(f"/v1/projects/{pid}/agents", headers=h)
        assert agents.status_code == 200
        assert [a["marius_id"] for a in agents.json()] == [mid]

        left = await c.delete(f"/v1/projects/{pid}/members/{mid}", headers=h)
        assert left.status_code == 200, left.text
        assert left.json()["id"] == joined.json()["id"]
        agents2 = await c.get(f"/v1/projects/{pid}/agents", headers=h)
    assert agents2.json() == []


async def test_the_agents_named_in_the_plan_are_on_the_project_already() -> None:
    """Create and staff in one call, which is what the wizard's last step does."""
    async with await _client() as c:
        token, ws_id = await _register(c, "p5b@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        lead = await _online_agent(c, ws_id, h, "Lead")
        dev = await _online_agent(c, ws_id, h, "Dev")

        proj = await _create(
            c, ws_id, h,
            leader={"description": "lead", "marius_id": lead},
            members=[dev],
        )
        agents = await c.get(f"/v1/projects/{proj['id']}/agents", headers=h)

    assert {a["marius_id"] for a in agents.json()} == {lead, dev}
    # And it opened the planning gate on the way, without a second call.
    assert proj["status"] in ("setup", "planning")


async def test_an_agent_cannot_be_both_the_leader_and_a_member() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "p5c@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        pid = (await _create(c, ws_id, h))["id"]
        lead = await _online_agent(c, ws_id, h, "Lead")
        await c.post(f"/v1/projects/{pid}/leader", headers=h, json={"marius_id": lead})

        again = await c.post(f"/v1/projects/{pid}/members", headers=h, json={"marius_id": lead})

    assert again.status_code == 400, again.text
    assert again.json()["code"] == "agent_leads_this_project"


async def test_create_rejects_a_leader_without_a_description() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "noleaddesc@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        # An empty leader description is just as invalid as a worker's (strict #112).
        r = await c.post(
            f"/v1/workspaces/{ws_id}/projects",
            headers=h,
            json=_plan(leader={"description": "", "marius_id": None}),
        )
    assert r.status_code == 422, r.text


async def test_delete_project_cascades_children() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "cascade@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        pid = (await _create(c, ws_id, h))["id"]
        mid = await _online_agent(c, ws_id, h, "Backend-1")
        await c.post(f"/v1/projects/{pid}/members", headers=h, json={"marius_id": mid})
        # FR-003: a real task needs a project past the plan gate. Cascade-on-delete is
        # not what the gate is about, so step over it rather than replaying the loop.
        await force_operating(pid)
        task = await c.post(f"/v1/projects/{pid}/tasks", headers=h, json={"title": "T"})
        task_id = task.json()["id"]
        art = await c.post(
            f"/v1/tasks/{task_id}/artifacts",
            headers=h,
            json={"name": "PR", "kind": "link", "uri": "https://github.com/a/b/pull/1"},
        )
        assert art.status_code == 201, art.text

        deleted = await c.delete(f"/v1/projects/{pid}", headers=h)
        assert deleted.status_code == 204, deleted.text

    # No orphaned children remain (the bug SQLite hides with FK enforcement off; on
    # Postgres a bare project delete would instead 500 on the FK constraint).
    sm = engine_mod.get_sessionmaker()
    async with sm() as s:
        pid_u, task_u = UUID(pid), UUID(task_id)
        roles = await s.scalar(
            select(func.count()).select_from(RoleModel).where(RoleModel.project_id == pid_u)
        )
        grants = await s.scalar(
            select(func.count())
            .select_from(SeatGrantModel)
            .where(SeatGrantModel.project_id == pid_u)
        )
        tasks = await s.scalar(
            select(func.count()).select_from(TaskModel).where(TaskModel.project_id == pid_u)
        )
        arts = await s.scalar(
            select(func.count())
            .select_from(ArtifactModel)
            .where(ArtifactModel.task_id == task_u)
        )
    assert (roles, grants, tasks, arts) == (0, 0, 0, 0)


async def test_all_seats_granted_to_online_agents_opens_planning() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "p7@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        pid = (await _create(c, ws_id, h))["id"]
        leader = await _online_agent(c, ws_id, h, "Lead")
        worker = await _online_agent(c, ws_id, h, "Worker")

        await c.post(f"/v1/projects/{pid}/leader", headers=h, json={"marius_id": leader})
        mid_detail = await c.get(f"/v1/projects/{pid}", headers=h)
        assert mid_detail.json()["status"] == "setup"  # nobody on the bench yet

        await c.post(f"/v1/projects/{pid}/members", headers=h, json={"marius_id": worker})
        final = await c.get(f"/v1/projects/{pid}", headers=h)
    # FR-002: a full, online roster opens the *planning* gate — not the work.
    assert final.json()["status"] == "planning"


async def test_cross_workspace_project_is_404() -> None:
    async with await _client() as c:
        token_a, ws_a = await _register(c, "owner@armarius.dev")
        ha = {"Authorization": f"Bearer {token_a}"}
        pid = (await _create(c, ws_a, ha))["id"]

        token_b, _ = await _register(c, "intruder@armarius.dev")
        hb = {"Authorization": f"Bearer {token_b}"}
        r = await c.get(f"/v1/projects/{pid}", headers=hb)
    assert r.status_code == 404, r.text


async def test_create_task_carries_full_definition() -> None:
    """A manually created task persists its full definition — priority/due_date/
    definition_of_done/assigned_marius_id — not just title+description, and TaskOut returns
    them. A task is more than a title (#82)."""
    async with await _client() as c:
        token, ws_id = await _register(c, "taskdef@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        pid = (await _create(c, ws_id, h))["id"]
        await force_operating(pid)
        mid = await _online_agent(c, ws_id, h, "Doer-1")
        body = {
            "title": "Ship the calculator",
            "description": "Basic + - × ÷",
            "priority": "high",
            "due_date": "2026-08-01T00:00:00+00:00",
            "definition_of_done": "All operations pass and it is deployed",
            "assigned_marius_id": mid,
        }
        created = await c.post(f"/v1/projects/{pid}/tasks", headers=h, json=body)
        assert created.status_code == 201, created.text
        out = created.json()
        assert out["priority"] == "high"
        assert out["due_date"] is not None
        assert out["definition_of_done"] == "All operations pass and it is deployed"
        assert out["assigned_marius_id"] == mid

        # The definition survives the SQL round-trip (the new columns actually persist).
        got = (await c.get(f"/v1/tasks/{out['id']}", headers=h)).json()
        assert got["priority"] == "high"
        assert got["definition_of_done"] == "All operations pass and it is deployed"
        assert got["assigned_marius_id"] == mid


async def test_create_task_lands_in_supplied_status() -> None:
    """The board's per-column "+" passes `status` so a task lands in the right column, not
    always backlog. Omitting status still defaults to backlog (#82)."""
    async with await _client() as c:
        token, ws_id = await _register(c, "taskcol@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        pid = (await _create(c, ws_id, h))["id"]
        await force_operating(pid)

        in_progress = await c.post(
            f"/v1/projects/{pid}/tasks",
            headers=h,
            json={"title": "Already going", "status": "in_progress"},
        )
        assert in_progress.status_code == 201, in_progress.text
        assert in_progress.json()["status"] == "in_progress"

        defaulted = await c.post(
            f"/v1/projects/{pid}/tasks", headers=h, json={"title": "Just an idea"}
        )
        assert defaulted.status_code == 201, defaulted.text
        assert defaulted.json()["status"] == "backlog"

