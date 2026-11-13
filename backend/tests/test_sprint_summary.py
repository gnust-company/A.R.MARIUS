"""Khép một đợt việc (spec 001 FR-042, FR-043).

Hai điều phải đúng cùng lúc, và chúng dễ bị lẫn:

  - **Không** có cổng nghiệm thu ở cấp dự án (FR-042). Công việc đã được công nhận từng
    đầu việc; bắt người chủ duyệt lại lần nữa ở cấp dự án là bắt họ ký cho thứ họ vừa ký.
  - Nhưng khi đợt việc khép lại thì vẫn phải có người **quyết đi tiếp thế nào** (FR-043):
    đóng dự án, chuyển bảo trì, hay mở đợt mới. Đó là quyết định, không phải nghiệm thu.

Nên cái rơi vào hộp thư người chủ mang ba lựa chọn, và Trưởng dự án là người soạn bản tổng
kết — hệ thống không tự viết thay.
"""

from __future__ import annotations

from tests.support.app_db import wakeups_for_project
from tests.support.approvals import task_awaiting_acceptance
from tests.support.planning import client, operating_project


async def _close(c, p, task_id: str) -> None:
    leader = await c.post(
        f"/agent/tasks/{task_id}/approval",
        headers=p.leader_headers,
        json={"approve": True},
    )
    assert leader.status_code == 200, leader.text
    patron = await c.post(
        f"/v1/tasks/{task_id}/approval", headers=p.headers, json={"approve": True}
    )
    assert patron.status_code == 200, patron.text
    assert patron.json()["status"] == "done", patron.text


