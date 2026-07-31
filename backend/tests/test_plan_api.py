"""Project context + plan across both surfaces (spec 001 FR-007 → FR-014).

Drives the whole Story-1 loop over HTTP: a fully-seated project lands in *planning*, the
Leader submits a context and a plan, the patron decides, and only an approval opens the
door to real tasks. Both the patron surface (`/v1`) and the Leader surface (`/agent`) are
exercised, because the rule that matters most — the Leader cannot approve its own plan —
only holds if it is enforced on the agent side too.
"""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from armarius.main import app
from tests.support.agents import invite_and_online


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(c: AsyncClient, email: str) -> tuple[dict, str]:
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    assert r.status_code == 201, r.text
    h = {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}
    ws = await c.get("/v1/workspaces", headers=h)
    return h, ws.json()[0]["id"]


async def _project_in_planning(c: AsyncClient, email: str) -> tuple[dict, str, str, str]:
    """A project with every seat granted and every agent online → *planning*.

    Returns (patron headers, project_id, leader agent token, workspace_id).
    """
    h, ws_id = await _register(c, email)
    created = await c.post(
        f"/v1/workspaces/{ws_id}/projects",
        headers=h,
        json={
            "name": "Apollo",
            "description": "ship it",
            "objective": "Launch the platform",
            "leader": {"description": "Leads.", "marius_id": None},
            "roles": [{"title": "Backend", "seats": 1, "description": "Owns the API."}],
        },
    )
    assert created.status_code == 201, created.text
    pid = created.json()["id"]

    leader_id, leader_token = await invite_and_online(c, ws_id, h, name="Leader")
    dev_id, _ = await invite_and_online(c, ws_id, h, name="Dev")
    for marius_id, role_key in ((leader_id, "leader"), (dev_id, "backend")):
        g = await c.post(
            f"/v1/projects/{pid}/grant",
            headers=h,
            json={"role_key": role_key, "marius_id": marius_id},
        )
        assert g.status_code == 201, g.text

    detail = await c.get(f"/v1/projects/{pid}", headers=h)
    assert detail.json()["status"] == "planning", detail.text
    return h, pid, leader_token, ws_id


# ── the project stops at the gate, it does not sail past it ───────────────────────
async def test_full_roster_lands_in_planning_not_operating() -> None:
    async with await _client() as c:
        h, pid, _, _ = await _project_in_planning(c, "plan-a@armarius.dev")
        detail = await c.get(f"/v1/projects/{pid}", headers=h)
    assert detail.json()["status"] == "planning"


async def test_real_tasks_are_refused_before_the_plan_is_approved() -> None:
    async with await _client() as c:
        h, pid, _, _ = await _project_in_planning(c, "plan-b@armarius.dev")
        r = await c.post(
            f"/v1/projects/{pid}/tasks",
            headers=h,
            json={"title": "Dựng cổng đăng nhập"},
        )
    assert r.status_code == 409, r.text
    assert "kế hoạch" in r.json()["detail"].lower() or "plan" in r.json()["detail"].lower()


# ── the Leader submits, the patron decides ────────────────────────────────────────
async def test_leader_submits_context_then_plan() -> None:
    async with await _client() as c:
        h, pid, leader_token, _ = await _project_in_planning(c, "plan-c@armarius.dev")
        ah = {"Authorization": f"Bearer {leader_token}"}

        ctx = await c.post(
            f"/agent/projects/{pid}/context",
            headers=ah,
            json={
                "objective": "Ra mắt nền tảng trong quý này",
                "background": "Đội cũ để lại một bản dựng dở.",
                "constraints": "Không đổi cơ sở dữ liệu.",
                "scope": "Chỉ phần máy chủ.",
                "principles": "Đặc tả đi trước.",
            },
        )
        assert ctx.status_code == 200, ctx.text
        assert ctx.json()["approval_status"] == "submitted"
        assert ctx.json()["version"] == 1

        plan = await c.post(
            f"/agent/projects/{pid}/plan",
            headers=ah,
            json={
                "summary": "Ba hạng mục, hai tuần.",
                "risks": "Phụ thuộc bên thứ ba.",
                "items": [
                    {"title": "Cổng đăng nhập", "description": "OAuth", "order": 1},
                    {"title": "Bảng điều khiển", "description": "Trang chính", "order": 2},
                ],
            },
        )
        assert plan.status_code == 200, plan.text
        assert plan.json()["status"] == "submitted"
        assert len(plan.json()["items"]) == 2

        # The patron sees it, and it landed in their inbox rather than nagging them.
        seen = await c.get(f"/v1/projects/{pid}/plan", headers=h)
        assert seen.status_code == 200
        assert seen.json()["status"] == "submitted"
        inbox = await c.get("/v1/inbox", headers=h)
        kinds = {i["kind"] for i in inbox.json()}
    assert "plan_approval" in kinds


