"""Cửa sự kiện từ chối bằng **mã mà máy đọc ra là câu trả lời cuối** (T141, FR-047).

Từ phía daemon, một lô bị giữ lại là một lô **chặn mọi sự kiện phía sau nó**: buffer là hàng
đợi vào-trước-ra-trước, nên một sự kiện server không bao giờ nhận sẽ ngồi ở đầu hàng và kéo cả
bản ghi của lượt chạy xuống theo. Vì thế daemon chia mã lỗi làm hai loại: *chưa phải lúc* thì
giữ lô và gửi lại, *đã đọc và không nhận* thì bỏ hẳn rồi tự thú.

Phép chia ấy chỉ đúng nếu server thật sự trả về mã thuộc loại thứ hai cho những cú từ chối nó
thật sự làm. Đây là bài kiểm giữ lấy chỗ nối ấy — chạy trên chính ứng dụng thật, không phải trên
một bản giả của nó. Danh sách ngoại lệ nằm ở `refusedForGood` trong
`daemon/internal/client/runs.go`, và bảng đối chiếu nằm ở `contracts/daemon-api.md` §4.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.main import app
from tests.support.agents import invite_agent
from tests.support.machines import auth, link_machine
from tests.support.work import a_project, a_task, shelve

pytestmark = pytest.mark.anyio

# Mã mà daemon hiểu là *chưa phải lúc* và sẽ hỏi lại mãi. Một cú từ chối vĩnh viễn rơi vào đây
# là một lượt chạy mất sạch bản ghi mà không ai biết vì sao.
KEEPS_ASKING = {401, 403, 404, 408, 425, 429}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _a_run_in_hand(c: AsyncClient, email: str) -> tuple[object, dict]:
    machine = await link_machine(c, email, hostname="box")
    agent = await invite_agent(
        c, machine.workspace_id, machine.headers, name="Marin", workplace_id=machine.workplace_id
    )
    project_id = await a_project(machine.workspace_id)
    task_id = await a_task(project_id, assigned_to=agent["id"])
    await shelve(marius_id=agent["id"], task_id=task_id)

    answered = await c.post(
        "/daemon/runs/claim",
        json={"workplace_ids": [machine.workplace_id], "max": 1},
        headers=auth(machine.token),
    )
    assert answered.status_code == 200, answered.text
    return machine, answered.json()["runs"][0]


def _a_batch(first_seq: int, poison: dict) -> dict:
    """Một lô bình thường có đúng một sự kiện hỏng ở giữa."""
    return {
        "events": [
            {"seq": first_seq, "type": "assistant.message", "payload": {"text": "trước"}},
            {"seq": first_seq + 1, **poison},
            {"seq": first_seq + 2, "type": "assistant.message", "payload": {"text": "sau"}},
        ]
    }


@pytest.mark.parametrize(
    ("why", "poison"),
    [
        (
            "toàn văn kết quả công cụ dưới một cái tên bị cấm",
            {"type": "tool.completed", "payload": {"call": "t1", "stdout": "x" * 64}},
        ),
        (
            "kết quả công cụ vượt ngưỡng kích thước",
            {"type": "tool.completed", "payload": {"call": "t1", "opening": "x" * 8192}},
        ),
        (
            "một lý do thiếu mà server này không biết",
            {
                "type": "tool.completed",
                "payload": {"call": "t1"},
                "omission_reason": "because_i_felt_like_it",
            },
        ),
    ],
)
async def test_every_refusal_this_door_makes_tells_the_machine_to_stop_asking(why, poison):
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"refuse-{uuid4().hex[:8]}@example.com")

        refused = await c.post(
            f"/daemon/runs/{run['run_id']}/events",
            json=_a_batch(run["first_seq"], poison),
            headers=auth(machine.token),
        )

        assert refused.status_code >= 400, f"{why}: cửa đã nhận, đáng lẽ phải từ chối"
        assert refused.status_code < 500, (
            f"{why}: 5xx nghĩa là server chưa đọc tới nơi, nên máy sẽ gửi lại mãi "
            f"(được {refused.status_code})"
        )
        assert refused.status_code not in KEEPS_ASKING, (
            f"{why}: mã {refused.status_code} là mã daemon hiểu thành *chưa phải lúc*, nên nó "
            "sẽ hỏi lại mỗi 250ms và mọi sự kiện sau đó chết theo (T141)"
        )
