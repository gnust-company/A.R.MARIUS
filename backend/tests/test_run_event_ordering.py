"""Sự kiện của một lượt chạy: thứ tự xác định, và không trùng (T107, FR-045).

Số do **máy** đặt, ngay lúc nó sinh ra sự kiện — không có vòng hỏi-đáp nào cho từng sự kiện, nên
thứ tự phải mang được trong chính con số. Hai hệ quả, và cả hai đều là chỗ dễ sai:

**Đồng hồ không phải thứ tự.** Cả một lô nhận cùng một mốc thời gian, và một lô bị giữ lại lúc
đường tắc sẽ tới **sau** những lô sinh sau nó. Xếp theo lúc ghi là xếp theo lịch giao hàng của
mạng, và một nhật ký như thế không phải nhật ký của chuyện đã xảy ra.

**Một con số đã viết là đã viết.** Đó là thứ làm cho gửi lại một lô là vô hại — cùng những con số
ấy, ghi đúng một lần (FR-045). Nó cũng có nghĩa là con số ấy không bao giờ đổi nghĩa: thứ hai
mang cùng số không đè lên thứ nhất, vì người đọc đã có thể đã đọc thứ nhất rồi.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import RunEventModel
from armarius.main import app
from tests.support.agents import invite_agent
from tests.support.machines import auth, link_machine
from tests.support.work import a_project, a_task, shelve

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _a_run_in_hand(c: AsyncClient, email: str) -> tuple[object, dict]:
    machine = await link_machine(c, email, hostname="box")
    agent = await invite_agent(
        c,
        machine.workspace_id,
        machine.headers,
        name=f"Marin{uuid4().hex[:6]}",
        workplace_id=machine.workplace_id,
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


async def _say(c: AsyncClient, machine, run, events: list[dict]) -> None:
    sent = await c.post(
        f"/daemon/runs/{run['run_id']}/events",
        json={"events": events},
        headers=auth(machine.token),
    )
    assert sent.status_code == 200, sent.text


def _line(seq: int, text: str) -> dict:
    return {"seq": seq, "type": "assistant.message", "payload": {"text": text}}


async def test_the_log_reads_in_the_runs_own_order_not_the_order_batches_arrived() -> None:
    """Lô sau tới trước. Bản ghi vẫn kể theo thứ tự đã xảy ra.

    Không phải chuyện giả tưởng: T141 cho một lô bị từ chối tạm thời nằm lại buffer trong khi
    những lô sinh sau nó vẫn đi, nên *tới sau khi những số lớn hơn đã tới* là đường bình thường,
    không phải đường hỏng.
    """
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"order-{uuid4().hex[:8]}@example.com")
        first = run["first_seq"]

        await _say(c, machine, run, [_line(first + 2, "ba"), _line(first + 3, "bốn")])
        await _say(c, machine, run, [_line(first, "một"), _line(first + 1, "hai")])

        listed = await c.get(f"/v1/runs/{run['run_id']}/events", headers=machine.headers)
        assert listed.status_code == 200, listed.text
        said = [e for e in listed.json() if e["type"] == "assistant.message"]

        assert [e["seq"] for e in said] == [first, first + 1, first + 2, first + 3]
        assert [e["payload"]["text"] for e in said] == ["một", "hai", "ba", "bốn"]


async def test_one_batch_shares_a_timestamp_so_the_clock_cannot_be_the_order() -> None:
    """Vì sao bài trên phải xếp theo `seq`: bên trong một lô, đồng hồ không phân biệt được gì cả."""
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"clock-{uuid4().hex[:8]}@example.com")
        first = run["first_seq"]

        await _say(
            c, machine, run,
            [_line(first, "một"), _line(first + 1, "hai"), _line(first + 2, "ba")],
        )

        async with get_sessionmaker()() as session:
            stamps = (
                await session.execute(
                    select(RunEventModel.created_at)
                    .where(
                        RunEventModel.run_id == UUID(run["run_id"]),
                        RunEventModel.seq >= first,
                    )
                    .order_by(RunEventModel.seq)
                )
            ).scalars().all()

        assert len(stamps) == 3
        assert len(set(stamps)) == 1, "một lô là một khoảnh khắc — đồng hồ không xếp được nó"


async def test_a_number_already_written_is_never_written_over() -> None:
    """Thứ hai mang cùng số không đè lên thứ nhất: người đọc có thể đã đọc thứ nhất rồi."""
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"dup-{uuid4().hex[:8]}@example.com")
        seq = run["first_seq"]

        await _say(c, machine, run, [_line(seq, "bản gốc")])
        await _say(c, machine, run, [_line(seq, "bản viết đè")])

        async with get_sessionmaker()() as session:
            rows = (
                await session.execute(
                    select(RunEventModel.payload).where(
                        RunEventModel.run_id == UUID(run["run_id"]),
                        RunEventModel.seq == seq,
                    )
                )
            ).scalars().all()

        assert len(rows) == 1, "một số, một hàng"
        assert rows[0]["text"] == "bản gốc"


async def test_a_number_taken_does_not_stop_the_rest_of_the_batch() -> None:
    """Gửi lại chồng lấn là chuyện thường: lô cũ ghi rồi, câu trả lời mất, máy gửi thêm đuôi."""
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"overlap-{uuid4().hex[:8]}@example.com")
        first = run["first_seq"]

        await _say(c, machine, run, [_line(first, "một"), _line(first + 1, "hai")])
        await _say(
            c, machine, run,
            [_line(first + 1, "hai"), _line(first + 2, "ba"), _line(first + 3, "bốn")],
        )

        listed = await c.get(f"/v1/runs/{run['run_id']}/events", headers=machine.headers)
        said = [e for e in listed.json() if e["type"] == "assistant.message"]
        assert [e["seq"] for e in said] == [first, first + 1, first + 2, first + 3]


async def test_walking_a_long_run_by_number_never_skips_a_line_or_repeats_one() -> None:
    """Đường người đọc thật đi (T100): xin từng trang theo `after_seq` cho tới khi hết.

    Đi theo **số của lượt chạy** chứ không theo vị trí trong danh sách: một lô về muộn rơi vào
    giữa sẽ đẩy mọi thứ sau nó xuống một chỗ, và một con trỏ đếm theo vị trí sẽ nhảy qua đúng
    một dòng ở mỗi lần như thế.
    """
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"walk-{uuid4().hex[:8]}@example.com")
        first = run["first_seq"]
        total = 25
        await _say(c, machine, run, [_line(first + i, f"dòng {i}") for i in range(total)])

        seen: list[int] = []
        after = 0
        while True:
            page = await c.get(
                f"/v1/runs/{run['run_id']}/events",
                params={"after_seq": after, "limit": 7},
                headers=machine.headers,
            )
            assert page.status_code == 200, page.text
            got = page.json()
            if not got:
                break
            seen.extend(e["seq"] for e in got)
            after = got[-1]["seq"]

        expected = list(range(1, first + total))
        assert seen == expected, "đi từng trang phải ra đúng dãy số, không thiếu không lặp"
        assert len(set(seen)) == len(seen)