async def test_leader_cannot_decide_on_its_own_plan() -> None:
    async with await _client() as c:
        h, pid, leader_token, _ = await _project_in_planning(c, "plan-d@armarius.dev")
        ah = {"Authorization": f"Bearer {leader_token}"}
        await _submit_context_and_plan(c, pid, ah)

        # There is deliberately no decision route on the agent surface at all (FR-014).
        r = await c.post(
            f"/agent/projects/{pid}/plan/decision",
            headers=ah,
            json={"decision": "duyet"},
        )
    assert r.status_code in (404, 405), r.text


async def test_request_changes_keeps_planning_and_carries_the_note() -> None:
    async with await _client() as c:
        h, pid, leader_token, _ = await _project_in_planning(c, "plan-e@armarius.dev")
        await _submit_context_and_plan(c, pid, {"Authorization": f"Bearer {leader_token}"})

        r = await c.post(
            f"/v1/projects/{pid}/plan/decision",
            headers=h,
            json={"decision": "yeu_cau_chinh", "note": "Chia nhỏ hạng mục 2 ra."},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "changes_requested"
        assert "Chia nhỏ" in r.json()["patron_note"]

        detail = await c.get(f"/v1/projects/{pid}", headers=h)
    assert detail.json()["status"] == "planning"


async def test_approval_opens_the_door_to_real_tasks() -> None:
    async with await _client() as c:
        h, pid, leader_token, _ = await _project_in_planning(c, "plan-f@armarius.dev")
        await _submit_context_and_plan(c, pid, {"Authorization": f"Bearer {leader_token}"})

        approved = await c.post(
            f"/v1/projects/{pid}/plan/decision", headers=h, json={"decision": "duyet"}
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"

        detail = await c.get(f"/v1/projects/{pid}", headers=h)
        assert detail.json()["status"] == "operating"

        task = await c.post(
            f"/v1/projects/{pid}/tasks", headers=h, json={"title": "Dựng cổng đăng nhập"}
        )
        assert task.status_code == 201, task.text

        # The waiting inbox item closed itself — the patron does not tidy up by hand.
        inbox = await c.get("/v1/inbox", headers=h)
    assert [i for i in inbox.json() if i["kind"] == "plan_approval"] == []


async def test_changes_must_come_with_a_reason() -> None:
    async with await _client() as c:
        h, pid, leader_token, _ = await _project_in_planning(c, "plan-g@armarius.dev")
        await _submit_context_and_plan(c, pid, {"Authorization": f"Bearer {leader_token}"})
        r = await c.post(
            f"/v1/projects/{pid}/plan/decision", headers=h, json={"decision": "yeu_cau_chinh"}
        )
    assert r.status_code in (409, 422), r.text


# ── phase changes: the Leader proposes, the patron decides (FR-004) ───────────────
async def test_leader_proposes_a_phase_change_and_the_patron_decides() -> None:
    async with await _client() as c:
        h, pid, leader_token, _ = await _project_in_planning(c, "plan-h@armarius.dev")
        ah = {"Authorization": f"Bearer {leader_token}"}
        await _submit_context_and_plan(c, pid, ah)
        await c.post(
            f"/v1/projects/{pid}/plan/decision", headers=h, json={"decision": "duyet"}
        )

        proposal = await c.post(
            f"/agent/projects/{pid}/phase-proposal",
            headers=ah,
            json={"target_phase": "maintaining", "reason": "Đã ra mắt xong."},
        )
        assert proposal.status_code == 200, proposal.text

        # The proposal alone changes nothing — it parks in the patron's inbox.
        detail = await c.get(f"/v1/projects/{pid}", headers=h)
        assert detail.json()["status"] == "operating"
        inbox = await c.get("/v1/inbox", headers=h)
        assert {i["kind"] for i in inbox.json()} == {"phase_decision"}

        moved = await c.post(
            f"/v1/projects/{pid}/phase",
            headers=h,
            json={"target_phase": "maintaining", "reason": "Đồng ý."},
        )
        assert moved.status_code == 200, moved.text
    assert moved.json()["status"] == "maintaining"


async def test_illegal_phase_change_is_refused() -> None:
    async with await _client() as c:
        h, pid, _, _ = await _project_in_planning(c, "plan-i@armarius.dev")
        r = await c.post(
            f"/v1/projects/{pid}/phase",
            headers=h,
            json={"target_phase": "closed", "reason": "Thôi không làm nữa."},
        )
    assert r.status_code == 409, r.text


async def test_a_closed_project_is_read_only() -> None:
    async with await _client() as c:
        h, pid, leader_token, _ = await _project_in_planning(c, "plan-j@armarius.dev")
        await _submit_context_and_plan(c, pid, {"Authorization": f"Bearer {leader_token}"})
        await c.post(f"/v1/projects/{pid}/plan/decision", headers=h, json={"decision": "duyet"})
        closed = await c.post(
            f"/v1/projects/{pid}/phase",
            headers=h,
            json={"target_phase": "closed", "reason": "Xong việc."},
        )
        assert closed.status_code == 200, closed.text

        # History stays readable…
        readable = await c.get(f"/v1/projects/{pid}", headers=h)
        assert readable.status_code == 200
        assert readable.json()["status"] == "closed"

        # …but every write is refused (FR-005).
        task = await c.post(
            f"/v1/projects/{pid}/tasks", headers=h, json={"title": "Việc mới"}
        )
        assert task.status_code == 409, task.text
        again = await c.post(
            f"/v1/projects/{pid}/phase",
            headers=h,
            json={"target_phase": "operating", "reason": "Mở lại."},
        )
    assert again.status_code == 409, again.text


# ── cross-workspace reads stay invisible (Constitution I) ─────────────────────────
async def test_another_patron_cannot_read_the_plan() -> None:
    async with await _client() as c:
        _, pid, leader_token, _ = await _project_in_planning(c, "plan-k@armarius.dev")
        await _submit_context_and_plan(c, pid, {"Authorization": f"Bearer {leader_token}"})
        other, _ = await _register(c, "plan-outsider@armarius.dev")
        r = await c.get(f"/v1/projects/{pid}/plan", headers=other)
    assert r.status_code == 404, r.text


async def _submit_context_and_plan(c: AsyncClient, pid: str, ah: dict) -> None:
    ctx = await c.post(
        f"/agent/projects/{pid}/context",
        headers=ah,
        json={"objective": "Ra mắt nền tảng", "background": "", "constraints": ""},
    )
    assert ctx.status_code == 200, ctx.text
    plan = await c.post(
        f"/agent/projects/{pid}/plan",
        headers=ah,
        json={
            "summary": "Hai hạng mục.",
            "items": [{"title": "Cổng đăng nhập", "description": "OAuth", "order": 1}],
        },
    )
    assert plan.status_code == 200, plan.text


async def test_the_phase_route_cannot_skip_the_plan_gate() -> None:
    """FR-011: leaving *planning* is what approving a plan does. If the phase route also
    did it, the gate would be decorative — a patron could move to operating without ever
    reading what the Leader proposed."""
    async with await _client() as c:
        h, pid, _, _ = await _project_in_planning(c, "plan-skip@armarius.dev")
        r = await c.post(
            f"/v1/projects/{pid}/phase",
            headers=h,
            json={"target_phase": "operating", "reason": "Bỏ qua cổng duyệt."},
        )
        assert r.status_code == 409, r.text
        detail = await c.get(f"/v1/projects/{pid}", headers=h)
    assert detail.json()["status"] == "planning"
