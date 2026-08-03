"""Vòng từ chối công nhận (spec 001 FR-040, FR-041).

Từ chối **không** phải huỷ việc và cũng không phải trả về nháp: việc đã làm được một
quãng, phản hồi là để sửa tiếp. Nên đầu việc quay về *đang làm*, việc kế tiếp ghi rõ phải
sửa gì, và **đúng người thợ cũ** được gọi lại — không phải người rảnh nhất, không phải
Trưởng dự án.

Và một cái phanh: sau ba vòng từ chối trên cùng một đầu việc, lỗi nhiều khả năng nằm ở
**đề bài** chứ không ở thợ. Hệ thống kéo Trưởng dự án vào soát lại đề bài và bộ tiêu chí,
thay vì để vòng sửa–nộp lặp vô tận.
"""

from __future__ import annotations

from tests.support.app_db import wakeups_for_task
from tests.support.approvals import task_awaiting_acceptance
from tests.support.planning import client, operating_project


async def _leader_signs(c, p, task_id: str) -> None:
    r = await c.post(
        f"/agent/tasks/{task_id}/approval",
        headers=p.leader_headers,
        json={"approve": True},
    )
    assert r.status_code == 200, r.text


async def _patron_rejects(c, p, task_id: str, reason: str) -> None:
    r = await c.post(
        f"/v1/tasks/{task_id}/approval",
        headers=p.headers,
        json={"approve": False, "reason": reason},
    )
    assert r.status_code == 200, r.text


async def _back_to_review(c, p, task_id: str) -> None:
    """Thợ sửa xong và nộp lại."""
    r = await c.post(
        f"/v1/tasks/{task_id}/status", headers=p.headers, json={"status": "in_review"}
    )
    assert r.status_code == 200, r.text


async def test_a_rejection_sends_the_task_back_to_in_progress_not_to_draft() -> None:
    async with client() as c:
        p = await operating_project(c, "reject-a@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p)
        await _leader_signs(c, p, task_id)
        await _patron_rejects(c, p, task_id, "Số liệu tháng 6 còn thiếu.")

        task = (await c.get(f"/v1/tasks/{task_id}", headers=p.headers)).json()

    assert task["status"] == "in_progress", task
    assert task["completed_at"] is None
    assert "sửa theo phản hồi" in (task["next_action"] or "").lower()
    assert "tháng 6" in (task["status_reason"] or "")


async def test_a_rejection_wakes_the_worker_who_did_the_work() -> None:
    """Gọi nhầm người là phản hồi rơi vào khoảng không."""
    async with client() as c:
        p = await operating_project(c, "reject-b@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p)
        await _leader_signs(c, p, task_id)
        await _patron_rejects(c, p, task_id, "Thiếu phần đối chiếu sổ cái.")

        wakes = await wakeups_for_task(task_id)
    rows = [w for w in wakes if w["source"] == "approval_rejected"]
    assert len(rows) == 1, wakes
    assert rows[0]["marius_id"] == str(p.worker_id)


async def test_the_rejection_reason_is_required() -> None:
    """Từ chối mà không nói vì sao thì thợ không có gì để sửa (FR-030 cùng tinh thần)."""
    async with client() as c:
        p = await operating_project(c, "reject-c@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p)
        await _leader_signs(c, p, task_id)
        r = await c.post(
            f"/v1/tasks/{task_id}/approval",
            headers=p.headers,
            json={"approve": False, "reason": "   "},
        )
    assert r.status_code in (409, 422), r.text


async def test_signing_again_after_a_rejection_starts_a_fresh_round() -> None:
    """Chữ ký của vòng cũ không được tính sang vòng mới.

    Nếu chữ ký Trưởng dự án ở vòng một còn sống sang vòng hai, thì lần nộp lại chỉ cần
    người chủ gật là đóng — thành phẩm sửa xong không ai chấm lại. Đó là *xong giả*.
    """
    async with client() as c:
        p = await operating_project(c, "reject-d@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p)
        await _leader_signs(c, p, task_id)
        await _patron_rejects(c, p, task_id, "Chưa đạt tiêu chí thứ hai.")
        await _back_to_review(c, p, task_id)

        # Người chủ gật ngay, chưa có chữ ký Trưởng dự án của vòng mới.
        r = await c.post(
            f"/v1/tasks/{task_id}/approval",
            headers=p.headers,
            json={"approve": True},
        )
        assert r.status_code == 200, r.text
        task = (await c.get(f"/v1/tasks/{task_id}", headers=p.headers)).json()
    assert task["status"] == "in_review", "chưa có chữ ký vòng mới của Trưởng dự án"


async def test_three_rounds_pull_the_leader_back_to_the_brief() -> None:
    async with client() as c:
        p = await operating_project(c, "reject-e@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p)
        for i, reason in enumerate(
            ("Thiếu đối chiếu.", "Sai kỳ báo cáo.", "Vẫn chưa khớp sổ cái.")
        ):
            if i:
                await _back_to_review(c, p, task_id)
            await _leader_signs(c, p, task_id)
            await _patron_rejects(c, p, task_id, reason)

        wakes = await wakeups_for_task(task_id)
        entries = (await c.get(f"/v1/tasks/{task_id}/log", headers=p.headers)).json()

    review_brief = [w for w in wakes if w["source"] == "brief_review"]
    assert len(review_brief) == 1, wakes
    assert review_brief[0]["marius_id"] == str(p.leader_id)
    assert [e for e in entries if e["kind"] == "escalated"], entries


async def test_two_rounds_do_not_pull_the_leader_in_yet() -> None:
    """Cái phanh phải bấm đúng vòng thứ ba, không sớm hơn."""
    async with client() as c:
        p = await operating_project(c, "reject-f@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p)
        for i, reason in enumerate(("Thiếu đối chiếu.", "Sai kỳ báo cáo.")):
            if i:
                await _back_to_review(c, p, task_id)
            await _leader_signs(c, p, task_id)
            await _patron_rejects(c, p, task_id, reason)

        wakes = await wakeups_for_task(task_id)
    assert [w for w in wakes if w["source"] == "brief_review"] == []
