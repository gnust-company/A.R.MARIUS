"""Hình dạng của cái chờ phải đi tới được màn hình (T055, FR-008b).

`blocked_by_task` gộp hai cái chờ khác hẳn nhau. Chờ một đầu việc khác thì đi giục bên kia.
Chờ máy rảnh thì **để yên** — không có gì hỏng, và thứ đang chiếm chỗ đã có đồng hồ riêng
của nó (FR-008e). Người đọc bảng làm hai việc khác nhau cho hai cái chờ ấy, nên bảng phải
nói được đây là cái nào.

Luật đã phân biệt được từ đặc tả 001; chỗ đứt nằm ở đường đi ra: đầu việc chỉ mang **loại**
động cơ, còn hình dạng thì tính xong rồi bỏ. Tệp này giữ đúng một điều — nó đi hết đường ra
tới câu trả lời của máy chủ, chỗ màn hình đọc.

Và giữ luôn điều kèm theo: cái đi ra là **mã**, không phải câu. Cùng một sự thật được đưa
cho người chủ bằng tiếng của họ và đưa cho agent bằng tiếng Anh (Hiến pháp — Điều VII).
"""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.domain.entities.task import TaskDrive, TaskStatus
from armarius.domain.services.push_reason_rules import (
    BLOCKED_ON_CAPACITY,
    BLOCKED_ON_TASK,
)
from armarius.main import app
from tests.support.projects import force_operating

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(c: AsyncClient, email: str) -> tuple[dict, str]:
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    h = {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}
    ws = await c.get("/v1/workspaces", headers=h)
    return h, ws.json()[0]["id"]


async def _project(c: AsyncClient, ws_id: str, h: dict) -> str:
    made = await c.post(
        f"/v1/workspaces/{ws_id}/projects",
        headers=h,
        json={
            "name": "Apollo",
            "key": "APO",
            "leader": {"description": "Leads.", "marius_id": None},
        },
    )
    pid = made.json()["id"]
    await force_operating(pid)
    return pid


async def _park(task_id: str, *, code: str | None) -> None:
    """Put one task into drive #5 with a given shape, straight on the row.

    Written here rather than staged through a real queue jam because this file is about the
    road out, not about how the shape is decided — that is settled against real rows in
    `test_taken_work_has_a_drive.py`.
    """
    async with app.state.container.uow_factory() as uow:
        task = await uow.tasks.get(UUID(task_id))
        assert task is not None
        task.status = TaskStatus.TODO
        task.drive = TaskDrive.BLOCKED_BY_TASK
        task.drive_expires_at = None
        task.drive_code = code
        await uow.tasks.update(task)
        await uow.commit()


async def test_a_task_waiting_for_a_free_machine_says_so_on_the_way_out() -> None:
    async with _client() as c:
        h, ws_id = await _register(c, "wait-screen@armarius.dev")
        pid = await _project(c, ws_id, h)
        made = await c.post(
            f"/v1/projects/{pid}/tasks", headers=h, json={"title": "Kết xuất báo cáo"}
        )
        task_id = made.json()["id"]
        await _park(task_id, code=BLOCKED_ON_CAPACITY)

        seen = await c.get(f"/v1/tasks/{task_id}", headers=h)

    assert seen.status_code == 200, seen.text
    body = seen.json()
    assert body["drive"] == "blocked_by_task"
    assert body["drive_code"] == BLOCKED_ON_CAPACITY, (
        "màn hình không có cách nào biết đây là chờ máy rảnh chứ không phải chờ việc khác"
    )


async def test_the_other_wait_comes_out_as_a_different_shape() -> None:
    """Đối chứng: hai cái chờ không được ra cùng một chữ."""
    async with _client() as c:
        h, ws_id = await _register(c, "wait-screen-other@armarius.dev")
        pid = await _project(c, ws_id, h)
        made = await c.post(
            f"/v1/projects/{pid}/tasks", headers=h, json={"title": "Kết xuất báo cáo"}
        )
        task_id = made.json()["id"]
        await _park(task_id, code=BLOCKED_ON_TASK)

        seen = await c.get(f"/v1/tasks/{task_id}", headers=h)

    assert seen.json()["drive_code"] == BLOCKED_ON_TASK


async def test_what_travels_is_a_code_and_never_a_sentence() -> None:
    """Câu chữ để màn hình tự dựng. Máy chủ chỉ đưa mã (Điều VII).

    Một câu lưu sẵn chỉ nói được một thứ tiếng, mà cùng sự thật này còn phải đưa cho agent
    bằng tiếng Anh.
    """
    async with _client() as c:
        h, ws_id = await _register(c, "wait-screen-code@armarius.dev")
        pid = await _project(c, ws_id, h)
        made = await c.post(
            f"/v1/projects/{pid}/tasks", headers=h, json={"title": "Kết xuất báo cáo"}
        )
        task_id = made.json()["id"]
        await _park(task_id, code=BLOCKED_ON_CAPACITY)

        body = (await c.get(f"/v1/tasks/{task_id}", headers=h)).json()

    assert body["drive_code"] == "blocked_on_capacity"
    assert " " not in body["drive_code"], body["drive_code"]


async def test_a_task_in_no_wait_at_all_carries_no_shape() -> None:
    """Không có cái chờ nào thì không được để lại nhãn cũ.

    Động cơ số 5 không có đồng hồ, nên không có gì tự đến dọn một cái nhãn nằm lại.
    """
    async with _client() as c:
        h, ws_id = await _register(c, "wait-screen-none@armarius.dev")
        pid = await _project(c, ws_id, h)
        made = await c.post(
            f"/v1/projects/{pid}/tasks", headers=h, json={"title": "Kết xuất báo cáo"}
        )
        body = (await c.get(f"/v1/tasks/{made.json()['id']}", headers=h)).json()

    assert body["drive_code"] is None, body["drive_code"]
