"""Lượt chạy nói về mình — lúc đang chạy, và lúc khép lại (T067, T068, T097, T098).

Cho tới đợt này, một lượt chạy trên máy người dùng đi ra khỏi cửa nhận việc rồi biến mất.
Server biết nó đã được trao đi và không biết gì thêm: không một dòng agent nói, không một
lời gọi công cụ, và không cả cái mốc *xong rồi*. Ba hệ quả, và không cái nào tự lộ ra:

  * màn hình theo dõi đầu việc đứng yên suốt cả lượt chạy (FR-046),
  * ngưỡng im lặng đọc mọi lượt chạy là im — vì đúng là không có gì được ghi (FR-030),
  * token của lượt chạy sống mãi, vì không có chỗ nào tuyên bố lượt chạy đã hết (FR-014b).

Hai cửa ở đây đóng cả ba. Bài kiểm chạy qua **app thật** cùng container thật, nên cái kệ nó
đọc đúng là cái bảng phần còn lại của hệ thống ghi vào.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from armarius.domain.entities.run import RunStatus
from armarius.infrastructure.daemon.models import RunClaimModel
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import RunEventModel, RunModel
from armarius.main import app
from armarius.shared.clock import utcnow
from tests.support.agents import invite_agent
from tests.support.machines import LinkedMachine, auth, link_machine
from tests.support.work import a_project, a_task, shelve

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class Held:
    """One run, on the shelf, taken by a machine — the state both doors start from."""

    def __init__(self, machine: LinkedMachine, marius_id: str, run: dict, task_id: UUID):
        self.machine = machine
        self.marius_id = marius_id
        #: The packet exactly as it went out on the wire, for the tests that are about that.
        self.raw = run
        self.run_id = run["run_id"]
        self.first_seq = run["first_seq"]
        self.task_id = task_id

    @property
    def headers(self) -> dict[str, str]:
        return auth(self.machine.token)


async def _held(c: AsyncClient, email: str, *, hostname: str = "thinkpad") -> Held:
    """Everything a run goes through before it can say anything, with nothing shortcut."""
    machine = await link_machine(c, email, hostname=hostname)
    agent = await invite_agent(
        c,
        machine.workspace_id,
        machine.headers,
        name=hostname,
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
    runs = answered.json()["runs"]
    assert len(runs) == 1, runs
    return Held(machine, agent["id"], runs[0], task_id)


async def _log(run_id: str) -> list[RunEventModel]:
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            select(RunEventModel)
            .where(RunEventModel.run_id == UUID(run_id))
            .order_by(RunEventModel.seq)
        )
        return list(rows.scalars())


async def _run(run_id: str) -> RunModel:
    async with get_sessionmaker()() as session:
        return await session.get(RunModel, UUID(run_id))


async def _claim_row(run_id: str) -> RunClaimModel:
    async with get_sessionmaker()() as session:
        return await session.get(RunClaimModel, UUID(run_id))


def _say(held: Held, *, at: int, kind: str = "assistant.message", **payload) -> dict:
    return {"seq": at, "type": kind, "payload": payload or {"text": "working on it"}}


async def test_the_hold_deadline_says_which_moment_it_is() -> None:
    """Một mốc thời gian không kèm múi giờ là một mốc không đọc được (T067, tìm ra lúc chạy thật).

    Cột thời gian trả về **có** múi giờ ở database này và **không** ở database kia, mà "không
    có" đâu phải phiên bản gọn hơn của "có": nó đi ra dây không kèm offset, và cái máy nhận
    được không phân tích nổi. Cú xin việc hỏng ngay tại chỗ giải mã, nên cái máy ấy không bao
    giờ nhận được một đầu việc nào — hỏng toàn phần, mà lời báo lỗi thì nói về JSON.

    Tìm ra bằng cách chạy daemon thật, không phải bằng đọc mã: mọi bài kiểm bên Go đều nói
    chuyện với một server giả, và server giả thì viết đúng chuẩn.
    """
    from datetime import datetime

    async with _client() as c:
        held = await _held(c, "tz@armarius.dev")

    said = held.raw["claim_expires_at"]
    when = datetime.fromisoformat(said)
    assert when.tzinfo is not None, f"hạn giữ đi ra dây mà không nói mình ở múi giờ nào: {said}"


# ── kể lại trong lúc đang chạy ────────────────────────────────────────────────


async def test_what_the_agent_does_is_written_down_as_it_happens() -> None:
    async with _client() as c:
        held = await _held(c, "reports@armarius.dev")
        first = held.first_seq

        sent = await c.post(
            f"/daemon/runs/{held.run_id}/events",
            json={
                "events": [
                    _say(held, at=first, text="on it"),
                    _say(held, at=first + 1, kind="tool.started", call="c1", name="read_file"),
                ]
            },
            headers=held.headers,
        )
        assert sent.status_code == 200, sent.text

        written = await _log(held.run_id)
        assert [e.type for e in written] == [
            "run.prompt",
            "assistant.message",
            "tool.started",
        ], [e.type for e in written]
        # Và cái cột ngưỡng im lặng đọc: không có nó thì mọi lượt chạy đều "im" (FR-030).
        assert (await _run(held.run_id)).last_output_at is not None


async def test_the_machine_numbers_from_where_the_server_said_and_never_over_the_message() -> None:
    """Thông điệp gửi agent đã nằm sẵn trong sổ trước khi agent tồn tại (FR-012a).

    Nên chỗ bắt đầu của máy không phải lúc nào cũng là 1: nó là *sau* mọi thứ đã ghi. Đây
    là thứ giữ cho cặp (lượt chạy, số thứ tự) là duy nhất mà không cần một vòng hỏi-đáp cho
    mỗi sự kiện (FR-045).
    """
    async with _client() as c:
        held = await _held(c, "numbering@armarius.dev")
        prompt = (await _log(held.run_id))[0]
        assert held.first_seq == prompt.seq + 1


async def test_a_batch_sent_twice_is_written_once() -> None:
    """Gói tin trả lời rơi mất là lý do bình thường nhất để máy gọi lại (FR-045)."""
    async with _client() as c:
        held = await _held(c, "twice@armarius.dev")
        batch = {"events": [_say(held, at=held.first_seq, text="only once")]}

        for _ in range(2):
            again = await c.post(
                f"/daemon/runs/{held.run_id}/events", json=batch, headers=held.headers
            )
            assert again.status_code == 200, again.text

        said = [e for e in await _log(held.run_id) if e.type == "assistant.message"]
        assert len(said) == 1, [(e.seq, e.type) for e in await _log(held.run_id)]


async def test_a_tool_result_that_was_not_cut_down_is_refused() -> None:
    """Kiểm ở tầng nhận, không tin daemon đã cắt đúng (FR-043a, T098).

    Cắt trên máy là thứ giữ các byte ở nhà; phép kiểm này là thứ làm cho luật đúng với **kho**
    chứ không chỉ đúng với hành vi tử tế của một chương trình. Một daemon bản cũ, một daemon
    ai đó vá, hay một thứ không phải daemon nhưng cầm token của máy — cả ba đều tới đây.
    """
    async with _client() as c:
        held = await _held(c, "uncut@armarius.dev")

        named = await c.post(
            f"/daemon/runs/{held.run_id}/events",
            json={
                "events": [
                    {
                        "seq": held.first_seq,
                        "type": "tool.completed",
                        "payload": {"call": "c1", "content": "the whole file"},
                    }
                ]
            },
            headers=held.headers,
        )
        assert named.status_code == 400, named.text

        huge = await c.post(
            f"/daemon/runs/{held.run_id}/events",
            json={
                "events": [
                    {
                        "seq": held.first_seq,
                        "type": "tool.completed",
                        "payload": {"call": "c1", "head": "x" * 8000},
                    }
                ]
            },
            headers=held.headers,
        )
        assert huge.status_code == 400, huge.text

        # Cả lô bị từ chối, không ghi nửa nào: một nửa được ghi để lại một lỗ ở một số thứ tự
        # sẽ không bao giờ được lấp, vì máy không có cách gửi thứ khác dưới số nó đã dùng.
        assert [e.type for e in await _log(held.run_id)] == ["run.prompt"]


async def test_a_summarised_tool_result_goes_through() -> None:
    async with _client() as c:
        held = await _held(c, "cut@armarius.dev")
        sent = await c.post(
            f"/daemon/runs/{held.run_id}/events",
            json={
                "events": [
                    {
                        "seq": held.first_seq,
                        "type": "tool.completed",
                        "payload": {"call": "c1", "failed": False},
                    }
                ]
            },
            headers=held.headers,
        )
        assert sent.status_code == 200, sent.text


async def test_a_machine_that_no_longer_holds_the_run_cannot_write_about_it() -> None:
    """Lưới cho ca không tránh được: đồng hồ hai bên lệch nhau (FR-059).

    Máy đã bị thu hồi vẫn tưởng mình còn giữ và vẫn bật agent lên. Chặn được cú ghi thì lần
    chạy thừa ấy không để lại dấu vết nào.
    """
    async with _client() as c:
        held = await _held(c, "taken-back@armarius.dev")
        async with get_sessionmaker()() as session:
            await session.execute(
                update(RunClaimModel)
                .where(RunClaimModel.run_id == UUID(held.run_id))
                .values(claim_expires_at=utcnow() - timedelta(seconds=1))
            )
            await session.commit()

        refused = await c.post(
            f"/daemon/runs/{held.run_id}/events",
            json={"events": [_say(held, at=held.first_seq)]},
            headers=held.headers,
        )
        assert refused.status_code == 404, refused.text
        assert [e.type for e in await _log(held.run_id)] == ["run.prompt"]


async def test_another_machine_cannot_write_about_this_ones_run() -> None:
    async with _client() as c:
        held = await _held(c, "mine@armarius.dev")
        stranger = await link_machine(c, "stranger@armarius.dev", hostname="other")

        refused = await c.post(
            f"/daemon/runs/{held.run_id}/events",
            json={"events": [_say(held, at=held.first_seq)]},
            headers=auth(stranger.token),
        )
        # Không phải của bạn và không tồn tại đọc y hệt nhau (Điều I).
        assert refused.status_code == 404, refused.text


async def test_a_run_nobody_ever_heard_of_reads_the_same_as_one_next_door() -> None:
    async with _client() as c:
        held = await _held(c, "ghost@armarius.dev")
        nowhere = await c.post(
            f"/daemon/runs/{uuid4()}/events",
            json={"events": [_say(held, at=1)]},
            headers=held.headers,
        )
        assert nowhere.status_code == 404, nowhere.text


# ── khép lại ─────────────────────────────────────────────────────────────────


async def test_finishing_a_run_revokes_its_token_and_closes_it() -> None:
    async with _client() as c:
        held = await _held(c, "finish@armarius.dev")
        before = await _claim_row(held.run_id)
        assert before.run_token_hash is not None, "chưa trao thì chưa có gì để thu hồi"

        closed = await c.post(
            f"/daemon/runs/{held.run_id}/finish",
            json={"status": "completed", "usage": {"input_tokens": 40}},
            headers=held.headers,
        )
        assert closed.status_code == 200, closed.text

        after = await _claim_row(held.run_id)
        assert after.run_token_hash is None, "token của lượt chạy còn mở được thứ gì đó"
        assert after.machine_id is None
        run = await _run(held.run_id)
        assert run.status == RunStatus.COMPLETED.value, run.status
        assert run.finished_at is not None
        assert run.usage_json == {"input_tokens": 40}


async def test_a_token_that_was_revoked_no_longer_opens_the_run() -> None:
    """FR-014b có một nửa dễ quên: thu hồi phải *có tác dụng*, không chỉ là xoá một cột."""
    async with _client() as c:
        held = await _held(c, "revoked@armarius.dev")
        await c.post(
            f"/daemon/runs/{held.run_id}/finish",
            json={"status": "completed"},
            headers=held.headers,
        )

        late = await c.post(
            f"/daemon/runs/{held.run_id}/events",
            json={"events": [_say(held, at=held.first_seq + 50)]},
            headers=held.headers,
        )
        assert late.status_code == 404, late.text


async def test_a_run_that_failed_is_closed_as_failed_with_the_reason() -> None:
    async with _client() as c:
        held = await _held(c, "failed@armarius.dev")
        closed = await c.post(
            f"/daemon/runs/{held.run_id}/finish",
            json={"status": "failed", "error": "claude ended badly: exit status 1"},
            headers=held.headers,
        )
        assert closed.status_code == 200, closed.text

        run = await _run(held.run_id)
        assert run.status == RunStatus.FAILED.value
        assert "exit status 1" in (run.error or "")


async def test_finishing_twice_does_not_close_the_run_twice() -> None:
    """Gọi lại là chuyện thường — gói tin trả lời rơi mất là lý do bình thường nhất."""
    async with _client() as c:
        held = await _held(c, "finish-twice@armarius.dev")
        body = {"status": "completed"}
        first = await c.post(
            f"/daemon/runs/{held.run_id}/finish", json=body, headers=held.headers
        )
        second = await c.post(
            f"/daemon/runs/{held.run_id}/finish", json=body, headers=held.headers
        )
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert (await _run(held.run_id)).status == RunStatus.COMPLETED.value


async def test_a_finished_run_leaves_the_task_with_something_pushing_it() -> None:
    """FR-030a — cái lỗ quan sát được ở Multica.

    Lượt chạy kết thúc sạch, đầu việc vẫn ở *đang làm*, và không tác nhân nào được xếp lịch
    quay lại nhìn nó. Vòng quét bắt được ca này nhưng bắt muộn, nên nó là lớp cuối chứ không
    phải cách xử chính: cửa khép lượt chạy phải để lại một động cơ đẩy **sống ngay**.
    """
    from armarius.domain.entities.task import TaskStatus
    from armarius.infrastructure.database.models import TaskModel, WakeupModel

    async with _client() as c:
        held = await _held(c, "still-going@armarius.dev")
        # Đầu việc đang làm dở và còn hành động kế tiếp đã lưu: đúng ca FR-030a nói tới.
        async with get_sessionmaker()() as session:
            await session.execute(
                update(TaskModel)
                .where(TaskModel.id == held.task_id)
                .values(
                    status=TaskStatus.IN_PROGRESS.value,
                    next_action="carry on where the last turn stopped",
                )
            )
            await session.commit()

        closed = await c.post(
            f"/daemon/runs/{held.run_id}/finish",
            json={"status": "completed"},
            headers=held.headers,
        )
        assert closed.status_code == 200, closed.text

        async with get_sessionmaker()() as session:
            booked = list(
                (
                    await session.execute(
                        select(WakeupModel).where(WakeupModel.task_id == held.task_id)
                    )
                ).scalars()
            )
        assert booked, "lượt chạy xong mà không có gì được xếp lịch quay lại nhìn đầu việc"


async def test_a_started_run_can_never_be_handed_out_a_second_time() -> None:
    """Cái lưới duy nhất giữ cho hai daemon cùng danh tính không giẫm lên nhau (FR-054b).

    Ca người review nêu: lúc nâng cấp có hai daemon cùng sống một lúc, **cùng một `machine_id`**.
    Daemon cũ gọi `finish` sau khi daemon mới đã nhận lại lượt chạy ấy thì sẽ xoá mối giữ của
    daemon mới — lượt chạy về kệ trong khi vẫn đang chạy. Bản thân `finish` không chặn được, vì
    hai bên trình cùng một token của cùng một cái máy: mọi phép so danh tính đều thấy khớp.

    Cái chặn nằm ở chỗ khác, và là **hai thứ rời nhau**, nên bài này ghim cả hai:

      1. `start` gỡ hẳn đồng hồ giữ, mà vòng thu hồi chỉ đụng vào hàng **còn** đồng hồ.
      2. Câu lệnh lấy việc chỉ nhặt lượt chạy đang `queued`, mà một lượt đã bật agent thì
         `running`.

    Mỗi cái một mình là đủ; đó chính là lý do phải ghim cả hai. Bảo vệ kiểu này là bảo vệ tình
    cờ — nó đúng hôm nay vì hai chỗ chẳng liên quan tình cờ hợp nhau, và nó tan ngày ai đó sửa
    một trong hai vì lý do khác. Ghim bằng bài kiểm chứ không thêm lưới ở `finish`: thêm lưới là
    viết mã cho một đường không tới được, còn bài này đỏ đúng vào ngày đường ấy mở ra.
    """
    async with _client() as c:
        held = await _held(c, "upgrade-overlap@armarius.dev")
        started = await c.post(
            f"/daemon/runs/{held.run_id}/start",
            json={"session_handle": ""},
            headers=held.headers,
        )
        assert started.status_code == 200, started.text

        # (1) Đồng hồ giữ đã tắt hẳn, nên không có gì để vòng thu hồi bắt được.
        assert (await _claim_row(held.run_id)).claim_expires_at is None, (
            "lượt chạy đã bật agent mà vẫn còn đồng hồ giữ — vòng thu hồi sẽ nhả nó ra"
        )

        # (2) Và ngay cả khi mối giữ *bị* nhả bằng cách nào đó, lượt chạy vẫn không được trao
        #     lại: nó đang `running`, mà cửa lấy việc chỉ nhặt `queued`. Dựng thẳng cái trạng
        #     thái tệ nhất ấy ra để đo, thay vì tin rằng nó không xảy ra được.
        async with get_sessionmaker()() as session:
            await session.execute(
                update(RunClaimModel)
                .where(RunClaimModel.run_id == UUID(held.run_id))
                .values(machine_id=None, claim_expires_at=None, run_token_hash=None)
            )
            await session.commit()

        asked = await c.post(
            "/daemon/runs/claim",
            json={"workplace_ids": [held.machine.workplace_id], "max": 5},
            headers=held.headers,
        )

    assert asked.json()["runs"] == [], (
        "lượt chạy đang chạy lại được trao lần nữa; từ đó `finish` của daemon cũ sẽ xoá mối "
        "giữ của daemon mới và đẩy một lượt chạy sống về kệ"
    )


async def test_another_machine_cannot_close_this_ones_run() -> None:
    async with _client() as c:
        held = await _held(c, "close-mine@armarius.dev")
        stranger = await link_machine(c, "close-stranger@armarius.dev", hostname="other")

        refused = await c.post(
            f"/daemon/runs/{held.run_id}/finish",
            json={"status": "completed"},
            headers=auth(stranger.token),
        )
        assert refused.status_code == 404, refused.text
        assert (await _run(held.run_id)).status != RunStatus.COMPLETED.value


async def test_an_ending_the_server_does_not_know_is_refused_at_the_door() -> None:
    async with _client() as c:
        held = await _held(c, "unknown-ending@armarius.dev")
        refused = await c.post(
            f"/daemon/runs/{held.run_id}/finish",
            json={"status": "went_quite_well_actually"},
            headers=held.headers,
        )
        assert refused.status_code == 422, refused.text
