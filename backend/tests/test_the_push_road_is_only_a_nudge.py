"""Đường đẩy — tin xuống máy chỉ là một cái vẫy tay (T053, FR-055, FR-055a, FR-055b).

Máy hỏi theo nhịp là **đường dự phòng**, không phải đường chính. Đường chính là server nói
*có việc, đi hỏi đi* ngay lúc có việc, để một đầu việc không phải nằm chờ hết một nhịp poll.

Nhưng chỗ dễ hỏng nằm ở chính chữ "nói": nếu tin ấy mang theo việc, hoặc tệ hơn, là **lệnh
chạy**, thì hai tin tới cùng lúc đẻ ra hai lượt chạy — và toàn bộ công sức dựng cửa nhận
việc một-lần ở T045 đổ sông. Nên tin này cố tình rỗng nghĩa: nó chỉ nói *đi hỏi đi*, còn
hỏi thì vẫn qua đúng cái cửa cũ, nơi lượt hỏi thừa về tay không.

Ba thứ tệp này giữ, và cả ba đều là thứ dễ mất khi ai đó "cải tiến" cho tiện:

* tin không mang việc — chỉ nói chỗ làm nào, không mã lượt chạy, không token;
* không phát lại — một cái vẫy tay chỉ đúng vào lúc vẫy, phát lại chồng cũ là bắt máy đi
  hỏi những lượt đã xong từ đời nào;
* giữ đường này mở **không** phải là dấu hiệu agent còn sống (FR-055b).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from armarius.application.ports.adapter import ExecContext
from armarius.domain.entities.project import ProjectStatus
from armarius.domain.entities.run import RunStatus
from armarius.domain.entities.task import TaskStatus
from armarius.infrastructure.daemon.models import MachineModel
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import ProjectModel, RunModel, TaskModel
from armarius.main import app
from armarius.shared.clock import utcnow
from tests.support.agents import invite_agent
from tests.support.machines import LinkedMachine, auth, link_machine

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


class Road:
    """What came down the push road, and a way to wait for the first of it."""

    def __init__(self) -> None:
        self.frames: list[dict] = []
        self._arrived = asyncio.Event()

    def note(self, frame: dict) -> None:
        self.frames.append(frame)
        self._arrived.set()

    async def first(self) -> dict:
        """The first frame, or a failure that says the road stayed silent."""
        try:
            async with asyncio.timeout(5):
                await self._arrived.wait()
        except TimeoutError:
            raise AssertionError("không có tin nào xuống đường đẩy") from None
        return self.frames[0]


@asynccontextmanager
async def _listening(c: AsyncClient, box: LinkedMachine) -> AsyncIterator[Road]:
    """Hold the push road open and collect whatever comes down it.

    Driven straight against the ASGI app rather than through the test client, and that is
    forced rather than chosen: the client's in-process transport waits for the application
    to *finish* before it hands back a response, and a stream that never finishes is exactly
    what is being tested here. Everything above the transport is still the real thing — the
    route, the token check, the bus.
    """
    road = Road()
    buffer = ""
    current: dict[str, str] = {}
    started = asyncio.Event()
    stop = asyncio.Event()
    status: list[int] = []
    headers: list[tuple[bytes, bytes]] = []

    async def receive() -> dict[str, object]:
        await stop.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        nonlocal buffer, current
        if message["type"] == "http.response.start":
            status.append(int(message["status"]))
            headers.extend(message.get("headers", []))
            started.set()
            return
        buffer += message.get("body", b"").decode()
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.rstrip("\r")
            if line == "":
                if "event" in current:
                    road.note(current)
                current = {}
                continue
            for key in ("event", "data", "id"):
                if line.startswith(f"{key}:"):
                    current[key] = line[len(key) + 1 :].strip()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.1"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/daemon/events",
        "raw_path": b"/daemon/events",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"test"),
            (b"accept", b"text/event-stream"),
            (b"authorization", f"Bearer {box.token}".encode()),
        ],
        "server": ("test", 80),
        "client": ("test", 1234),
    }
    task = asyncio.create_task(app(scope, receive, send))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        assert status == [200], status
        kinds = dict(headers)
        assert kinds[b"content-type"].startswith(b"text/event-stream"), kinds
        # The response has begun, which means the route ran; its generator attaches to the
        # bus on the next turn of the scheduler.
        await asyncio.sleep(0.05)
        yield road
    finally:
        stop.set()
        try:
            await asyncio.wait_for(task, timeout=5)
        except (TimeoutError, asyncio.CancelledError):
            task.cancel()


async def _offer(box: LinkedMachine, *, agent_id: str) -> UUID:
    """Put one run on the shelf the way the system does — through the adapter (FR-053).

    With a real task behind it, because the door now hands the agent its message as well as
    the work, and it will not hand over a run it has nothing to say about (FR-011).
    """
    run_id = uuid4()
    project_id, task_id = uuid4(), uuid4()
    async with get_sessionmaker()() as session:
        session.add(
            ProjectModel(
                id=project_id,
                workspace_id=UUID(box.workspace_id),
                name="Apollo",
                slug=f"apollo-{project_id.hex[:6]}",
                key=project_id.hex[:6].upper(),
                status=ProjectStatus.OPERATING.value,
                created_at=utcnow(),
            )
        )
        session.add(
            TaskModel(
                id=task_id,
                project_id=project_id,
                title="Ship the thing",
                status=TaskStatus.TODO.value,
                assigned_marius_id=UUID(agent_id),
                created_at=utcnow(),
            )
        )
        session.add(
            RunModel(
                id=run_id,
                marius_id=UUID(agent_id),
                task_id=task_id,
                adapter_type="daemon",
                status=RunStatus.QUEUED.value,
                created_at=utcnow(),
            )
        )
        await session.commit()
    adapter = app.state.container.registry.get("daemon")
    await adapter.dispatch(
        ExecContext(
            prompt="",
            adapter_config={},
            marius_id=UUID(agent_id),
            task_id=task_id,
            run_id=run_id,
        )
    )
    return run_id


# ── the road carries a signal ─────────────────────────────────────────────────


async def test_shelving_work_nudges_the_machine_that_can_take_it() -> None:
    """Việc vừa lên kệ thì máy giữ chỗ làm ấy được vẫy ngay, không đợi hết nhịp poll."""
    async with _client() as c:
        box = await link_machine(c, "push-nudge@armarius.dev")
        agent = await invite_agent(
            c, box.workspace_id, box.headers, name="Marin",
            workplace_id=box.workplace_id,
        )
        async with _listening(c, box) as road:
            await _offer(box, agent_id=agent["id"])
            first = await road.first()

    assert first["event"] == "pending_work"
    assert json.loads(first["data"]) == {"workplace_id": box.workplace_id}


async def test_the_nudge_carries_no_work_and_no_token() -> None:
    """Tin chỉ nói *đi hỏi đi*.

    Mang việc theo là biến cái vẫy tay thành lệnh chạy, và hai tin tới cùng lúc thành hai
    lượt chạy — đúng cái cửa nhận việc một-lần dựng ra để chặn (FR-055a).
    """
    async with _client() as c:
        box = await link_machine(c, "push-empty@armarius.dev")
        agent = await invite_agent(
            c, box.workspace_id, box.headers, name="Marin",
            workplace_id=box.workplace_id,
        )
        async with _listening(c, box) as road:
            run_id = await _offer(box, agent_id=agent["id"])
            first = await road.first()

    payload = json.loads(first["data"])
    assert set(payload) == {"workplace_id"}, payload
    assert str(run_id) not in first["data"], "tin đẩy mang theo mã lượt chạy"
    assert "token" not in first["data"], "tin đẩy mang theo token"


async def test_one_machines_work_is_never_announced_to_another() -> None:
    """Vẫy nhầm máy là bắt một máy đi hỏi thứ nó không bao giờ được đưa."""
    async with _client() as c:
        mine = await link_machine(c, "push-mine@armarius.dev", hostname="mine")
        theirs = await link_machine(c, "push-theirs@armarius.dev", hostname="theirs")
        agent = await invite_agent(
            c, mine.workspace_id, mine.headers, name="Marin",
            workplace_id=mine.workplace_id,
        )
        async with _listening(c, theirs) as next_door:
            async with _listening(c, mine) as here:
                await _offer(mine, agent_id=agent["id"])
                await here.first()
                # Give a wrongly-addressed nudge every chance to show up.
                await asyncio.sleep(0.2)
                assert next_door.frames == [], next_door.frames


async def test_a_nudge_sent_before_anyone_listened_is_not_replayed() -> None:
    """Cái vẫy tay chỉ đúng vào lúc vẫy.

    Mọi luồng khác trong hệ thống phát lại phần khách bỏ lỡ, vì chúng mang tin tức và một
    lỗ hổng trong tin tức là một lỗ hổng trong hồ sơ. Đường này không mang tin tức: máy nối
    lại là đã đi hỏi rồi, nên phát lại chồng cũ chỉ đẻ ra những lượt hỏi về tay không.
    """
    async with _client() as c:
        box = await link_machine(c, "push-noreplay@armarius.dev")
        agent = await invite_agent(
            c, box.workspace_id, box.headers, name="Marin",
            workplace_id=box.workplace_id,
        )
        await _offer(box, agent_id=agent["id"])  # nobody is holding the road open yet

        async with _listening(c, box) as road:
            await asyncio.sleep(0.3)
            assert road.frames == [], road.frames


# ── what the road must not become ─────────────────────────────────────────────


async def test_holding_the_road_open_is_not_a_sign_of_life(monkeypatch) -> None:
    """Giữ đường mở chứng minh **liên lạc được tới máy**, không chứng minh agent chạy được.

    Trộn hai thứ này thì máy bật mà CLI đã bị gỡ vẫn trông sống mãi (FR-055b).
    """
    async with _client() as c:
        box = await link_machine(c, "push-liveness@armarius.dev")
        async with get_sessionmaker()() as session:
            before = (
                await session.execute(
                    select(MachineModel.last_heartbeat_at).where(
                        MachineModel.id == box.machine_id
                    )
                )
            ).scalar_one()

        async with _listening(c, box):
            await asyncio.sleep(0.2)

        async with get_sessionmaker()() as session:
            after = (
                await session.execute(
                    select(MachineModel.last_heartbeat_at).where(
                        MachineModel.id == box.machine_id
                    )
                )
            ).scalar_one()
    assert after == before, "nối vào đường đẩy đã bị tính thành một nhịp tim"


async def test_the_road_is_shut_to_anyone_without_a_machine_token() -> None:
    async with _client() as c:
        anonymous = await c.get("/daemon/events")
        assert anonymous.status_code == 401, anonymous.text
        wrong = await c.get("/daemon/events", headers=auth("armr_machine_nope"))
        assert wrong.status_code == 401, wrong.text


async def test_a_push_road_that_is_broken_does_not_lose_the_work(monkeypatch) -> None:
    """Push hỏng thì việc vẫn nằm trên kệ.

    Đây là cả lý do đường poll tồn tại. Để một cú vẫy tay hỏng ném ngược lên đường đặt việc
    là biến một khởi động chậm vài giây thành một lượt chạy mất hẳn (FR-055d).
    """
    async with _client() as c:
        box = await link_machine(c, "push-broken@armarius.dev")
        agent = await invite_agent(
            c, box.workspace_id, box.headers, name="Marin",
            workplace_id=box.workplace_id,
        )

        async def explode(*args: object, **kwargs: object) -> int:
            raise RuntimeError("the push road is down")

        monkeypatch.setattr(app.state.container.control_bus, "publish", explode)
        run_id = await _offer(box, agent_id=agent["id"])
        monkeypatch.undo()

        taken = await c.post(
            "/daemon/runs/claim",
            json={"workplace_ids": [box.workplace_id], "max": 4},
            headers=auth(box.token),
        )
    assert taken.status_code == 200, taken.text
    assert [r["run_id"] for r in taken.json()["runs"]] == [str(run_id)]
