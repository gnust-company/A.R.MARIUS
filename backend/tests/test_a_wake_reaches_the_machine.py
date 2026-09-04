"""Gọi dậy một agent chạy trên máy người dùng thì việc đi xuống máy ấy (T048b).

Cho tới đợt này, con đường xuống máy đã dựng xong hết — cửa nhận việc, quãng chạy, cửa khép
— nhưng **không có lối lên đường**. Mọi lượt gọi dậy đều đi qua `adapter.execute`: gọi, đứng
đợi, rồi khép lượt chạy ngay tại chỗ. Đường xuống máy lộn ngược cả ba: đặt việc lên kệ rồi
buông, còn cái mốc bắt đầu, từng dòng agent nói, và cú khép đều đi vào từ phía máy. Nên mọi
lượt chạy thật tới được daemon chỉ vì bài kiểm **đặt thẳng lên kệ** — không lượt nào tới bằng
một cú gọi dậy.

Bốn điều được đo ở đây, và ba điều đầu là ba cách cùng một lỗi có thể xảy ra:

  * việc **tới được** kệ, và tới với đúng chỗ làm của agent (FR-009, FR-053);
  * mối giữ *(agent, đầu việc)* **không** được trả lại lúc việc rời đi — trả lại là mở đường
    cho một lượt chạy thứ hai về cùng một lượt nói (FR-050);
  * lượt chạy **không** bị khép ở đây: cái mốc bắt đầu và cú khép thuộc về máy (FR-040b);
  * và một cú giao việc **bị từ chối** thì lượt chạy khép lại ngay tại đây, vì không còn ai
    đến lấy nó nữa.

Đi qua app thật với container thật: cái kệ mà cửa daemon đọc đúng là cái bảng mà bên gọi dậy
ghi vào, và chỉ chạy thật mới đo được điều đó.
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from armarius.application.ports.workspace_trace import EVENT_RUN_STATE_CHANGED
from armarius.domain.entities.run import ACTIVE_RUN_STATUSES, RunStatus, WakeSource
from armarius.domain.entities.task import TaskStatus
from armarius.domain.entities.wakeup import PENDING_WAKEUP_STATUSES
from armarius.infrastructure.daemon.models import (
    AgentWorkplaceBindingModel,
    RunClaimModel,
)
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import RunModel, TaskModel, WakeupModel
from armarius.main import app
from tests.support.agents import invite_agent
from tests.support.machines import LinkedMachine, auth, link_machine
from tests.support.work import a_project, a_task

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class Woken:
    """One agent that works on a machine, one task of its own, and the wake it was sent."""

    def __init__(
        self, machine: LinkedMachine, marius_id: str, task_id: UUID, run_id: UUID
    ) -> None:
        self.machine = machine
        self.marius_id = marius_id
        self.task_id = task_id
        self.run_id = run_id

    @property
    def headers(self) -> dict[str, str]:
        return auth(self.machine.token)


async def _an_agent_on_a_machine(
    c: AsyncClient, email: str, *, hostname: str = "thinkpad"
) -> tuple[LinkedMachine, str]:
    """An agent placed at a real linked machine, whose turns are carried out there.

    Nothing here names a runtime. It used to: creating an agent gave everybody a runtime
    built for demos, and this helper had to move the agent afterwards before the road below
    could be measured at all. T048c put the answer where it comes from — the place declares
    who carries the work — so an agent created on a machine is already carried by it.
    """
    machine = await link_machine(c, email, hostname=hostname)
    agent = await invite_agent(
        c,
        machine.workspace_id,
        machine.headers,
        name=hostname,
        workplace_id=machine.workplace_id,
        adapter_type=None,
    )
    return machine, agent["id"]


async def _woken(c: AsyncClient, email: str, *, hostname: str = "thinkpad") -> Woken:
    """Wake a machine-borne agent on a task of its own, the way the product wakes one."""
    machine, marius_id = await _an_agent_on_a_machine(c, email, hostname=hostname)
    project_id = await a_project(machine.workspace_id)
    task_id = await a_task(project_id, assigned_to=marius_id, title="Dựng cổng đăng nhập")
    run_id = await app.state.container.wake_engine.enqueue(
        marius_id=UUID(marius_id),
        task_id=task_id,
        source=WakeSource.ASSIGNMENT,
    )
    assert run_id is not None, "lượt gọi dậy bị từ chối, mà đây là người được giao việc"
    await app.state.container.wake_engine.drain()
    return Woken(machine, marius_id, task_id, run_id)


async def _run(run_id: UUID) -> RunModel:
    async with get_sessionmaker()() as session:
        return await session.get(RunModel, run_id)


async def _shelf(run_id: UUID) -> RunClaimModel | None:
    async with get_sessionmaker()() as session:
        return await session.get(RunClaimModel, run_id)


async def _wakes(run_id: UUID) -> list[WakeupModel]:
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            select(WakeupModel).where(WakeupModel.run_id == run_id)
        )
        return list(rows.scalars())


def _announced(workspace_id: str) -> list[dict]:
    """Every run-lifecycle event on this workspace's channel, oldest first."""
    return [
        event.data
        for event in app.state.container.control_bus.backlog(f"ws:{workspace_id}")
        if event.type == EVENT_RUN_STATE_CHANGED
    ]


