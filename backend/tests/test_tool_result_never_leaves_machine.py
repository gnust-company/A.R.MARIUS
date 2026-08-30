"""Toàn văn kết quả công cụ **không có chỗ nào để nằm** ở phía server (T105, FR-043a).

T098 đã dựng một cánh cửa: một sự kiện `tool.completed` mang toàn văn bị từ chối cả lô. Bài kiểm
này lo cái còn lại, và nó là một câu khác hẳn — *nếu một sự kiện như thế lọt qua cửa thì nó có
đường nào vào kho phụ không*. Cửa kiểm theo tên trường và theo kích thước cả gói; cả hai đều là
phép đoán về hình dạng, và phép đoán nào cũng có mép. Cái ở đây không có mép: `tool.completed`
không nằm trong danh sách loại được phép tách, nên phép tách **không có khoá nào để đọc** và
không sinh ra hàng nào.

Vì sao đáng viết riêng: ngưỡng của cửa (4096) **lớn hơn** ngưỡng tách (2048), và khoảng giữa hai
con số ấy là chỗ duy nhất lỗi này sống được — một kết quả 3KB đi qua cửa, rồi nếu danh sách loại
lỡ có thêm `tool.completed` thì 3KB ấy được ghi vào `run_event_blobs` và nằm lại trên server mãi.
Không ai thấy gì cả: cửa vẫn 200, màn hình vẫn vẽ đúng, chỉ có bytes ở lại chỗ chúng bị cấm ở lại.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from armarius.infrastructure.daemon import event_blobs
from armarius.infrastructure.daemon.claim import TOOL_RESULT_EVENT
from armarius.infrastructure.daemon.models import RunEventBlobModel
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import RunEventModel
from armarius.main import app
from armarius.shared.config import settings
from tests.support.agents import invite_agent
from tests.support.machines import auth, link_machine
from tests.support.work import a_project, a_task, shelve

pytestmark = pytest.mark.anyio


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


async def _blobs_of(run_id: str) -> list[tuple[str, RunEventBlobModel]]:
    """Mỗi hàng toàn văn của lượt chạy này, kèm loại sự kiện nó treo vào."""
    async with get_sessionmaker()() as session:
        found = await session.execute(
            select(RunEventModel.type, RunEventBlobModel)
            .join(RunEventBlobModel, RunEventBlobModel.run_event_id == RunEventModel.id)
            .where(RunEventModel.run_id == UUID(run_id))
        )
        return [(kind, blob) for kind, blob in found.all()]


def test_a_tool_result_is_not_one_of_the_kinds_kept_in_two_pieces() -> None:
    """Danh sách loại được phép tách là **một luật**, và luật ấy là đúng một dòng mã.

    Kiểm thẳng vào dòng ấy vì thêm `tool.completed` vào đây là một sửa đổi trông vô hại — nó đọc
    ra *cho kết quả dài cũng mở xem được đi* — mà hậu quả là toàn văn kết quả nằm lại server, thứ
    FR-043a cấm bằng một câu không có ngoại lệ.
    """
    assert TOOL_RESULT_EVENT not in event_blobs.FULL_TEXT_FIELDS, (
        "kết quả công cụ không được phép có toàn văn ở phía server (FR-043a); "
        f"danh sách hiện có: {sorted(event_blobs.FULL_TEXT_FIELDS)}"
    )


def test_asking_to_split_a_tool_result_finds_nothing_to_split() -> None:
    """Không phải *từ chối*, mà là **không có gì để làm**: không khoá nào để đọc toàn văn ra."""
    huge = "x" * (settings.run_event_inline_bytes * 4)
    split = event_blobs.split(
        TOOL_RESULT_EVENT,
        {"call": "t1", "failed": False, "opening": huge},
        settings.run_event_inline_bytes,
    )
    assert split.whole is None
    assert split.was_cut is False
    assert split.payload["opening"] == huge, "phép tách không được chạm vào một loại nó không quản"


async def test_a_tool_result_bigger_than_the_split_threshold_leaves_no_second_half() -> None:
    """3KB: qua được cửa (ngưỡng 4096) và vượt ngưỡng tách (2048) — đúng khoảng lỗi sống được."""
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"blob-{uuid4().hex[:8]}@example.com")
        opening = "y" * 3000
        assert settings.run_event_inline_bytes < 3000 < 4096

        sent = await c.post(
            f"/daemon/runs/{run['run_id']}/events",
            json={
                "events": [
                    {
                        "seq": run["first_seq"],
                        "type": TOOL_RESULT_EVENT,
                        "payload": {"call": "t1", "failed": False, "opening": opening},
                        "truncated": True,
                        "original_byte_size": 900_000,
                    }
                ]
            },
            headers=auth(machine.token),
        )
        assert sent.status_code == 200, sent.text

        assert await _blobs_of(run["run_id"]) == []

        async with get_sessionmaker()() as session:
            row = (
                await session.execute(
                    select(RunEventModel).where(
                        RunEventModel.run_id == UUID(run["run_id"]),
                        RunEventModel.seq == run["first_seq"],
                    )
                )
            ).scalar_one()
        # Server không cắt lại thứ máy đã cắt: bản rút gọn đi vào nguyên vẹn, và con số 900_000
        # vẫn là con số máy đo được, không phải kích thước của bản rút gọn.
        assert row.payload["opening"] == opening
        assert row.original_byte_size == 900_000


async def test_no_row_in_the_side_store_belongs_to_a_tool_result() -> None:
    """Một lô trộn: thứ được phép tách thì tách, kết quả công cụ thì không, trong cùng một lần ghi.

    Trộn có chủ ý — lỗi đáng sợ không phải *tách nhầm mọi thứ* mà là *tách đúng ba loại kia rồi
    tiện tay tách nốt cái thứ tư*, và chỉ có một lô trộn mới phân biệt được hai chuyện đó.
    """
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"mixed-{uuid4().hex[:8]}@example.com")
        seq = run["first_seq"]
        long_enough = "z" * (settings.run_event_inline_bytes * 2)

        sent = await c.post(
            f"/daemon/runs/{run['run_id']}/events",
            json={
                "events": [
                    {
                        "seq": seq,
                        "type": "tool.started",
                        "payload": {"call": "t1", "name": "read", "args": {"path": long_enough}},
                    },
                    {
                        "seq": seq + 1,
                        "type": "assistant.message",
                        "payload": {"text": long_enough},
                    },
                    {
                        "seq": seq + 2,
                        "type": TOOL_RESULT_EVENT,
                        "payload": {"call": "t1", "failed": False, "opening": "y" * 3000},
                        "truncated": True,
                        "original_byte_size": 900_000,
                    },
                ]
            },
            headers=auth(machine.token),
        )
        assert sent.status_code == 200, sent.text

        kept = await _blobs_of(run["run_id"])
        kinds = sorted(kind for kind, _ in kept)
        assert kinds == ["assistant.message", "tool.started"], kinds
        for kind, _ in kept:
            assert kind != TOOL_RESULT_EVENT
            assert kind in event_blobs.FULL_TEXT_FIELDS
