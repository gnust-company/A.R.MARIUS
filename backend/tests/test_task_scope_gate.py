"""Cổng duyệt theo khuôn kế hoạch (spec 001 FR-027, nối FR-075).

Sau khi người chủ duyệt kế hoạch, Trưởng dự án được **tự do trong khuôn**: đầu việc gắn
với một hạng mục đã duyệt thì tạo và giao ngay, không hỏi lại. Đầu việc **không** gắn hạng
mục nào là một lần nới phạm vi — nó ở lại *nháp* và một mục chờ duyệt rơi vào hộp thư người
chủ.

Đây là thứ thay chỗ công tắc "làm tới luôn" cũ: không còn một cờ bật/tắt toàn dự án quyết
định Trưởng dự án được tự tiện tới đâu, mà là chính bản kế hoạch người chủ đã đọc và gật.
"""

from __future__ import annotations

from tests.support.planning import client, operating_project


async def test_a_task_inside_an_approved_item_is_created_and_assigned_at_once() -> None:
    async with client() as c:
        p = await operating_project(c, "scope-a@armarius.dev")
        r = await c.post(
            f"/agent/projects/{p.project_id}/tasks",
            headers=p.leader_headers,
            json={
                "title": "Dựng màn hình đăng nhập",
                "description": "Làm biểu mẫu đăng nhập và nối vào lối xác thực sẵn có.",
                "assignee_marius_id": p.worker_id,
                "plan_item_id": p.item_id(0),
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["status"] == "todo"
        assert body["assigned_marius_id"] == p.worker_id
        assert body["plan_item_id"] == p.item_id(0)

        # Không phiền tới người chủ: trong khuôn thì không có gì phải hỏi.
        inbox = await c.get("/v1/inbox", headers=p.headers)
    assert [i for i in inbox.json() if i["kind"] == "major_change_approval"] == []


async def test_a_task_outside_the_plan_stays_a_draft_and_asks_the_patron() -> None:
    async with client() as c:
        p = await operating_project(c, "scope-b@armarius.dev")
        r = await c.post(
            f"/agent/projects/{p.project_id}/tasks",
            headers=p.leader_headers,
            json={
                "title": "Viết lại toàn bộ phần thanh toán",
                "description": "Đổi sang cổng thanh toán khác.",
                "assignee_marius_id": p.worker_id,
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["status"] == "draft"
        assert r.json()["plan_item_id"] is None

        inbox = await c.get("/v1/inbox", headers=p.headers)
        waiting = [i for i in inbox.json() if i["kind"] == "major_change_approval"]
    assert len(waiting) == 1
    assert "thanh toán" in waiting[0]["title"].lower()


async def test_pointing_at_an_item_of_a_plan_that_is_not_approved_does_not_count() -> None:
    """Một mã hạng mục bịa ra không mở được cổng — nếu không thì cổng chỉ là hình thức."""
    async with client() as c:
        p = await operating_project(c, "scope-c@armarius.dev")
        r = await c.post(
            f"/agent/projects/{p.project_id}/tasks",
            headers=p.leader_headers,
            json={
                "title": "Việc lạ",
                "description": "Trỏ vào một hạng mục không thuộc kế hoạch đã duyệt.",
                "assignee_marius_id": p.worker_id,
                "plan_item_id": "00000000-0000-0000-0000-000000000001",
            },
        )
        assert r.status_code == 201, r.text
    assert r.json()["status"] == "draft"


async def test_the_patron_can_approve_an_out_of_scope_draft_by_hand() -> None:
    async with client() as c:
        p = await operating_project(c, "scope-d@armarius.dev")
        created = await c.post(
            f"/agent/projects/{p.project_id}/tasks",
            headers=p.leader_headers,
            json={
                "title": "Thêm phần xuất báo cáo",
                "description": "Kết xuất số liệu ra tệp bảng tính cho kế toán.",
                "assignee_marius_id": p.worker_id,
            },
        )
        task_id = created.json()["id"]

        approved = await c.post(
            f"/v1/tasks/{task_id}/approve", headers=p.headers
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "todo"

        # Mục chờ tự đóng — người chủ không phải dọn tay.
        inbox = await c.get("/v1/inbox", headers=p.headers)
    assert [i for i in inbox.json() if i["kind"] == "major_change_approval"] == []


async def test_an_out_of_scope_draft_without_a_description_is_refused_at_approval() -> None:
    """Cổng mô tả và cổng duyệt chồng lên nhau: qua cổng này không miễn cổng kia."""
    async with client() as c:
        p = await operating_project(c, "scope-e@armarius.dev")
        created = await c.post(
            f"/agent/projects/{p.project_id}/tasks",
            headers=p.leader_headers,
            json={"title": "Việc thiếu mô tả", "assignee_marius_id": p.worker_id},
        )
        task_id = created.json()["id"]
        r = await c.post(
            f"/v1/tasks/{task_id}/approve", headers=p.headers
        )
    assert r.status_code == 409, r.text
