"""Sự kiện dài nằm ở hai chỗ, và chỗ thứ hai chỉ đi ra khi có người hỏi (T099, T100, FR-049).

Phép đọc quyết định thiết kế này là phép đọc mở một lượt chạy ra: màn hình xin **mọi** sự kiện
của nó. Một nghìn sự kiện mà mỗi cái vác theo một megabyte prompt là truy vấn không ai phục vụ
nổi, và màn hình sẽ kéo cả đống ấy về chỉ để vẽ danh sách tóm tắt một dòng (SC-014).

Nên có một trạng thái **thứ tư**, và nó phải phân biệt được với ba cái đã có (FR-047):

- `truncated_by_policy` — máy đã cắt, phần còn lại nằm nguyên trên máy người dùng, mất hẳn.
- `not_exposed_by_cli` — CLI không bao giờ lộ ra.
- cắt ở đây — phần còn lại **có ở ngay đây**, xin một câu là ra.

Cái thứ tư không phải một sự thiếu, nên nó **không** mang lý do thiếu. Nếu nó mang, người đọc sẽ
tưởng phần còn lại đã mất, và không đi hỏi thứ vốn đang nằm sẵn đó.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.domain.entities.run import RunEvent
from armarius.infrastructure.daemon.event_blobs import FULL_TEXT_FIELDS, split
from armarius.main import app
from armarius.presentation.api.trace import about_the_record
from armarius.presentation.schemas import RunEventOut
from armarius.shared.config import settings
from tests.support.agents import invite_agent
from tests.support.machines import auth, link_machine
from tests.support.work import a_project, a_task, shelve

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _a_run_in_hand(c: AsyncClient, email: str, *, instructions: str = "") -> tuple:
    machine = await link_machine(c, email, hostname="box")
    agent = await invite_agent(
        c,
        machine.workspace_id,
        machine.headers,
        name=f"Marin{uuid4().hex[:6]}",
        workplace_id=machine.workplace_id,
        instructions=instructions,
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


# ── cái gì được tách, cái gì không ───────────────────────────────────────────


def test_a_tool_result_has_no_second_half_here_at_all():
    """Không phải vì nó nhỏ. Toàn văn kết quả công cụ **không rời khỏi máy** (FR-043a).

    Nên ở đây không có ngưỡng nào cho nó cả: không có gì để lưu. Đặt nó vào danh sách được tách
    là lặng lẽ dựng ra một đường cho thứ đáng lẽ chưa từng tới nơi này.
    """
    assert "tool.completed" not in FULL_TEXT_FIELDS
    huge = {"call": "t1", "opening": "x" * 9000, "bytes": 9000}
    assert split("tool.completed", huge, 2048).whole is None


def test_something_that_already_fits_is_left_exactly_as_it_is():
    payload = {"text": "ngắn"}
    got = split("assistant.message", payload, 2048)
    assert got.whole is None
    assert got.payload is payload, "không có gì để tách thì không được sao chép vô cớ"


def test_a_cut_falls_on_a_character_not_in_the_middle_of_one():
    """Ngưỡng đếm bytes vì dây đếm bytes; người đọc thì đọc ký tự."""
    text = "đ" * 100  # hai bytes mỗi ký tự
    got = split("assistant.message", {"text": text}, 51)
    assert got.whole == text
    assert got.payload["text"] == "đ" * 25, "chỗ cắt phải lùi về ranh giới ký tự"


def test_tool_arguments_keep_their_shape_when_they_are_cut():
    """Cắt riêng giá trị làm nó lớn, chứ không đổi cả object thành một chuỗi cắt ngang JSON.

    Giữ hình dạng là điểm chính: màn hình vẫn đọc được *công cụ nào, tệp nào* — gần hết thứ
    người ta cần từ một dòng danh sách — mà toàn văn vẫn còn nguyên ở kho.
    """
    args = {"path": "/etc/hosts", "content": "y" * 9000}
    got = split("tool.started", {"call": "t1", "args": args}, 2048)

    assert got.whole is not None
    kept = got.payload["args"]
    assert isinstance(kept, dict), "tham số vẫn phải là object"
    assert kept["path"] == "/etc/hosts", "trường ngắn không bị đụng tới"
    assert len(kept["content"]) < len(args["content"])
    assert "y" * 32 in kept["content"], "phần giữ lại phải còn đọc được"


# ── đi qua cửa thật ──────────────────────────────────────────────────────────


async def test_a_long_thing_the_agent_said_is_stored_in_two_pieces():
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"long-{uuid4().hex[:8]}@example.com")
        whole = "một câu rất dài. " * 500
        await _say(c, machine, run, [
            {"seq": run["first_seq"], "type": "assistant.message", "payload": {"text": whole}},
        ])

        listed = await c.get(f"/v1/runs/{run['run_id']}/events", headers=machine.headers)
        assert listed.status_code == 200, listed.text
        said = [e for e in listed.json() if e["type"] == "assistant.message"][0]

        assert said["truncated"] is True
        assert said["original_byte_size"] == len(whole.encode("utf-8"))
        assert said["full_field"] == "text"
        assert said["full_byte_size"] == len(whole.encode("utf-8"))
        assert len(said["payload"]["text"]) < len(whole)
        assert said["omission_reason"] is None, (
            "phần còn lại đang nằm ngay đây, không mất — mang lý do thiếu là bảo người đọc "
            "đừng đi hỏi thứ họ hỏi được (FR-047)"
        )


async def test_the_whole_of_it_comes_back_byte_for_byte_when_asked():
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"whole-{uuid4().hex[:8]}@example.com")
        whole = "chi tiết " * 900
        await _say(c, machine, run, [
            {"seq": run["first_seq"], "type": "assistant.message", "payload": {"text": whole}},
        ])

        opened = await c.get(
            f"/v1/runs/{run['run_id']}/events/{run['first_seq']}/full",
            headers=machine.headers,
        )

        assert opened.status_code == 200, opened.text
        assert opened.json()["content"] == whole
        assert opened.json()["field"] == "text"


async def test_the_message_the_agent_was_given_is_kept_whole_however_long_it_is():
    """Prompt là thứ dài đều đặn ở phía này, và cũng là thứ người ta đọc trọn khi muốn biết
    *vì sao agent làm thế* (FR-042, SC-013)."""
    async with _client() as c:
        machine, run = await _a_run_in_hand(
            c, f"prompt-{uuid4().hex[:8]}@example.com", instructions="Hãy cẩn thận. " * 400
        )

        listed = await c.get(f"/v1/runs/{run['run_id']}/events", headers=machine.headers)
        written = [e for e in listed.json() if e["type"] == "run.prompt"][0]
        assert written["truncated"] is True
        assert written["full_field"] == "prompt"

        opened = await c.get(
            f"/v1/runs/{run['run_id']}/events/{written['seq']}/full", headers=machine.headers
        )
        assert opened.status_code == 200, opened.text
        assert opened.json()["content"] == run["prompt"], (
            "bản giữ lại phải đúng bằng chữ đã đưa cho agent"
        )


async def test_asking_for_the_rest_of_something_that_has_no_rest_is_not_found():
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"norest-{uuid4().hex[:8]}@example.com")
        await _say(c, machine, run, [
            {"seq": run["first_seq"], "type": "assistant.message", "payload": {"text": "ngắn"}},
        ])

        asked = await c.get(
            f"/v1/runs/{run['run_id']}/events/{run['first_seq']}/full", headers=machine.headers
        )

        assert asked.status_code == 404, asked.text


# ── lọc và đi dần (FR-052) ───────────────────────────────────────────────────


async def test_the_log_can_be_narrowed_to_the_kinds_being_looked_for():
    """Tìm một lần gọi công cụ giữa hàng nghìn dòng bằng mắt thì không phải là tìm được."""
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"filter-{uuid4().hex[:8]}@example.com")
        first = run["first_seq"]
        await _say(c, machine, run, [
            {"seq": first, "type": "assistant.message", "payload": {"text": "a"}},
            {"seq": first + 1, "type": "tool.started",
             "payload": {"call": "t1", "name": "read_file", "args": {"path": "/x"}}},
            {"seq": first + 2, "type": "assistant.thinking", "payload": {"text": "b"}},
            {"seq": first + 3, "type": "tool.completed",
             "payload": {"call": "t1", "bytes": 4, "opening": "abcd"}},
        ])

        only_tools = await c.get(
            f"/v1/runs/{run['run_id']}/events",
            params=[("type", "tool.started"), ("type", "tool.completed")],
            headers=machine.headers,
        )

        assert only_tools.status_code == 200, only_tools.text
        kinds = {e["type"] for e in only_tools.json()}
        assert kinds == {"tool.started", "tool.completed"}


async def test_a_reader_walks_a_long_run_by_the_number_it_stopped_at():
    """Đi theo `seq` chứ không theo vị trí: số của lượt chạy không xê dịch khi có lô về sau."""
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"walk-{uuid4().hex[:8]}@example.com")
        first = run["first_seq"]
        await _say(c, machine, run, [
            {"seq": first + i, "type": "assistant.message", "payload": {"text": str(i)}}
            for i in range(6)
        ])

        page = await c.get(
            f"/v1/runs/{run['run_id']}/events",
            params={"after_seq": first + 1, "limit": 2},
            headers=machine.headers,
        )

        assert [e["seq"] for e in page.json()] == [first + 2, first + 3]


async def test_the_log_of_another_workspaces_run_reads_as_not_there():
    """Nhật ký mang prompt và kết quả làm việc; đọc nhầm là đọc trộm việc người khác
    (FR-051, Hiến pháp — Điều I)."""
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"mine-{uuid4().hex[:8]}@example.com")
        await _say(c, machine, run, [
            {"seq": run["first_seq"], "type": "assistant.message",
             "payload": {"text": "riêng tư " * 400}},
        ])
        stranger, _ = await _a_run_in_hand(c, f"theirs-{uuid4().hex[:8]}@example.com")

        listed = await c.get(f"/v1/runs/{run['run_id']}/events", headers=stranger.headers)
        opened = await c.get(
            f"/v1/runs/{run['run_id']}/events/{run['first_seq']}/full",
            headers=stranger.headers,
        )

        assert listed.status_code == 404, listed.text
        assert opened.status_code == 404, opened.text


def test_the_threshold_is_something_that_can_be_set():
    """FR-049 đòi ngưỡng đặt được, và một hằng số nằm trong mã thì không đặt được."""
    assert settings.run_event_inline_bytes > 0


# ── đường sống (FR-046, SC-012) ──────────────────────────────────────────────


async def test_a_run_being_watched_live_is_told_what_the_machine_just_said():
    """Bản ghi đầy đủ mà im lặng lúc đang chạy là nửa còn lại — nửa người ta đang ngồi xem.

    Kênh của **lượt chạy** tách khỏi kênh của **đầu việc**: phòng làm việc hỏi *chuyện gì đang
    xảy ra với việc này*, còn màn nhật ký hỏi *agent này đã làm gì*. Trước T103 chỉ có bộ chạy
    trong tiến trình nuôi kênh thứ hai, nên một lượt chạy trên máy thật ghi đủ bản ghi mà không
    đẩy ra một chữ nào.
    """
    from armarius.main import app

    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"live-{uuid4().hex[:8]}@example.com")
        heard: list[dict] = []

        watching = app.state.container.event_bus.subscribe(UUID(run["run_id"]))

        async def listen() -> None:
            async for event in watching:
                heard.append(event)

        ear = asyncio.create_task(listen())
        await asyncio.sleep(0)

        await _say(c, machine, run, [
            {"seq": run["first_seq"], "type": "assistant.message",
             "payload": {"text": "vừa mới xảy ra"}},
        ])
        for _ in range(20):
            if heard:
                break
            await asyncio.sleep(0.05)
        ear.cancel()

        assert heard, "không có gì đẩy ra kênh của lượt chạy"
        assert heard[0]["type"] == "assistant.message"
        assert heard[0]["seq"] == run["first_seq"]
        assert heard[0]["payload"]["text"] == "vừa mới xảy ra"


async def test_the_live_push_carries_the_opening_slice_not_the_whole_of_it():
    """Đường đẩy trực tiếp gửi đúng thứ hàng đã lưu giữ: **phần đầu**, không phải toàn văn.

    Cùng một luật hai-đường ở bài dưới, nhưng ở phần thân chứ không phải ở mấy cột giải thích.
    Đường đẩy trước đây gửi payload **máy báo lên**, còn hàng lưu giữ payload **đã cắt** — nên
    một sự kiện dài về màn hình theo hai hình dạng, và cái nào thắng là do lô nào tới trước.

    Hai chỗ hỏng, không phải một. Người xem trực tiếp phải kéo cả megabyte vào trang, đúng thứ
    FR-049 dựng ra để tránh (SC-014). Và khung đẩy vẫn kèm `_full_field` — *còn nữa, xin thì
    có* — cho một đoạn văn nó **đã** cầm trong tay, nên nút mở toàn văn đi hỏi lại thứ đang nằm
    sẵn trong trang.
    """
    from armarius.main import app

    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"slice-{uuid4().hex[:8]}@example.com")
        whole = "đủ dài để phải tách" * 400
        heard: list[dict] = []

        watching = app.state.container.event_bus.subscribe(UUID(run["run_id"]))

        async def listen() -> None:
            async for event in watching:
                heard.append(event)

        ear = asyncio.create_task(listen())
        await asyncio.sleep(0)

        await _say(c, machine, run, [
            {"seq": run["first_seq"], "type": "assistant.message", "payload": {"text": whole}},
        ])
        for _ in range(20):
            if heard:
                break
            await asyncio.sleep(0.05)
        ear.cancel()

        assert heard, "không có gì đẩy ra kênh của lượt chạy"
        pushed = heard[0]["payload"]
        assert pushed["_full_field"] == "text", "khung đẩy phải nói là còn nữa"
        assert pushed["_full_byte_size"] == len(whole.encode("utf-8"))
        assert len(pushed["text"]) < len(whole), "đường đẩy vẫn mang toàn văn"

        listed = await c.get(
            f"/v1/runs/{run['run_id']}/events", headers=machine.headers
        )
        assert listed.status_code == 200, listed.text
        stored = next(e for e in listed.json() if e["seq"] == run["first_seq"])
        assert pushed["text"] == stored["payload"]["text"], "hai đường mang hai thân khác nhau"


def test_the_two_roads_to_one_run_carry_the_same_facts_about_it():
    """Đọc bằng danh sách bền và đọc bằng đường phát lại phải ra **cùng một** sự thật.

    Cùng một lượt chạy tới màn hình bằng hai đường, và người đọc không được thấy hai phiên bản
    của nó tuỳ theo sự kiện ấy rơi vào nửa nào. Đường phát lại từng chỉ gửi phần thân, nên một
    sự kiện phát lại mất sạch *vì sao nó ngắn* và *có bị che gì không* — đúng mấy điều FR-047
    dựng ra để giữ.

    Kiểm bằng **hình dạng**, không bằng một ví dụ: thêm một cột vào hàng lưu rồi quên đường
    phát lại là cách hai đường lệch nhau lần nữa, lặng lẽ, và lệch về phía hiện ra ít hơn.
    """
    said = about_the_record(
        RunEvent(
            seq=7,
            type="tool.completed",
            payload={"call": "t1"},
            truncated=True,
            original_byte_size=9000,
            omission_reason="truncated_by_policy",
            redacted=True,
            full_field="args",
            full_byte_size=9000,
            created_at=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
        )
    )

    beside = set(RunEventOut.model_fields) - {"seq", "type", "payload"}
    assert beside <= set(said), f"đường phát lại thiếu: {sorted(beside - set(said))}"
    assert said["truncated"] is True
    assert said["omission_reason"] == "truncated_by_policy"
    assert said["full_field"] == "args"
    assert said["created_at"] == "2026-08-30T12:00:00+00:00"