# ── the work gets there ───────────────────────────────────────────────────────────


async def test_a_wake_puts_the_work_on_the_shelf_of_the_machine_the_agent_works_on() -> None:
    """Việc đi tới **đúng cái kệ**, và chỗ làm ghi trên nó là chỗ agent được đặt vào.

    Không phải chuyện gọn gàng: cửa nhận việc lấy việc theo chỗ làm mà cái máy hỏi hộ, nên
    một hàng ghi sai chỗ làm là một hàng không máy nào lấy được — việc nằm đó im lặng.
    """
    async with _client() as c:
        woken = await _woken(c, "shelf@example.com")

        row = await _shelf(woken.run_id)
        assert row is not None, "lượt gọi dậy không đặt việc lên kệ nào cả"
        assert str(row.workplace_id) == woken.machine.workplace_id
        assert row.machine_id is None, "chưa máy nào nhận mà đã ghi tên máy vào"


async def test_the_run_is_left_queued_because_nothing_is_running_yet() -> None:
    """Nói *đang chạy* ở đây là lời nói dối duy nhất có sức phá.

    Cửa nhận việc lấy việc **theo trạng thái đang chờ**. Một lượt chạy bị đánh dấu đang chạy
    lúc mới giao đi là một lượt chạy không máy nào lấy được nữa — và cùng lúc, bảng công việc
    đọc nó là *đang có người làm* trong khi chưa ai làm gì.
    """
    async with _client() as c:
        woken = await _woken(c, "queued@example.com")

        run = await _run(woken.run_id)
        assert run.status == RunStatus.QUEUED.value, run.status
        assert run.started_at is None
        assert run.finished_at is None


async def test_the_pair_is_still_held_after_the_work_has_left() -> None:
    """Mối giữ *(agent, đầu việc)* **không** được trả lại lúc việc rời đi (FR-050).

    Đây là chỗ dễ sai nhất của cả đợt. Lối cũ trả mối giữ lại trong khối `finally` — đúng cho
    một lượt gọi-rồi-đợi, vì lúc ấy lượt chạy đã xong thật. Giữ nguyên khối ấy cho đường
    xuống máy thì mối giữ được trả về **đúng giây việc rời đi**, và bình luận tiếp theo mở
    một lượt chạy thứ hai về cùng một lượt nói: hai agent, một đầu việc, cùng một lúc.
    """
    async with _client() as c:
        woken = await _woken(c, "held@example.com")

        run = await _run(woken.run_id)
        assert RunStatus(run.status) in ACTIVE_RUN_STATUSES
        owed = await _wakes(woken.run_id)
        assert owed, "không có lời gọi dậy nào ghi cho lượt chạy này"
        assert any(w.status in {str(s) for s in PENDING_WAKEUP_STATUSES} for w in owed), (
            "lời gọi dậy đã bị đánh dấu xong trong khi lượt chạy còn chưa bắt đầu"
        )

        # Và bằng chứng hành vi, không phải bằng chứng trạng thái: một nguyên nhân mới gộp
        # vào đúng lượt chạy đang giữ mối, chứ không mở lượt thứ hai.
        again = await app.state.container.wake_engine.enqueue(
            marius_id=UUID(woken.marius_id),
            task_id=woken.task_id,
            source=WakeSource.COMMENT,
        )
        assert again == woken.run_id, "một lượt chạy thứ hai được mở cho cùng một mối giữ"


