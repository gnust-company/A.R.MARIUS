"""Không đường nào ghi được một credential của chính hệ thống vào sổ (T143, FR-048c).

Cửa dựng ở T106 đứng trên **một** lối: lối daemon gõ vào. Còn hai lối nữa, và cả hai là phía
server viết về chính nó — chữ nó soạn cho agent (`run.prompt`), và sự kiện của một lượt chạy nó
tự chạy trong tiến trình của mình. Hôm nay cả hai lối ấy đều lành: token đi vào agent bằng
**tiến trình**, không bằng chữ. Vấn đề là không có gì bắt chúng phải lành mãi.

Cách vá dễ nghĩ nhất là chép phép kiểm thêm một bản ở lối thứ hai. Hai thành ba, ba thành bốn,
và cái thứ tư là cái quên. Nên phép kiểm dời về đúng chỗ cả ba lối đều đi qua dù có muốn hay
không: **lúc dòng được chèn xuống**. Người viết lối thứ tư sang năm không cần biết luật này tồn
tại thì vẫn bị nó giữ.

Cửa trên vẫn ở nguyên chỗ cũ, và không thừa: nó trả về cho máy một **mã có tên**, kịp để máy bỏ
lô và sửa phép che (T141). Cái ở đây không nói với ai cả — tới lúc dòng đang được chèn thì việc
duy nhất còn đáng làm là đừng chèn. Cửa và kho, đúng hình dạng T098.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from armarius.domain.entities.run import RunEvent
from armarius.infrastructure.daemon.models import RunEventBlobModel
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import RunEventModel, WakeupModel
from armarius.main import app
from armarius.shared.clock import utcnow
from armarius.shared.credentials import MACHINE_TOKEN_PREFIX, RUN_TOKEN_PREFIX
from armarius.shared.errors import BadRequest
from tests.support.agents import invite_agent
from tests.support.machines import auth, link_machine
from tests.support.work import a_project, a_task, shelve

pytestmark = pytest.mark.anyio

#: Hình dạng một token của lượt chạy, đúng chiều dài thật, nhưng không phải token của ai cả.
A_TOKEN_SHAPED_STRING = f"{RUN_TOKEN_PREFIX}{'x' * 43}"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _ask_for_work(
    c: AsyncClient, email: str, *, instructions: str
) -> tuple[object, dict]:
    """Dựng máy + agent + việc, rồi hỏi xin việc **một lần** và trả về nguyên câu trả lời.

    Trả về cả câu chứ không phải `runs[0]`: nửa số bài kiểm ở đây mong câu trả lời **rỗng**,
    và một helper chỉ biết bốc phần tử đầu thì hỏng ở đúng chỗ đang cần đọc.
    """
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
    return machine, answered.json()


async def _anywhere_in_the_log(needle: str) -> bool:
    """Có dòng nào của `run_events` — của bất kỳ lượt chạy nào — nhắc tới chuỗi này không.

    Soi theo **chuỗi** chứ không đếm số dòng: đếm thì phải chụp hai lần trước-sau và tin rằng
    giữa hai lần ấy không ai ghi gì, mà đó là niềm tin vào thứ tự chạy của cả bộ kiểm.
    """
    async with get_sessionmaker()() as session:
        rows = (await session.execute(select(RunEventModel.payload))).scalars().all()
    return any(needle in str(row) for row in rows)


# ── lối server tự soạn chữ ───────────────────────────────────────────────────


async def test_a_token_in_what_the_server_composed_never_becomes_a_row() -> None:
    """Lối `_record`: server soạn chữ, server tự ghi, lưới che của máy không chạm tới.

    Đưa hình dạng token vào chỉ dẫn thường trực của agent là đường thật ngắn nhất tới đó —
    chỉ dẫn được ghép thẳng vào chữ gửi agent, nên đây đúng là *một lần thoái lui trong tương
    lai* trông sẽ như thế nào.
    """
    async with _client() as c:
        _, answered = await _ask_for_work(
            c,
            f"compose-{uuid4().hex[:8]}@example.com",
            instructions=f"Dùng khoá này: {A_TOKEN_SHAPED_STRING}",
        )

    assert answered["runs"] == [], "việc phải bị trả lại chứ không được giao đi cùng chữ ấy"
    assert not await _anywhere_in_the_log(A_TOKEN_SHAPED_STRING), "và không dòng nào giữ lại nó"


async def test_a_name_that_merely_starts_like_a_token_does_not_cost_a_run() -> None:
    """Mặt kia của cùng phép kiểm, và là mặt tốn kém hơn nếu sai.

    Từ chối quá tay ở đây không mất một lô sự kiện — nó mất **cả lượt chạy**: việc bị trả về
    kệ, rồi lần hỏi sau lại hỏng đúng như thế, mãi mãi. Nên `armd_config_name` phải đi qua.
    """
    async with _client() as c:
        _, answered = await _ask_for_work(
            c,
            f"name-{uuid4().hex[:8]}@example.com",
            instructions=f"Đọc {MACHINE_TOKEN_PREFIX}config_name rồi làm theo.",
        )
    assert len(answered["runs"]) == 1, "một cái tên chỉ *bắt đầu* giống token thì không phải token"


# ── lối bộ chạy trong tiến trình ─────────────────────────────────────────────


async def test_the_in_process_runner_writes_through_the_same_door() -> None:
    """Lối `_emit`: đi qua repository chứ không qua cửa daemon, và vẫn phải bị giữ lại."""
    async with _client() as c:
        _, answered = await _ask_for_work(
            c, f"inproc-{uuid4().hex[:8]}@example.com", instructions="Bình thường."
        )
        run = answered["runs"][0]

        with pytest.raises(BadRequest) as refused:
            async with app.state.container.uow_factory() as uow:
                await uow.run_events.add(
                    RunEvent(
                        run_id=UUID(run["run_id"]),
                        seq=run["first_seq"] + 5,
                        type="assistant.message",
                        payload={"text": f"đây này: {A_TOKEN_SHAPED_STRING}"},
                        created_at=utcnow(),
                    )
                )
                await uow.commit()
    assert refused.value.code == "credential_in_the_clear"


# ── nửa để riêng ─────────────────────────────────────────────────────────────


async def test_the_half_kept_apart_is_read_too() -> None:
    """Sự kiện dài được giữ làm hai mảnh (FR-049), và bí mật không hứa nằm ở mảnh đầu.

    Phép kiểm chỉ đọc thân sự kiện là phép kiểm chống bí mật *trong hai kilobyte đầu* — không
    phải luật ai đó định ra. Nên dòng sự kiện ở đây sạch, và chỉ toàn văn để riêng là bẩn.
    """
    async with _client() as c:
        machine, answered = await _ask_for_work(
            c, f"blob-{uuid4().hex[:8]}@example.com", instructions="Bình thường."
        )
        run = answered["runs"][0]

    async with get_sessionmaker()() as session:
        event = (
            await session.execute(
                select(RunEventModel).where(RunEventModel.run_id == UUID(run["run_id"]))
            )
        ).scalars().first()
        assert event is not None
        with pytest.raises(BadRequest) as refused:
            session.add(
                RunEventBlobModel(
                    id=uuid4(),
                    run_event_id=event.id,
                    workspace_id=UUID(str(machine.workspace_id)),
                    field="text",
                    content=f"...rất dài... {A_TOKEN_SHAPED_STRING}",
                    byte_size=64,
                )
            )
            await session.flush()
    assert refused.value.code == "credential_in_the_clear"


# ── cửa trên vẫn nói được câu của nó ─────────────────────────────────────────


async def test_the_door_upstairs_still_answers_with_a_name_the_machine_can_act_on() -> None:
    """Lưới dưới không được nuốt mất câu trả lời của cửa trên.

    Một cửa trả `400 credential_in_the_clear` thì máy biết bỏ lô và sửa phép che. Nếu lưới ở
    tầng ghi bắt trước, máy nhận về một lỗi không tên và chuyện im lặng ngay tại đó.
    """
    async with _client() as c:
        machine, answered = await _ask_for_work(
            c, f"door-{uuid4().hex[:8]}@example.com", instructions="Bình thường."
        )
        run = answered["runs"][0]
        sent = await c.post(
            f"/daemon/runs/{run['run_id']}/events",
            json={
                "events": [
                    {
                        "seq": run["first_seq"],
                        "type": "assistant.message",
                        "payload": {"text": A_TOKEN_SHAPED_STRING},
                    }
                ]
            },
            headers=auth(machine.token),
        )
    assert sent.status_code == 400, sent.text
    assert sent.json()["code"] == "credential_in_the_clear"


# ── bản sao của chữ đã gửi ───────────────────────────────────────────────────


async def test_the_copy_of_the_message_that_went_out_is_held_to_the_same_rule() -> None:
    """`wakeup_requests.prompt` giữ nguyên văn chữ đã gửi, và được **ghi đè vào sau**.

    Lối gọi dậy chạy trong tiến trình không ghi dòng `run.prompt` nào cả — nó dựng hàng chờ
    trước, rồi điền chữ vào sau khi soạn xong. Cùng một chữ, tên cột khác, và một lưới chỉ
    canh lúc *chèn* sẽ nhìn thấy dòng lúc nó còn trống.
    """
    async with get_sessionmaker()() as session:
        wake = WakeupModel(
            id=uuid4(),
            marius_id=uuid4(),
            task_id=uuid4(),
            source="on_demand",
            causes=[],
            status="done",
            created_at=utcnow(),
        )
        session.add(wake)
        await session.flush()

        wake.prompt = f"Dùng khoá này: {A_TOKEN_SHAPED_STRING}"
        with pytest.raises(BadRequest) as refused:
            await session.flush()
    assert refused.value.code == "credential_in_the_clear"