async def test_closing_the_last_task_does_not_raise_a_project_acceptance_gate() -> None:
    """FR-042: xong hết việc thì **không** có mục nghiệm thu cấp dự án nào bật lên."""
    async with client() as c:
        p = await operating_project(c, "sprint-a@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p)
        await _close(c, p, task_id)

        inbox = (await c.get("/v1/inbox", headers=p.headers)).json()
        detail = await c.get(f"/v1/projects/{p.project_id}", headers=p.headers)

    assert [i for i in inbox if i["kind"] == "output_acceptance"] == []
    # Dự án vẫn ở *vận hành*: hệ thống không tự chuyển giai đoạn thay người chủ.
    assert detail.json()["status"] == "operating"


async def test_the_leader_writes_the_wrap_up_and_the_patron_gets_three_choices() -> None:
    async with client() as c:
        p = await operating_project(c, "sprint-b@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p)
        await _close(c, p, task_id)

        sent = await c.post(
            f"/agent/projects/{p.project_id}/sprint-summary",
            headers=p.leader_headers,
            json={"summary": "Đợt này khép với một đầu việc: báo cáo tháng đã kết xuất."},
        )
        assert sent.status_code == 200, sent.text
        assert set(sent.json()["choices"]) == {"dong_du_an", "chuyen_bao_tri", "mo_dot_moi"}

        inbox = (await c.get("/v1/inbox", headers=p.headers)).json()

    decisions = [i for i in inbox if i["kind"] == "phase_decision"]
    assert len(decisions) == 1, inbox
    assert "báo cáo tháng" in (decisions[0]["body"] or "")
    assert decisions[0]["attempt_dossier"]["choices"] == [
        "dong_du_an",
        "chuyen_bao_tri",
        "mo_dot_moi",
    ]


async def test_a_worker_cannot_send_the_wrap_up() -> None:
    """Bản tổng kết là việc của Trưởng dự án — thợ gửi thay là báo cáo vượt cấp (FR-071)."""
    async with client() as c:
        p = await operating_project(c, "sprint-c@armarius.dev")
        r = await c.post(
            f"/agent/projects/{p.project_id}/sprint-summary",
            headers=p.worker_headers,
            json={"summary": "Tôi tự tổng kết."},
        )
    assert r.status_code in (401, 403, 404), r.text


# ── the patron's answer reaches the Leader (FR-043a, FR-047) ──────────────────────
#
# Measured 2026-11-13: the patron chose *another batch*, the letter left the inbox, and
# nothing else happened. The Leader is the only one who can turn that answer into tasks,
# and it was never told.


async def _wrapped_up(c, p) -> None:
    task_id = await task_awaiting_acceptance(c, p)
    await _close(c, p, task_id)
    sent = await c.post(
        f"/agent/projects/{p.project_id}/sprint-summary",
        headers=p.leader_headers,
        json={"summary": "Đợt này khép với một đầu việc."},
    )
    assert sent.status_code == 200, sent.text


async def _pending_decisions(c, p) -> list[dict]:
    inbox = (await c.get("/v1/inbox", headers=p.headers)).json()
    return [i for i in inbox if i["kind"] == "phase_decision"]


async def test_choosing_another_batch_closes_the_letter_and_wakes_the_leader() -> None:
    async with client() as c:
        p = await operating_project(c, "sprint-next@armarius.dev")
        await _wrapped_up(c, p)
        assert len(await _pending_decisions(c, p)) == 1

        answered = await c.post(
            f"/v1/projects/{p.project_id}/next-batch",
            headers=p.headers,
            json={"note": "Thêm trang xuất PDF cho báo cáo tháng."},
        )
        assert answered.status_code == 200, answered.text
        assert answered.json() == {"answered": True}

        waiting = await _pending_decisions(c, p)
        told = [
            w
            for w in await wakeups_for_project(p.project_id)
            if "new_batch_opened" in w["codes"]
        ]
        detail = await c.get(f"/v1/projects/{p.project_id}", headers=p.headers)

    assert waiting == [], "the letter is still asking a question the patron answered"
    assert len(told) == 1, told
    assert told[0]["marius_id"] == p.leader_id
    assert told[0]["source"] == "patron_decision"
    # In the patron's own words: a person's text is handed on as typed (FR-012).
    assert "Thêm trang xuất PDF cho báo cáo tháng." in (told[0]["prompt"] or "")
    # No phase moved: another batch is more work in the phase the project is already in.
    assert detail.json()["status"] == "operating"


async def test_answering_twice_calls_the_leader_once() -> None:
    async with client() as c:
        p = await operating_project(c, "sprint-twice@armarius.dev")
        await _wrapped_up(c, p)

        first = await c.post(
            f"/v1/projects/{p.project_id}/next-batch", headers=p.headers, json={}
        )
        again = await c.post(
            f"/v1/projects/{p.project_id}/next-batch", headers=p.headers, json={}
        )
        told = [
            w
            for w in await wakeups_for_project(p.project_id)
            if "new_batch_opened" in w["codes"]
        ]

    assert first.json() == {"answered": True}
    assert again.status_code == 200 and again.json() == {"answered": False}
    assert len(told) == 1, "one answer, two calls to the Leader"
    # With no note the Leader is told to ask, rather than left to guess what goes in it.
    assert "Ask them in this chat" in (told[0]["prompt"] or "")


async def test_a_phase_proposal_is_not_answered_by_opening_a_batch() -> None:
    """Same kind of letter, different question: closing it would record an answer to
    something the patron was never asked."""
    async with client() as c:
        p = await operating_project(c, "sprint-other@armarius.dev")
        proposed = await c.post(
            f"/agent/projects/{p.project_id}/phase-proposal",
            headers=p.leader_headers,
            json={"target_phase": "maintaining", "reason": "Hết việc lớn."},
        )
        assert proposed.status_code == 200, proposed.text

        answered = await c.post(
            f"/v1/projects/{p.project_id}/next-batch", headers=p.headers, json={}
        )
        waiting = await _pending_decisions(c, p)

    assert answered.json() == {"answered": False}
    assert len(waiting) == 1, "the Leader's proposal was closed by an answer to another letter"


async def test_moving_to_maintenance_tells_the_leader() -> None:
    async with client() as c:
        p = await operating_project(c, "sprint-maint@armarius.dev")
        await _wrapped_up(c, p)

        moved = await c.post(
            f"/v1/projects/{p.project_id}/phase",
            headers=p.headers,
            json={"target_phase": "maintaining", "reason": "Chỉ còn sửa lỗi."},
        )
        assert moved.status_code == 200, moved.text
        told = [
            w
            for w in await wakeups_for_project(p.project_id)
            if "phase_changed" in w["codes"]
        ]
        waiting = await _pending_decisions(c, p)

    assert len(told) == 1, told
    assert told[0]["marius_id"] == p.leader_id
    assert "maintaining" in (told[0]["reason"] or "")
    assert "Chỉ còn sửa lỗi." in (told[0]["prompt"] or "")
    assert waiting == []
