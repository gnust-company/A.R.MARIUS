"""Bản ghi nói ra **vì sao nó ngắn**, chứ không để lại một khoảng trống (T095, T096).

Ba sự thật khác hẳn nhau trông y hệt nhau khi chỉ nhìn phần thân sự kiện: *công cụ trả về đúng
chừng này*, *ta cắt bớt cho khỏi rời máy*, và *CLI này không cho xem*. Một màn hình không phân
biệt được ba thứ ấy sẽ vẽ cùng một thứ cho cả ba, và người đọc rút ra kết luận sai ở hai trong
ba lần (FR-043b, FR-047).

Nên chúng không nằm trong phần thân. Chúng là **cột riêng**: một người đọc hỏi *cho tôi xem chỗ
nào bị cắt* mà không phải mở từng payload, và một màn hình vẽ được *chỗ này thiếu, và thiếu vì
lý do này* mà không phải đoán theo hình dạng payload — vốn khác nhau theo từng loại sự kiện.

Chỉ **máy** nói được mấy điều này. Nó cắt, và nó che. Từ phía server, một bản rút gọn đã cắt
đúng trông hệt một kết quả ngắn chưa từng cần cắt — nên đây là thứ phải đi qua dây, không phải
thứ suy ra được ở đầu này.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from armarius.infrastructure.daemon.claim import ReportedEvent, _about_the_record
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


async def _rows(run_id: str) -> list[RunEventModel]:
    async with get_sessionmaker()() as session:
        found = await session.execute(
            select(RunEventModel)
            .where(RunEventModel.run_id == UUID(run_id))
            .order_by(RunEventModel.seq)
        )
        return list(found.scalars())


async def test_the_machine_can_say_a_result_was_cut_and_how_big_it_really_was():
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"cut-{uuid4().hex[:8]}@example.com")
        seq = run["first_seq"]

        sent = await c.post(
            f"/daemon/runs/{run['run_id']}/events",
            json={
                "events": [
                    {
                        "seq": seq,
                        "type": "tool.completed",
                        "payload": {"call": "t1", "failed": False, "opening": "line one"},
                        "truncated": True,
                        "original_byte_size": 41230,
                        "omission_reason": "truncated_by_policy",
                    }
                ]
            },
            headers=auth(machine.token),
        )
        assert sent.status_code == 200, sent.text

        row = next(r for r in await _rows(run["run_id"]) if r.seq == seq)
        assert row.truncated is True
        assert row.original_byte_size == 41230, (
            "cắt rồi mà không giữ lại kích thước thật — người đọc tưởng đó là toàn bộ kết quả"
        )
        assert row.omission_reason == "truncated_by_policy"


async def test_a_cli_that_reveals_nothing_is_stored_as_a_different_fact_from_a_cut():
    """Hai lý do, hai giá trị. Cái thứ nhất sửa được bằng một ngưỡng, cái thứ hai thì không."""
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"silent-{uuid4().hex[:8]}@example.com")
        seq = run["first_seq"]

        sent = await c.post(
            f"/daemon/runs/{run['run_id']}/events",
            json={
                "events": [
                    {
                        "seq": seq,
                        "type": "tool.completed",
                        "payload": {"call": "t1", "failed": False},
                        "omission_reason": "not_exposed_by_cli",
                    }
                ]
            },
            headers=auth(machine.token),
        )
        assert sent.status_code == 200, sent.text

        row = next(r for r in await _rows(run["run_id"]) if r.seq == seq)
        assert row.omission_reason == "not_exposed_by_cli"
        assert row.truncated is False, "không có gì để cắt mà bị ghi là đã cắt"
        assert row.original_byte_size is None, "dựng ra một kích thước không ai đo"


async def test_a_reason_this_server_does_not_know_is_refused_at_the_door():
    """Một chuỗi tự do ở cột này là một màn hình phải đoán, và đoán sai thì im lặng."""
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"bogus-{uuid4().hex[:8]}@example.com")

        refused = await c.post(
            f"/daemon/runs/{run['run_id']}/events",
            json={
                "events": [
                    {
                        "seq": run["first_seq"],
                        "type": "tool.completed",
                        "payload": {"call": "t1"},
                        "omission_reason": "because_i_felt_like_it",
                    }
                ]
            },
            headers=auth(machine.token),
        )
        assert refused.status_code == 422, refused.text


async def test_masking_on_the_machine_is_written_down_where_the_reader_can_see_it():
    """Che là chuyện xảy ra **trên máy người dùng**, nên server chỉ biết nếu máy nói ra.

    Và người đọc cần biết: một dòng có `[redacted]` mà không có dấu nào là một dòng người ta
    tưởng agent tự gõ như thế.
    """
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"mask-{uuid4().hex[:8]}@example.com")
        seq = run["first_seq"]

        sent = await c.post(
            f"/daemon/runs/{run['run_id']}/events",
            json={
                "events": [
                    {
                        "seq": seq,
                        "type": "assistant.message",
                        "payload": {"text": "I used [redacted] to call back"},
                        "redacted": True,
                    }
                ]
            },
            headers=auth(machine.token),
        )
        assert sent.status_code == 200, sent.text

        row = next(r for r in await _rows(run["run_id"]) if r.seq == seq)
        assert row.redacted is True


async def test_an_ordinary_event_is_stored_as_what_it_is_untouched():
    """Bốn cột ấy là **lời khẳng định**, không phải mặc định.

    Một daemon bản cũ không gửi gì cả, và sự kiện của nó phải nằm lại đúng như nó vốn thế —
    không cắt, không che, không thiếu.
    """
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"plain-{uuid4().hex[:8]}@example.com")
        seq = run["first_seq"]

        sent = await c.post(
            f"/daemon/runs/{run['run_id']}/events",
            json={"events": [{"seq": seq, "type": "assistant.message", "payload": {"text": "ok"}}]},
            headers=auth(machine.token),
        )
        assert sent.status_code == 200, sent.text

        row = next(r for r in await _rows(run["run_id"]) if r.seq == seq)
        assert (row.truncated, row.original_byte_size, row.omission_reason, row.redacted) == (
            False,
            None,
            None,
            False,
        )


async def test_the_reader_gets_the_reason_back_not_just_the_short_payload():
    """Ghi vào mà không đọc ra được thì cột ấy chỉ là chỗ tốn dung lượng."""
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"read-{uuid4().hex[:8]}@example.com")
        seq = run["first_seq"]

        await c.post(
            f"/daemon/runs/{run['run_id']}/events",
            json={
                "events": [
                    {
                        "seq": seq,
                        "type": "tool.completed",
                        "payload": {"call": "t1", "failed": False, "opening": "line one"},
                        "truncated": True,
                        "original_byte_size": 41230,
                        "omission_reason": "truncated_by_policy",
                        "redacted": True,
                    }
                ]
            },
            headers=auth(machine.token),
        )

        shown = await c.get(f"/v1/runs/{run['run_id']}/events", headers=machine.headers)
        assert shown.status_code == 200, shown.text
        event = next(e for e in shown.json() if e["seq"] == seq)
        assert event["truncated"] is True
        assert event["original_byte_size"] == 41230
        assert event["omission_reason"] == "truncated_by_policy"
        assert event["redacted"] is True


def test_a_live_viewer_is_told_the_same_thing_as_a_late_one():
    """Cùng một lượt chạy đọc từ hai chỗ — dòng trực tiếp lúc đang chạy, bản ghi lúc xong.

    Nói được *vì sao thiếu* ở một chỗ và im ở chỗ kia là vẽ cùng một lượt chạy thành hai câu
    chuyện, tuỳ người xem mở lên lúc nào (FR-046).
    """
    cut = ReportedEvent(
        seq=1,
        type="tool.completed",
        payload={"call": "t1"},
        truncated=True,
        original_byte_size=41230,
        omission_reason="truncated_by_policy",
        redacted=True,
    )
    assert _about_the_record(cut) == {
        "_truncated": True,
        "_original_byte_size": 41230,
        "_omission_reason": "truncated_by_policy",
        "_redacted": True,
    }

    plain = ReportedEvent(seq=2, type="assistant.message", payload={"text": "ok"})
    assert _about_the_record(plain) == {}, (
        "sự kiện thường bị phình ra để mang theo bốn lời phủ định"
    )