async def test_the_message_is_written_when_the_machine_takes_the_work() -> None:
    """Lời nhắn dựng lúc **đổi tay**, không dựng lúc đặt lên kệ (FR-011).

    Việc có thể nằm trên kệ hàng phút. Đầu việc thì nhận thêm bình luận và bị viết lại việc
    kế tiếp trong quãng ấy, nên một lời nhắn dựng sớm là lời nhắn kể về một đầu việc không ai
    còn chạm tới nữa.
    """
    async with _client() as c:
        woken = await _woken(c, "message@example.com")

        answered = await c.post(
            "/daemon/runs/claim",
            json={"workplace_ids": [woken.machine.workplace_id], "max": 1},
            headers=woken.headers,
        )
        assert answered.status_code == 200, answered.text
        taken = answered.json()["runs"]
        assert len(taken) == 1, taken
        assert taken[0]["run_id"] == str(woken.run_id)
        assert "Dựng cổng đăng nhập" in taken[0]["prompt"], taken[0]["prompt"]
        assert taken[0]["run_token"], "việc đi ra mà không có giấy tờ để gọi về"


async def test_nothing_books_a_follow_up_while_the_work_is_still_on_the_shelf() -> None:
    """Việc kế tiếp được quyết lúc lượt chạy **kết thúc**, mà nó chưa kết thúc.

    Chọn một đầu việc **bị chặn mà không ghi lý do**, vì đó đúng là ca mà chính sách nối tiếp
    có đặt ra một cú nhắc. Nếu khối kết-thúc vẫn chạy sau khi việc đã rời đi, cú nhắc ấy được
    đặt ra ngay lúc việc còn đang nằm trên kệ — nghĩa là hệ thống tự nhắc mình về một lượt nói
    chưa ai nói.
    """
    async with _client() as c:
        machine, marius_id = await _an_agent_on_a_machine(c, "shelved@example.com")
        project_id = await a_project(machine.workspace_id)
        task_id = await a_task(project_id, assigned_to=marius_id)
        async with get_sessionmaker()() as session:
            task = await session.get(TaskModel, task_id)
            task.status = TaskStatus.BLOCKED.value
            task.status_reason = None
            await session.commit()

        run_id = await app.state.container.wake_engine.enqueue(
            marius_id=UUID(marius_id), task_id=task_id, source=WakeSource.ASSIGNMENT
        )
        await app.state.container.wake_engine.drain()

        owed = await _wakes(run_id)
        assert len(owed) == 1, [(w.source, w.status) for w in owed]


# ── the machine says what happened ────────────────────────────────────────────────


async def test_a_run_that_begins_on_a_machine_says_so_on_the_screen() -> None:
    """Màn hình theo dõi một agent phải thấy lượt chạy **chuyển sang đang chạy** (FR-080).

    Lối gọi-rồi-đợi tự loan tin ấy vì nó chính là bên đổi trạng thái. Trên đường xuống máy,
    bên đổi trạng thái là cửa `start`, và trước đợt này cửa ấy không loan gì: cùng một lượt
    chạy, chạy trên máy người dùng, nằm ở *đang chờ* trên màn hình suốt cả lượt và chỉ nhảy
    một lần lúc khép.
    """
    async with _client() as c:
        woken = await _woken(c, "started@example.com")
        await c.post(
            "/daemon/runs/claim",
            json={"workplace_ids": [woken.machine.workplace_id], "max": 1},
            headers=woken.headers,
        )

        began = await c.post(
            f"/daemon/runs/{woken.run_id}/start",
            json={"session_handle": "sess-1"},
            headers=woken.headers,
        )
        assert began.status_code == 200, began.text

        run = await _run(woken.run_id)
        assert run.status == RunStatus.RUNNING.value
        said = [
            event
            for event in _announced(woken.machine.workspace_id)
            if event["run_id"] == str(woken.run_id)
        ]
        assert [event["status"] for event in said] == [
            str(RunStatus.QUEUED),
            str(RunStatus.RUNNING),
        ], said


