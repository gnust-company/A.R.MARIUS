"""Ranh giới của một cuộc trò chuyện là **đầu việc** (T114, SC-006, FR-023, FR-024).

Handle của phiên nằm trên máy: nó là chữ CLI tự đặt cho mạch trò chuyện, và daemon ghi nó cạnh
thư mục làm việc mà mạch ấy gắn vào (FR-010a). Bài kiểm bên Go giữ phần đó.

Ở đây là câu hỏi khác: **server có ghi lại không**. Một lời hứa về đĩa của một cái máy là lời hứa
không ai kiểm được — máy tắt, máy bị dựng lại, hoặc đơn giản là nói sai. Nên mỗi lần một lượt chạy
báo nó đang nối tiếp mạch nào, server ghi xuống, vào **đúng một hàng** khoá theo (agent, adapter,
đầu việc). Hàng ấy chính là điều khoản: FR-024 nói hai đầu việc là hai mạch kể cả cùng một agent,
và cái khoá ba phần này là chỗ lời hứa ấy thôi là lời hứa.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import RunModel, SessionModel
from armarius.main import app
from tests.support.agents import invite_agent
from tests.support.machines import auth, link_machine
from tests.support.work import a_project, a_task, shelve

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _take_one(c: AsyncClient, machine) -> dict:
    """Xin đúng một lượt việc và trả về nó."""
    answered = await c.post(
        "/daemon/runs/claim",
        json={"workplace_ids": [machine.workplace_id], "max": 1},
        headers=auth(machine.token),
    )
    assert answered.status_code == 200, answered.text
    runs = answered.json()["runs"]
    assert len(runs) == 1, f"xin một lượt việc, nhận về {len(runs)}"
    return runs[0]


async def _say_it_started(c: AsyncClient, machine, run_id: str, handle: str) -> None:
    started = await c.post(
        f"/daemon/runs/{run_id}/start",
        json={"session_handle": handle},
        headers=auth(machine.token),
    )
    assert started.status_code == 200, started.text


async def _sessions_of(marius_id: str) -> list[SessionModel]:
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            select(SessionModel).where(SessionModel.marius_id == UUID(marius_id))
        )
        return list(rows.scalars().all())


async def _a_machine_with_an_agent(c: AsyncClient, email: str) -> tuple[object, dict, str]:
    machine = await link_machine(c, email, hostname="box")
    agent = await invite_agent(
        c,
        machine.workspace_id,
        machine.headers,
        name=f"Marin{uuid4().hex[:6]}",
        workplace_id=machine.workplace_id,
    )
    project_id = await a_project(machine.workspace_id)
    return machine, agent, project_id


# ── cùng một đầu việc ────────────────────────────────────────────────────────


async def test_two_wakes_on_one_task_are_one_conversation() -> None:
    """SC-006: lần gọi dậy sau nối lại mạch cũ, và server ghi đúng một hàng cho mạch ấy."""
    async with _client() as c:
        machine, agent, project_id = await _a_machine_with_an_agent(
            c, f"same-{uuid4().hex[:8]}@example.com"
        )
        task_id = await a_task(project_id, assigned_to=agent["id"])

        await shelve(marius_id=agent["id"], task_id=task_id)
        first = await _take_one(c, machine)
        # Lượt đầu chưa nối tiếp gì cả — nó **mở** mạch, và tên mạch chỉ có sau khi CLI nói ra.
        await _say_it_started(c, machine, first["run_id"], "")

        await c.post(
            f"/daemon/runs/{first['run_id']}/finish",
            json={"status": "completed"},
            headers=auth(machine.token),
        )
        await shelve(marius_id=agent["id"], task_id=task_id)
        second = await _take_one(c, machine)
        await _say_it_started(c, machine, second["run_id"], "sess-abc")

    rows = await _sessions_of(agent["id"])
    assert len(rows) == 1, "một đầu việc phải có đúng một mạch trò chuyện"
    assert rows[0].session_display_id == "sess-abc"
    assert UUID(str(rows[0].task_id)) == UUID(str(task_id))


async def test_the_run_itself_says_which_conversation_it_took_up() -> None:
    """Đọc một lượt chạy là biết nó nối tiếp cái gì, không phải đi hỏi bảng khác."""
    async with _client() as c:
        machine, agent, project_id = await _a_machine_with_an_agent(
            c, f"onrun-{uuid4().hex[:8]}@example.com"
        )
        task_id = await a_task(project_id, assigned_to=agent["id"])
        await shelve(marius_id=agent["id"], task_id=task_id)
        run = await _take_one(c, machine)
        await _say_it_started(c, machine, run["run_id"], "sess-onrun")

    async with get_sessionmaker()() as session:
        row = await session.get(RunModel, UUID(run["run_id"]))
    assert row is not None
    assert row.session_id_before == "sess-onrun"


# ── hai đầu việc ─────────────────────────────────────────────────────────────


async def test_two_tasks_are_two_conversations_for_the_same_agent() -> None:
    """FR-024: cùng một agent, cùng một chỗ làm, hai đầu việc — hai mạch."""
    async with _client() as c:
        machine, agent, project_id = await _a_machine_with_an_agent(
            c, f"two-{uuid4().hex[:8]}@example.com"
        )
        handles = {}
        for handle in ("sess-one", "sess-two"):
            task_id = await a_task(project_id, assigned_to=agent["id"])
            await shelve(marius_id=agent["id"], task_id=task_id)
            run = await _take_one(c, machine)
            await _say_it_started(c, machine, run["run_id"], handle)
            await c.post(
                f"/daemon/runs/{run['run_id']}/finish",
                json={"status": "completed"},
                headers=auth(machine.token),
            )
            handles[str(task_id)] = handle

    rows = await _sessions_of(agent["id"])
    assert len(rows) == 2, "hai đầu việc phải có hai mạch, không phải một mạch bị ghi đè"
    assert {str(r.task_id): r.session_display_id for r in rows} == handles


# ── lượt chạy mở mạch mới ────────────────────────────────────────────────────


async def test_a_run_that_opened_a_new_conversation_does_not_erase_the_old_one() -> None:
    """Handle rỗng nghĩa là *lượt này không nối tiếp gì*, không phải *đầu việc này hết mạch*.

    Ghi đè bằng chỗ trống là xoá đúng cái mạch mà lần gọi dậy sau đang định tìm — và một lượt
    chạy hỏng trước khi CLI kịp đặt tên cho mạch cũng gửi lên đúng chỗ trống ấy.
    """
    async with _client() as c:
        machine, agent, project_id = await _a_machine_with_an_agent(
            c, f"keep-{uuid4().hex[:8]}@example.com"
        )
        task_id = await a_task(project_id, assigned_to=agent["id"])

        await shelve(marius_id=agent["id"], task_id=task_id)
        first = await _take_one(c, machine)
        await _say_it_started(c, machine, first["run_id"], "sess-kept")
        await c.post(
            f"/daemon/runs/{first['run_id']}/finish",
            json={"status": "completed"},
            headers=auth(machine.token),
        )

        await shelve(marius_id=agent["id"], task_id=task_id)
        second = await _take_one(c, machine)
        await _say_it_started(c, machine, second["run_id"], "")

    rows = await _sessions_of(agent["id"])
    assert len(rows) == 1
    assert rows[0].session_display_id == "sess-kept", "một lượt chạy không đặt tên đã xoá mạch cũ"


# ── mạch lượt chạy **kết thúc** với nó ───────────────────────────────────────


async def test_the_conversation_the_run_ended_on_is_the_one_written_down() -> None:
    """Lượt chạy mở mạch mới thì tên mạch chỉ có ở lúc **xong**, không có ở lúc bắt đầu.

    Một lượt chạy được đưa handle mà CLI không nạp được sẽ mở mạch mới rồi chạy tiếp trên mạch
    ấy (FR-025) — nên handle báo lúc bắt đầu và handle báo lúc xong là **hai** sự việc, và cái
    lần gọi dậy sau dùng được là cái thứ hai.
    """
    async with _client() as c:
        machine, agent, project_id = await _a_machine_with_an_agent(
            c, f"ended-{uuid4().hex[:8]}@example.com"
        )
        task_id = await a_task(project_id, assigned_to=agent["id"])
        await shelve(marius_id=agent["id"], task_id=task_id)
        run = await _take_one(c, machine)
        await _say_it_started(c, machine, run["run_id"], "")

        done = await c.post(
            f"/daemon/runs/{run['run_id']}/finish",
            json={"status": "completed", "session_handle": "sess-opened-mid-run"},
            headers=auth(machine.token),
        )
        assert done.status_code == 200, done.text

    rows = await _sessions_of(agent["id"])
    assert len(rows) == 1, "lượt chạy mở mạch mới mà server không ghi lại gì"
    assert rows[0].session_display_id == "sess-opened-mid-run"

    async with get_sessionmaker()() as session:
        row = await session.get(RunModel, UUID(run["run_id"]))
    assert row is not None
    assert row.session_id_after == "sess-opened-mid-run"
    assert row.session_id_before is None, "lượt này không nối tiếp gì cả"


async def test_a_run_that_ends_without_naming_a_conversation_leaves_the_old_one_alone() -> None:
    """Cùng luật ấy ở cửa `/finish`, và đây mới là cửa hay gặp ca này.

    Một lượt chạy hỏng trước khi CLI kịp đặt tên cho mạch sẽ đóng lại với handle rỗng. Nếu chỗ
    trống ấy ghi đè, thì một lượt chạy hỏng vừa làm mất luôn mạch mà lần gọi dậy sau đang định
    nối lại — hỏng một lượt thành hỏng cả cuộc trò chuyện.
    """
    async with _client() as c:
        machine, agent, project_id = await _a_machine_with_an_agent(
            c, f"failed-{uuid4().hex[:8]}@example.com"
        )
        task_id = await a_task(project_id, assigned_to=agent["id"])

        await shelve(marius_id=agent["id"], task_id=task_id)
        first = await _take_one(c, machine)
        await _say_it_started(c, machine, first["run_id"], "")
        await c.post(
            f"/daemon/runs/{first['run_id']}/finish",
            json={"status": "completed", "session_handle": "sess-still-good"},
            headers=auth(machine.token),
        )

        await shelve(marius_id=agent["id"], task_id=task_id)
        second = await _take_one(c, machine)
        await _say_it_started(c, machine, second["run_id"], "sess-still-good")
        done = await c.post(
            f"/daemon/runs/{second['run_id']}/finish",
            json={"status": "failed", "error": "CLI chết trước khi nói được gì"},
            headers=auth(machine.token),
        )
        assert done.status_code == 200, done.text

    rows = await _sessions_of(agent["id"])
    assert len(rows) == 1
    assert rows[0].session_display_id == "sess-still-good", "một lượt chạy hỏng đã xoá mạch cũ"
