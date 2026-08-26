"""Thông điệp gửi agent — server dựng, server ghi, ngay tại cú nhận việc (T056, T057).

Trước đợt này chỗ dựng thông điệp nằm trong vòng chạy của gateway: server gọi agent, và
trên đường gọi nó dựng câu chữ. Bỏ gateway thì đường ấy mất, mà thông điệp thì không —
nó phải đi xuống cùng gói việc, và nó phải được ghi lại ở chính chỗ nó được dựng.

Vì sao là *chỗ nó được dựng* chứ không phải chỗ nó được dùng: bên dựng đã cầm sẵn toàn văn.
Đợi máy gửi ngược về là biến một chuyện đã biết chắc thành một chuyện phải chờ xác nhận, và
đúng ca cần bản ghi nhất — máy nhận việc rồi im hẳn — lại là ca không có gì được ghi.

Hai luật nữa nằm ở phía server và không kiểm được ở phía máy: nội dung dựng từ chỉ dẫn của
agent (Điều V) và phải bằng tiếng Anh (Điều VII). Cho máy dựng là mang hai luật ấy xuống một
nơi không ai soi được.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from armarius.infrastructure.daemon.claim import PROMPT_EVENT
from armarius.infrastructure.daemon.models import RunClaimModel
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import RunEventModel, RunModel
from armarius.main import app
from tests.support.agents import invite_agent
from tests.support.machines import LinkedMachine, auth, link_machine
from tests.support.work import a_project, a_task, shelve

pytestmark = pytest.mark.anyio

INSTRUCTIONS = "You are the release engineer. You never merge without a green build."


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _agent_with_work(
    c: AsyncClient, box: LinkedMachine, *, next_action: str | None = None
) -> tuple[str, UUID]:
    """One agent on this machine, with one run waiting for it."""
    agent = await invite_agent(
        c,
        box.workspace_id,
        box.headers,
        name="Marin",
        workplace_id=box.workplace_id,
        instructions=INSTRUCTIONS,
    )
    project_id = await a_project(box.workspace_id)
    task_id = await a_task(project_id, assigned_to=agent["id"], next_action=next_action)
    return agent["id"], await shelve(marius_id=agent["id"], task_id=task_id)


async def _claim(c: AsyncClient, box: LinkedMachine) -> list[dict]:
    answered = await c.post(
        "/daemon/runs/claim",
        json={"workplace_ids": [box.workplace_id], "max": 4},
        headers=auth(box.token),
    )
    assert answered.status_code == 200, answered.text
    return answered.json()["runs"]


async def _recorded(run_id: UUID) -> list[RunEventModel]:
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            select(RunEventModel)
            .where(RunEventModel.run_id == run_id)
            .order_by(RunEventModel.seq)
        )
        return list(rows.scalars())


# ── the message goes down with the work ───────────────────────────────────────


async def test_the_work_comes_with_the_message_already_written() -> None:
    """Máy nhận việc là nhận luôn thông điệp — không phải đi hỏi thêm một vòng nữa."""
    async with _client() as c:
        box = await link_machine(c, "packet-message@armarius.dev")
        _, run_id = await _agent_with_work(c, box)

        taken = await _claim(c, box)

        assert [r["run_id"] for r in taken] == [str(run_id)]
        assert taken[0]["prompt"].strip(), "gói việc đi xuống mà không mang chữ nào"


async def test_the_message_is_built_from_the_agents_own_instructions() -> None:
    """Cách cư xử đến từ chỉ dẫn viết lúc tạo agent, không từ chỗ nào khác (Điều V)."""
    async with _client() as c:
        box = await link_machine(c, "packet-instructions@armarius.dev")
        await _agent_with_work(c, box)

        prompt = (await _claim(c, box))[0]["prompt"]

        assert INSTRUCTIONS in prompt


async def test_the_message_carries_the_task_and_what_was_left_to_do() -> None:
    """Đủ bối cảnh để làm việc: đầu việc, mô tả, và hành động kế tiếp đã lưu (FR-011)."""
    async with _client() as c:
        box = await link_machine(c, "packet-task@armarius.dev")
        await _agent_with_work(c, box, next_action="Cut the release branch")

        prompt = (await _claim(c, box))[0]["prompt"]

        assert "Ship the thing" in prompt
        assert "Whatever the patron asked for." in prompt
        assert "Cut the release branch" in prompt


async def test_the_message_does_not_point_at_a_credential_file() -> None:
    """Đường này trao token cho chính tiến trình, nên không có tệp nào để trỏ tới (FR-014c).

    Trỏ vào một tệp không tồn tại trên máy ấy không phải là thừa một dòng — nó là một lượt
    đọc hỏng, rồi một agent bắt đầu bằng cách không tin gói tin nó vừa nhận.
    """
    async with _client() as c:
        box = await link_machine(c, "packet-no-footer@armarius.dev")
        await _agent_with_work(c, box)

        prompt = (await _claim(c, box))[0]["prompt"]

        assert ".armarius/" not in prompt
        assert "ARMARIUS HINT" not in prompt


# ── and it is written down here, not sent back ────────────────────────────────


async def test_the_whole_message_is_in_the_record_the_moment_it_is_handed_over() -> None:
    """Toàn văn nằm trong nhật ký ngay sau cú nhận việc, không đợi máy báo về (FR-012a)."""
    async with _client() as c:
        box = await link_machine(c, "packet-recorded@armarius.dev")
        _, run_id = await _agent_with_work(c, box)

        prompt = (await _claim(c, box))[0]["prompt"]

        events = await _recorded(run_id)
        assert [e.type for e in events] == [PROMPT_EVENT]
        assert events[0].payload["prompt"] == prompt, "bản ghi khác bản đã gửi đi"
        assert events[0].original_byte_size == len(prompt.encode("utf-8"))


async def test_nothing_is_recorded_for_work_nobody_has_taken() -> None:
    """Đặt việc lên kệ chưa phải là nói gì với ai — bản ghi sinh ra lúc trao tay."""
    async with _client() as c:
        box = await link_machine(c, "packet-untaken@armarius.dev")
        _, run_id = await _agent_with_work(c, box)

        assert await _recorded(run_id) == []


async def test_two_runs_each_get_their_own_record() -> None:
    """Hai lượt chạy là hai thông điệp; không lượt nào ghi đè lượt nào (FR-045)."""
    async with _client() as c:
        box = await link_machine(c, "packet-two-runs@armarius.dev")
        agent = await invite_agent(
            c,
            box.workspace_id,
            box.headers,
            name="Marin",
            workplace_id=box.workplace_id,
            instructions=INSTRUCTIONS,
        )
        project_id = await a_project(box.workspace_id)
        first = await a_task(project_id, assigned_to=agent["id"], title="First job")
        second = await a_task(project_id, assigned_to=agent["id"], title="Second job")
        run_a = await shelve(marius_id=agent["id"], task_id=first)
        run_b = await shelve(marius_id=agent["id"], task_id=second)

        await _ceiling(box.machine_id, 4)
        taken = await _claim(c, box)

        assert {r["run_id"] for r in taken} == {str(run_a), str(run_b)}
        by_run = {r["run_id"]: r["prompt"] for r in taken}
        assert "First job" in by_run[str(run_a)]
        assert "Second job" in by_run[str(run_b)]
        for run_id in (run_a, run_b):
            events = await _recorded(run_id)
            assert len(events) == 1 and events[0].seq == 1


# ── a run nobody can describe is not handed over ──────────────────────────────


async def test_work_that_cannot_be_described_goes_back_on_the_shelf() -> None:
    """Không dựng nổi thông điệp thì trả việc về ngay, không trao một gói rỗng.

    Trao đi thì máy ôm một chỗ trống cho tới lúc hết hạn giữ, rồi trả lại đúng thứ nó vừa
    nhận. Trả ngay thì chỗ ấy còn dùng được cho việc khác, và đầu việc này chờ đúng thứ nó
    đang thiếu.
    """
    async with _client() as c:
        box = await link_machine(c, "packet-undescribable@armarius.dev")
        _, run_id = await _agent_with_work(c, box)
        # The agent this run belongs to is gone: nothing left to build a message out of.
        async with get_sessionmaker()() as session:
            await session.execute(
                RunModel.__table__.update()
                .where(RunModel.id == run_id)
                .values(marius_id=None)
            )
            await session.commit()

        assert await _claim(c, box) == []

        async with get_sessionmaker()() as session:
            claim = await session.get(RunClaimModel, run_id)
            assert claim is not None
            assert claim.machine_id is None, "việc vẫn bị giữ dù không trao được"
            assert claim.run_token_hash is None, "token của lượt chạy chưa bị thu hồi"


async def _ceiling(machine_id: UUID, allowed: int) -> None:
    from armarius.infrastructure.daemon.models import MachineModel

    async with get_sessionmaker()() as session:
        await session.execute(
            MachineModel.__table__.update()
            .where(MachineModel.id == machine_id)
            .values(max_concurrent=allowed)
        )
        await session.commit()
