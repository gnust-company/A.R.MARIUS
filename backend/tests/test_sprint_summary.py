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
