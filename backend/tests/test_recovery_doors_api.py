"""Hai cửa Mức 2, qua HTTP thật (FR-059, FR-060b).

Cả hai cửa được canh ở tầng dịch vụ và độ phủ ở đó là đủ cho *luật*. Cái chỉ tồn tại một
lần có bộ định tuyến là **chốt người gọi**: ghế Trưởng dự án, và phép quy lỗi 409. Không có
bài kiểm nào đi qua đường mạng thì một lần dọn bộ định tuyến gỡ mất dòng kiểm ghế sẽ không
làm đỏ bài nào — mà chính cái dòng đó ngăn một con thợ tự đẩy đầu việc kẹt của nó thẳng lên
người chủ, tức đi vòng qua cả hai nấc dưới.

Spec mô tả hai cửa là **một cửa sổ hai lối**, nên chúng được kiểm cạnh nhau ở đây: một cửa
lệch khỏi cửa kia là cái lỗ đúng bằng hình phép kiểm còn thiếu.
"""

from __future__ import annotations

import pytest

from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.database.engine import init_db
from armarius.main import app
from armarius.presentation.container import build_container
from tests.support.planning import client, operating_project


@pytest.fixture(autouse=True)
async def _bootstrap():
    await init_db()
    container = build_container()
    container.registry.register(EchoAdapter(step_delay=0.0))
    app.state.container = container
    yield


async def _a_live_task(c, p) -> str:
    task = await c.post(
        f"/v1/projects/{p.project_id}/tasks",
        headers=p.headers,
        json={"title": "Việc sẽ kẹt", "plan_item_id": p.item_id()},
    )
    assert task.status_code == 201, task.text
    task_id = task.json()["id"]
    moved = await c.post(
        f"/v1/tasks/{task_id}/status", headers=p.headers, json={"status": "todo"}
    )
    assert moved.status_code == 200, moved.text
    return task_id


async def test_a_worker_cannot_use_either_leader_door() -> None:
    """Không giữ ghế thì cả hai cửa trả *không tìm thấy*, không phải *không có quyền*.

    Hai lẽ. Một là Hiến pháp I: câu trả lời không được để lộ rằng đầu việc đó có tồn tại.
    Hai là chính cái thang: một con thợ đẩy được đầu việc của mình lên người chủ là đi vòng
    qua cả Mức 1 lẫn Mức 2 trong một lời gọi.
    """
    async with client() as c:
        p = await operating_project(c, "doors-a@armarius.dev")
        task_id = await _a_live_task(c, p)

        decided = await c.post(
            f"/agent/tasks/{task_id}/recovery",
            headers=p.worker_headers,
            json={"action": "giao lại cho Bob"},
        )
        gave_up = await c.post(
            f"/agent/tasks/{task_id}/escalate",
            headers=p.worker_headers,
            json={"reason": "ngoài tầm của tôi"},
        )

    assert decided.status_code == 404, decided.text
    assert gave_up.status_code == 404, gave_up.text


async def test_neither_door_opens_while_the_system_is_still_trying() -> None:
    """Giữ ghế nhưng đầu việc chưa tới Mức 2 — cả hai cửa trả 409.

    Đầu việc này còn chưa hề đình trệ, nên chưa ai hỏi Trưởng dự án điều gì. Ghi một quyết
    định ở đây là khai một lần bàn giao chưa xảy ra, và hồ sơ gửi người chủ được dựng từ
    đúng những bản ghi ấy.
    """
    async with client() as c:
        p = await operating_project(c, "doors-b@armarius.dev")
        task_id = await _a_live_task(c, p)

        decided = await c.post(
            f"/agent/tasks/{task_id}/recovery",
            headers=p.leader_headers,
            json={"action": "giao lại cho Bob"},
        )
        gave_up = await c.post(
            f"/agent/tasks/{task_id}/escalate",
            headers=p.leader_headers,
            json={"reason": "ngoài tầm của tôi"},
        )

    assert decided.status_code == 409, decided.text
    assert gave_up.status_code == 409, gave_up.text