async def test_the_turn_ends_where_the_machine_says_it_ends() -> None:
    """Cú khép đi vào từ phía máy, và nó khép **trọn vẹn**: mối giữ được trả, lời gọi xong."""
    async with _client() as c:
        woken = await _woken(c, "ended@example.com")
        await c.post(
            "/daemon/runs/claim",
            json={"workplace_ids": [woken.machine.workplace_id], "max": 1},
            headers=woken.headers,
        )
        await c.post(
            f"/daemon/runs/{woken.run_id}/start",
            json={"session_handle": "sess-1"},
            headers=woken.headers,
        )

        done = await c.post(
            f"/daemon/runs/{woken.run_id}/finish",
            json={"status": "completed", "session_handle": "sess-1"},
            headers=woken.headers,
        )
        assert done.status_code == 200, done.text
        await app.state.container.wake_engine.drain()

        run = await _run(woken.run_id)
        assert run.status == RunStatus.COMPLETED.value, run.status
        assert run.finished_at is not None
        owed = await _wakes(woken.run_id)
        assert all(
            w.status not in {str(s) for s in PENDING_WAKEUP_STATUSES} for w in owed
        ), "lượt chạy khép rồi mà lời gọi dậy vẫn còn ghi là đang nợ"


# ── the road that was refused ─────────────────────────────────────────────────────


async def test_an_agent_with_nowhere_left_to_work_ends_its_run_here() -> None:
    """Giao việc bị từ chối thì lượt chạy khép **ngay tại đây** — không ai đến lấy nó nữa.

    Buông một lượt chạy không ai nhận là kẹt đầu việc ấy vĩnh viễn: mối giữ còn nguyên, mà
    thứ đang giữ nó thì không tồn tại.
    """
    async with _client() as c:
        machine, marius_id = await _an_agent_on_a_machine(c, "nowhere@example.com")
        project_id = await a_project(machine.workspace_id)
        task_id = await a_task(project_id, assigned_to=marius_id)
        async with get_sessionmaker()() as session:
            await session.execute(
                delete(AgentWorkplaceBindingModel).where(
                    AgentWorkplaceBindingModel.marius_id == UUID(marius_id)
                )
            )
            await session.commit()

        run_id = await app.state.container.wake_engine.enqueue(
            marius_id=UUID(marius_id), task_id=task_id, source=WakeSource.ASSIGNMENT
        )
        await app.state.container.wake_engine.drain()

        run = await _run(run_id)
        assert RunStatus(run.status) not in ACTIVE_RUN_STATUSES, run.status
        assert run.error == "agent_has_no_workplace", run.error
        assert await _shelf(run_id) is None, "việc lên kệ dù không có chỗ làm nào để lên"


async def test_a_runtime_this_process_can_call_is_still_called() -> None:
    """Cùng một lượt gọi dậy, agent chạy trong tiến trình này vẫn đi lối cũ trọn vẹn.

    Đây là nửa còn lại của phép đo. Chỗ rẽ đọc **hợp đồng** của adapter, nên bằng chứng phải
    gồm cả hai phía: nếu chỉ đo phía kia thì một chỗ rẽ luôn-luôn-giao-đi cũng qua bài.
    """
    async with _client() as c:
        machine = await link_machine(c, "called@example.com", hostname="laptop")
        agent = await invite_agent(
            c,
            machine.workspace_id,
            machine.headers,
            name="laptop",
            workplace_id=machine.workplace_id,
        )
        project_id = await a_project(machine.workspace_id)
        task_id = await a_task(project_id, assigned_to=agent["id"])

        run_id = await app.state.container.wake_engine.enqueue(
            marius_id=UUID(agent["id"]),
            task_id=task_id,
            source=WakeSource.ASSIGNMENT,
        )
        for _ in range(400):
            run = await _run(run_id)
            if RunStatus(run.status) not in ACTIVE_RUN_STATUSES:
                break
            await asyncio.sleep(0.02)
        await app.state.container.wake_engine.drain()

        run = await _run(run_id)
        assert RunStatus(run.status) not in ACTIVE_RUN_STATUSES, run.status
        assert run.started_at is not None, "lượt chạy trong tiến trình này không có mốc bắt đầu"
        assert await _shelf(run_id) is None, "việc chạy tại đây mà vẫn bị đặt lên kệ"


async def test_a_run_nobody_opened_is_not_announced_as_started() -> None:
    """Cửa `start` của một lượt chạy không tồn tại không loan tin gì, và không nổ.

    Cùng một lối vào phục vụ cả cú gọi lại của một máy có gói tin trả lời bị rơi (FR-054b),
    nên nó phải chịu được một mã lượt chạy đã biến mất.
    """
    async with _client() as c:
        machine = await link_machine(c, "ghost@example.com", hostname="ghost")
        before = len(_announced(machine.workspace_id))

        await app.state.container.wake_engine.run_started(uuid4())

        assert len(_announced(machine.workspace_id)) == before
