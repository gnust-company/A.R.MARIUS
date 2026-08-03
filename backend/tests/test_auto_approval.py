"""Công tắc tự động công nhận (spec 001 FR-036 → FR-039).

Công tắc là cách người chủ nói "phần này khỏi hỏi tôi" — không phải cách hệ thống tự cho
mình quyền. Ba điều nó **không** được làm:

  - không bật sẵn (FR-038): im lặng ký thay người chủ ngay từ đầu là hỏng cả cơ chế;
  - không cho Trưởng dự án đụng vào (FR-038): agent tự bật công tắc miễn ký cho chính
    mình thì hai chữ ký chỉ còn một;
  - không với tới ba quyết định cấp dự án (FR-037): duyệt kế hoạch, duyệt thay đổi lớn,
    chuyển giai đoạn vẫn phải có người chủ ra tay thật.

Và một điều nó **phải** làm: bật rồi thì vẫn ghi vết đủ — ai được coi là đã ký, cho đầu
việc nào, lúc nào (FR-039). Tự động là bớt thao tác, không phải bớt sổ sách.
"""

from __future__ import annotations

from tests.support.approvals import task_awaiting_acceptance
from tests.support.planning import client, operating_project


async def test_the_switch_is_off_until_the_patron_turns_it_on() -> None:
    async with client() as c:
        p = await operating_project(c, "auto-a@armarius.dev")
        r = await c.get(f"/v1/projects/{p.project_id}/auto-approval", headers=p.headers)
        assert r.status_code == 200, r.text
    assert r.json()["enabled"] is False


async def test_only_the_patron_flips_their_own_switch() -> None:
    async with client() as c:
        p = await operating_project(c, "auto-b@armarius.dev")
        on = await c.put(
            f"/v1/projects/{p.project_id}/auto-approval",
            headers=p.headers,
            json={"enabled": True},
        )
        assert on.status_code == 200, on.text
        assert on.json()["enabled"] is True

        # Trưởng dự án không có lối nào chạm tới công tắc — token agent bị chặn ở cửa.
        sneak = await c.put(
            f"/v1/projects/{p.project_id}/auto-approval",
            headers=p.leader_headers,
            json={"enabled": False},
        )
        assert sneak.status_code in (401, 403), sneak.text

        still = await c.get(f"/v1/projects/{p.project_id}/auto-approval", headers=p.headers)
    assert still.json()["enabled"] is True


async def test_with_the_switch_off_the_leader_signature_leaves_the_task_open() -> None:
    async with client() as c:
        p = await operating_project(c, "auto-c@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p)

        signed = await c.post(
            f"/agent/tasks/{task_id}/approval",
            headers=p.leader_headers,
            json={"approve": True},
        )
        assert signed.status_code == 200, signed.text

        task = await c.get(f"/v1/tasks/{task_id}", headers=p.headers)
        assert task.json()["status"] == "in_review", task.text

        inbox = await c.get("/v1/inbox", headers=p.headers)
    waiting = [i for i in inbox.json() if i["kind"] == "output_acceptance"]
    assert len(waiting) == 1, inbox.text
    assert str(waiting[0]["task_id"]) == str(task_id)


async def test_with_the_switch_on_the_task_closes_but_the_trail_still_names_the_patron() -> None:
    async with client() as c:
        p = await operating_project(c, "auto-d@armarius.dev")
        on = await c.put(
            f"/v1/projects/{p.project_id}/auto-approval",
            headers=p.headers,
            json={"enabled": True},
        )
        assert on.status_code == 200, on.text
        task_id = await task_awaiting_acceptance(c, p)

        signed = await c.post(
            f"/agent/tasks/{task_id}/approval",
            headers=p.leader_headers,
            json={"approve": True},
        )
        assert signed.status_code == 200, signed.text

        task = await c.get(f"/v1/tasks/{task_id}", headers=p.headers)
        assert task.json()["status"] == "done", task.text

        inbox = await c.get("/v1/inbox", headers=p.headers)
        assert [i for i in inbox.json() if i["kind"] == "output_acceptance"] == []

        # FR-039: bớt thao tác, không bớt sổ sách.
        entries = (await c.get(f"/v1/tasks/{task_id}/log", headers=p.headers)).json()

    approvals = [e for e in entries if e["kind"] == "approval_signed"]
    auto = [e for e in approvals if e["detail"].get("is_auto") is True]
    assert len(auto) == 1, entries
    assert auto[0]["detail"]["signer_kind"] == "patron"
    assert auto[0]["created_at"]


async def test_the_switch_does_not_decide_a_phase_change() -> None:
    """FR-037: công tắc bật rồi, chuyển giai đoạn vẫn phải có người chủ."""
    async with client() as c:
        p = await operating_project(c, "auto-e@armarius.dev")
        await c.put(
            f"/v1/projects/{p.project_id}/auto-approval",
            headers=p.headers,
            json={"enabled": True},
        )
        proposed = await c.post(
            f"/agent/projects/{p.project_id}/phase-proposal",
            headers=p.leader_headers,
            json={"target_phase": "maintaining", "reason": "Đợt việc đã xong."},
        )
        assert proposed.status_code == 200, proposed.text

        detail = await c.get(f"/v1/projects/{p.project_id}", headers=p.headers)
        assert detail.json()["status"] == "operating", "công tắc không được tự chuyển giai đoạn"

        inbox = await c.get("/v1/inbox", headers=p.headers)
    assert [i for i in inbox.json() if i["kind"] == "phase_decision"], inbox.text


async def test_the_switch_does_not_decide_a_scope_widening() -> None:
    """FR-037: thay đổi lớn (đầu việc ngoài khuôn kế hoạch) vẫn phải hỏi người chủ."""
    async with client() as c:
        p = await operating_project(c, "auto-f@armarius.dev")
        await c.put(
            f"/v1/projects/{p.project_id}/auto-approval",
            headers=p.headers,
            json={"enabled": True},
        )
        r = await c.post(
            f"/agent/projects/{p.project_id}/tasks",
            headers=p.leader_headers,
            json={
                "title": "Viết lại toàn bộ phần thanh toán",
                "description": "Đổi sang cổng thanh toán khác.",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["status"] == "draft", "ngoài khuôn thì vẫn phải ở lại nháp"

        inbox = await c.get("/v1/inbox", headers=p.headers)
    assert [i for i in inbox.json() if i["kind"] == "major_change_approval"], inbox.text
