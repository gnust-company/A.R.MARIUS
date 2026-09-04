"""Lối sửa đầu việc qua đường truyền (spec 001 FR-070a, FR-081, T187).

Ở đây kiểm đúng thứ chỉ đường truyền mới trả lời được: một trường **không có trong yêu
cầu** khác một trường **gửi lên rỗng**. Ở tầng nghiệp vụ hai thứ đó là hai giá trị khác
nhau; qua JSON thì chúng dễ trở thành một, và lúc ấy cái hạn chót đặt nhầm gỡ ra không
được nữa.
"""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from armarius.main import app
from tests.support.projects import force_operating


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(c: AsyncClient, email: str) -> tuple[dict, str]:
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    token = r.json()["tokens"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    ws = await c.get("/v1/workspaces", headers=headers)
    return headers, ws.json()[0]["id"]


async def _project(c: AsyncClient, ws_id: str, h: dict) -> str:
    proj = await c.post(
        f"/v1/workspaces/{ws_id}/projects",
        headers=h,
        json={
            "name": "Apollo",
            "key": "APO",
            "leader": {"description": "Leads.", "marius_id": None},
        },
    )
    pid = proj.json()["id"]
    await force_operating(pid)
    return pid


async def _task(c: AsyncClient, pid: str, h: dict) -> str:
    r = await c.post(
        f"/v1/projects/{pid}/tasks",
        headers=h,
        json={
            "title": "Xuất báo cáo tháng",
            "description": "Gom số liệu bán hàng rồi kết xuất.",
            "priority": "low",
            "due_date": "2026-09-01T12:00:00Z",
        },
    )
    return r.json()["id"]


async def test_the_patron_can_rewrite_a_task_over_http() -> None:
    async with await _client() as c:
        h, ws = await _register(c, "edit1@example.com")
        pid = await _project(c, ws, h)
        tid = await _task(c, pid, h)

        r = await c.patch(
            f"/v1/tasks/{tid}",
            headers=h,
            json={"title": "Xuất báo cáo quý", "priority": "high"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["title"] == "Xuất báo cáo quý"
        assert body["priority"] == "high"
        # Không gửi lên ⇒ không đụng.
        assert body["description"] == "Gom số liệu bán hàng rồi kết xuất."
        assert body["due_date"] is not None


async def test_a_deadline_sent_as_empty_is_wiped_not_ignored() -> None:
    """Chỗ dễ hỏng nhất của một lối sửa từng phần.

    Nếu "không gửi" và "gửi rỗng" gộp làm một thì cái hạn chót gõ nhầm gỡ ra không được,
    mà gỡ nó ra chính là lý do FR-070a tồn tại.
    """
    async with await _client() as c:
        h, ws = await _register(c, "edit2@example.com")
        pid = await _project(c, ws, h)
        tid = await _task(c, pid, h)

        r = await c.patch(f"/v1/tasks/{tid}", headers=h, json={"due_date": None})
        assert r.status_code == 200, r.text
        assert r.json()["due_date"] is None
        assert r.json()["title"] == "Xuất báo cáo tháng"


async def test_an_empty_body_changes_nothing_and_is_not_an_error() -> None:
    async with await _client() as c:
        h, ws = await _register(c, "edit3@example.com")
        pid = await _project(c, ws, h)
        tid = await _task(c, pid, h)

        r = await c.patch(f"/v1/tasks/{tid}", headers=h, json={})
        assert r.status_code == 200, r.text
        assert r.json()["title"] == "Xuất báo cáo tháng"


async def test_a_task_cannot_be_left_nameless() -> None:
    async with await _client() as c:
        h, ws = await _register(c, "edit4@example.com")
        pid = await _project(c, ws, h)
        tid = await _task(c, pid, h)

        blank = await c.patch(f"/v1/tasks/{tid}", headers=h, json={"title": "   "})
        assert blank.status_code == 422, blank.text
        empty = await c.patch(f"/v1/tasks/{tid}", headers=h, json={"title": None})
        assert empty.status_code == 422, empty.text

        after = await c.get(f"/v1/tasks/{tid}", headers=h)
        assert after.json()["title"] == "Xuất báo cáo tháng"


async def test_someone_elses_task_reads_as_not_found() -> None:
    """FR-081 — không được dùng câu lỗi để dò xem đầu việc kia có tồn tại hay không."""
    async with await _client() as c:
        mine, ws = await _register(c, "edit5@example.com")
        pid = await _project(c, ws, mine)
        tid = await _task(c, pid, mine)
        stranger, _ = await _register(c, "edit6@example.com")

        r = await c.patch(
            f"/v1/tasks/{tid}", headers=stranger, json={"title": "Tên của người lạ"}
        )
        assert r.status_code == 404, r.text

        after = await c.get(f"/v1/tasks/{tid}", headers=mine)
        assert after.json()["title"] == "Xuất báo cáo tháng"
