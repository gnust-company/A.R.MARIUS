"""Không giá trị bí mật nào lọt lên server ở dạng nguyên bản (T106, SC-015, FR-048).

Che là việc của **máy**, và nó ở đó vì lý do thật: daemon được trao token của lượt chạy và token
của máy, nên nó tìm đúng hai chuỗi ấy — chính xác, không phải phỏng đoán (FR-048). Bài kiểm của
phép che ấy nằm bên Go, cạnh phép che.

Ở đây là hai câu hỏi **khác**, và không câu nào phía Go trả lời được.

**Một: chính server viết một sự kiện.** `run.prompt` là chữ server soạn và server tự ghi xuống,
trước khi daemon tồn tại — nên lưới che của máy không bao giờ chạm tới nó. Nếu chữ ấy có ngày mang
theo token (đúng thứ đã bàn ở #108/#109 rồi chốt là *token nằm trong file, không nhúng*), nó vào
thẳng sổ, và không một phép kiểm nào bên Go đỏ lên cả.

**Hai: một lô tới cửa mà chưa từng được che.** Một daemon bản cũ, một daemon ai đó vá, hay một
token của máy nằm trong tay thứ không phải daemon — cả ba đều tới đây và cả ba đều chưa che gì.
SC-015 nói *không có giá trị bí mật nào lọt lên server*, tức là một câu về **kho**, không phải một
câu về hạnh kiểm của một chương trình. Nên cửa có bản sao thứ hai của luật, đúng hình dạng T098
đã dựng cho kết quả công cụ.

Phía này không so theo **giá trị** được: nó chỉ giữ hash, không có gì để đem ra đối chiếu. Nên nó
so theo **hình dạng**, trên đúng hai tiền tố nó tự đúc ra — loại bí mật duy nhất mà phía này thật
sự biết mặt.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from armarius.infrastructure.daemon.models import RunClaimModel, RunEventBlobModel
from armarius.infrastructure.daemon.run_auth import hash_run_token
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import RunEventModel
from armarius.main import app
from armarius.shared.credentials import (
    CREDENTIAL_TAIL_FLOOR,
    MACHINE_TOKEN_PREFIX,
    OUR_CREDENTIALS,
    RUN_TOKEN_PREFIX,
)
from tests.support.agents import invite_agent
from tests.support.machines import auth, link_machine
from tests.support.work import a_project, a_task, shelve

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _a_run_in_hand(
    c: AsyncClient, email: str, *, instructions: str = ""
) -> tuple[object, dict]:
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


async def _everything_written_about(run_id: str) -> str:
    """Mọi chữ lượt chạy này để lại phía server: thân sự kiện và toàn văn để riêng."""
    async with get_sessionmaker()() as session:
        rows = (
            await session.execute(
                select(RunEventModel.payload).where(RunEventModel.run_id == UUID(run_id))
            )
        ).scalars()
        kept = (
            await session.execute(
                select(RunEventBlobModel.content)
                .join(RunEventModel, RunEventModel.id == RunEventBlobModel.run_event_id)
                .where(RunEventModel.run_id == UUID(run_id))
            )
        ).scalars()
        return "\n".join([str(p) for p in rows] + list(kept))


# ── chữ chính server viết ────────────────────────────────────────────────────


async def test_the_runs_token_is_not_in_the_message_the_server_wrote_down() -> None:
    """Token đi vào agent bằng **tiến trình**, không bằng chữ (FR-014c) — nên không có trong sổ."""
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"mint-{uuid4().hex[:8]}@example.com")
        token = run["run_token"]
        assert token.startswith(RUN_TOKEN_PREFIX)

        assert token not in run["prompt"], "chữ đưa cho agent không được mang theo token"
        assert token not in await _everything_written_about(run["run_id"])


async def test_a_message_long_enough_to_be_split_hides_no_token_in_its_second_half() -> None:
    """Nửa đi ra kho phụ là nửa **không ai nhìn** trong danh sách — nên phải soi riêng.

    Một prompt dài bị tách làm hai: phần đầu nằm trong dòng sự kiện, toàn văn nằm ở
    `run_event_blobs`. Một phép kiểm chỉ đọc dòng sự kiện sẽ xanh cho một prompt có token ở
    byte thứ ba nghìn.
    """
    async with _client() as c:
        machine, run = await _a_run_in_hand(
            c, f"split-{uuid4().hex[:8]}@example.com", instructions="Hãy cẩn thận. " * 400
        )
        async with get_sessionmaker()() as session:
            kept = (
                await session.execute(
                    select(RunEventBlobModel.content)
                    .join(RunEventModel, RunEventModel.id == RunEventBlobModel.run_event_id)
                    .where(RunEventModel.run_id == UUID(run["run_id"]))
                )
            ).scalars().all()
        assert kept, "prompt này phải đủ dài để bị tách, nếu không bài kiểm chẳng soi gì cả"
        for whole in kept:
            assert run["run_token"] not in whole


async def test_the_server_keeps_no_readable_copy_of_the_token_it_minted() -> None:
    """Một lần trong đời, và chỉ ở câu trả lời ấy. Cái ở lại là hash (FR-014, FR-014a)."""
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"hash-{uuid4().hex[:8]}@example.com")
        async with get_sessionmaker()() as session:
            claim = await session.get(RunClaimModel, UUID(run["run_id"]))
        assert claim is not None
        assert claim.run_token_hash == hash_run_token(run["run_token"])
        assert run["run_token"] not in str(
            {c.name: getattr(claim, c.name) for c in RunClaimModel.__table__.columns}
        )


async def test_the_machines_own_token_never_reaches_the_log() -> None:
    """Token của máy sống lâu hơn và mở được nhiều hơn — mất nó tệ hơn mất token một lượt chạy."""
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"mtok-{uuid4().hex[:8]}@example.com")
        assert machine.token.startswith(MACHINE_TOKEN_PREFIX)
        assert machine.token not in await _everything_written_about(run["run_id"])


# ── một lô chưa từng được che, tới cửa ───────────────────────────────────────


async def test_a_token_planted_in_tool_arguments_is_refused_at_the_door() -> None:
    """Đúng ca SC-015 mô tả: gài token vào tham số, và nó **không** vào tới kho."""
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"plant-{uuid4().hex[:8]}@example.com")

        sent = await c.post(
            f"/daemon/runs/{run['run_id']}/events",
            json={
                "events": [
                    {
                        "seq": run["first_seq"],
                        "type": "tool.started",
                        "payload": {
                            "call": "t1",
                            "name": "bash",
                            "args": {"command": f"curl -H 'X-Token: {run['run_token']}' /v1/me"},
                        },
                    }
                ]
            },
            headers=auth(machine.token),
        )

        assert sent.status_code == 400, sent.text
        assert sent.json()["code"] == "credential_in_the_clear"
        assert run["run_token"] not in await _everything_written_about(run["run_id"])


async def test_the_whole_batch_goes_back_not_just_the_event_that_carried_it() -> None:
    """Ghi nửa hợp lệ để lại một lỗ ở con số không gì lấp được (FR-045) — cùng luật T098."""
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"batch-{uuid4().hex[:8]}@example.com")
        seq = run["first_seq"]

        sent = await c.post(
            f"/daemon/runs/{run['run_id']}/events",
            json={
                "events": [
                    {"seq": seq, "type": "assistant.message", "payload": {"text": "sạch sẽ"}},
                    {
                        "seq": seq + 1,
                        "type": "assistant.message",
                        "payload": {"text": f"và đây là {machine.token}"},
                    },
                ]
            },
            headers=auth(machine.token),
        )
        assert sent.status_code == 400, sent.text

        async with get_sessionmaker()() as session:
            written = (
                await session.execute(
                    select(RunEventModel.seq).where(
                        RunEventModel.run_id == UUID(run["run_id"]),
                        RunEventModel.seq >= seq,
                    )
                )
            ).scalars().all()
        assert written == [], "không nửa nào được ghi"


async def test_a_token_this_system_mints_is_one_this_guard_recognises() -> None:
    """Cửa nhận ra theo **hình dạng**, mà hình dạng ấy neo vào một con số ở chỗ khác.

    Sàn là 40 ký tự; `secrets.token_urlsafe(32)` ra 43. Ba ký tự dư, và ba ký tự ấy **không
    nhìn thấy được** từ chỗ đặt sàn — chúng nằm trong một tham số của `token_urlsafe` cách đó
    hai trăm dòng. Hạ entropy xuống 29 bytes là đuôi còn 39, và cửa lặng lẽ thôi đóng.

    Bài kiểm cửa ở trên **cũng** đỏ khi ấy, vì nó gài đúng token thật — nhưng nó đỏ thành câu
    *đợi 400, nhận 200*, tức là tên triệu chứng. Bài này đỏ thành tên nguyên nhân, và nó kiểm
    đúng tính chất cần giữ chứ không kiểm lại phép tính: **thứ hệ thống này đúc ra phải là thứ
    cửa của nó nhận ra**. Cả hai token đều lấy từ đường đúc thật, không dựng lại bằng tay.
    """
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"shape-{uuid4().hex[:8]}@example.com")

        minted = (
            ("token lượt chạy", run["run_token"], RUN_TOKEN_PREFIX),
            ("token máy", machine.token, MACHINE_TOKEN_PREFIX),
        )
        for what, token, prefix in minted:
            # Cắt đúng tiền tố, không tách theo `_`: bảng chữ url-safe **có** dấu gạch dưới,
            # nên tách theo nó là cắt vào giữa chính cái đuôi đang đo.
            tail = token.removeprefix(prefix)
            assert OUR_CREDENTIALS.fullmatch(token), (
                f"{what} vừa đúc ra không lọt lưới của chính cửa này: {len(tail)} ký tự đuôi, "
                f"sàn đang là {CREDENTIAL_TAIL_FLOOR}. Hạ sàn, hoặc đừng hạ entropy."
            )
            assert len(tail) > CREDENTIAL_TAIL_FLOOR, (
                f"{what} chỉ còn {len(tail)} ký tự đuôi — bằng đúng sàn thì không còn chỗ nào "
                "cho lần rút gọn tiếp theo, và lần ấy sẽ không có bài kiểm nào đỏ trước nó."
            )


async def test_a_name_that_merely_starts_like_a_token_is_left_alone() -> None:
    """Lưới hình dạng phải hẹp: một lô bị từ chối là một lô bị bỏ hẳn (T141).

    `armd_` là tiền tố ngắn, và một định danh dài trong mã nguồn agent đang đọc có thể bắt đầu
    bằng đúng thế. Neo vào **độ dài** của phần sau — `secrets.token_urlsafe(32)` ra 43 ký tự —
    là thứ tách một token thật khỏi một tên biến.
    """
    async with _client() as c:
        machine, run = await _a_run_in_hand(c, f"name-{uuid4().hex[:8]}@example.com")

        sent = await c.post(
            f"/daemon/runs/{run['run_id']}/events",
            json={
                "events": [
                    {
                        "seq": run["first_seq"],
                        "type": "tool.started",
                        "payload": {
                            "call": "t1",
                            "name": "read",
                            "args": {"path": "armd_configuration_manager.py"},
                        },
                    }
                ]
            },
            headers=auth(machine.token),
        )
        assert sent.status_code == 200, sent.text
