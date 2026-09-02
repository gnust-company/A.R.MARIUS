"""Daemon chết giữa lượt chạy thì đi đúng con đường cũ (T126, FR-006b, FR-028, FR-029, FR-029a).

Đây là bài **chứng minh**, và thứ nó chứng minh là một điều đã cố ý **không viết mã mới**.
Bốn điều khoản trên nói cùng một câu theo bốn cách: mô hình daemon không được có luồng hỏng
riêng. Một luồng riêng thì lúc viết trông vô hại — nó chỉ là *một* nhánh nữa — nhưng nó
nhân đôi mọi thứ đứng sau: hai chỗ tuyên offline, hai kiểu chữ ghi vào sổ, hai đường leo
thang, và hai chỗ để sai khác nhau.

Nên bài này dựng một cái chết thật của máy rồi hỏi bốn câu, và câu nào cũng là câu hỏi
*con đường cũ có chạy không*, chứ không phải *có đường mới nào không*:

  1. Máy tắt có được tuyên offline **nhanh hơn** thứ gì khác không (FR-029). Không: nó đi
     hết đúng cái thang dò đang có, và khoảng ân hạn ấy đo được thành giây.
  2. Máy sống lại trong khoảng ân hạn thì đầu việc mất gì (đối chứng). Không mất gì.
  3. Hết ân hạn thì đầu việc rơi vào **đúng** luồng offline đang có (FR-006b, FR-028) —
     đậu lại, có lý do nói ra, và vẫn còn một động cơ đẩy sống.
  4. Lượt chạy máy chết đang giữ có quay lại kệ không (FR-029a), và cái token của nó có
     hết mở được cửa nào không.

Không chỗ nào ở đây gọi tới một hàm sinh ra vì daemon. Đồng hồ được quay tay chứ không ngồi
đợi — bài kiểm ngồi đợi hai phút rưỡi là bài kiểm bị bỏ qua.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from armarius.domain.entities.marius import Liveness
from armarius.domain.entities.run import RunStatus
from armarius.domain.entities.task import TaskStatus
from armarius.domain.services.liveness_fsm import LivenessConfig
from armarius.infrastructure.daemon.models import MachineModel
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import RunModel, TaskModel
from armarius.main import app
from armarius.shared.clock import utcnow
from tests.support.agents import invite_agent
from tests.support.machines import auth, link_machine
from tests.support.work import a_project, a_task, shelve

pytestmark = pytest.mark.anyio

CFG = LivenessConfig()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@dataclass
class Scene:
    """One machine, one agent on it, one task it is holding, one run on that task."""

    c: AsyncClient
    machine_id: UUID
    marius_id: UUID
    task_id: UUID
    run_id: UUID
    #: What the agent speaks with — minted for this run and dying with it (FR-014b).
    run_token: str
    #: What the daemon speaks with. A different credential for a different party.
    machine_token: str
    started_at: datetime


async def _a_machine_holding_work(c: AsyncClient) -> Scene:
    """The whole ordinary situation, built through the doors that really build it."""
    linked = await link_machine(c, "patron@acme.dev")
    agent = await invite_agent(
        c,
        linked.workspace_id,
        linked.headers,
        name="Marin",
        adapter_type="daemon",
        workplace_id=linked.workplace_id,
    )
    marius_id = UUID(agent["id"])
    project_id = await a_project(linked.workspace_id)
    task_id = await a_task(project_id, assigned_to=marius_id)
    await _set_task(task_id, status=TaskStatus.IN_PROGRESS)
    run_id = await shelve(marius_id=marius_id, task_id=task_id)

    # The machine takes the work, exactly as a live daemon does. From here on it is holding
    # a run — which is what makes its death a death *mid-run* rather than a quiet machine.
    claimed = await c.post(
        "/daemon/runs/claim",
        json={"workplace_ids": [linked.workplace_id], "free_slots": 1},
        headers=auth(linked.token),
    )
    assert claimed.status_code == 200, claimed.text
    granted = claimed.json()["runs"]
    assert len(granted) == 1, f"the machine was handed {len(granted)} runs, wanted 1"

    now = utcnow()
    await app.state.container.liveness.record_signal(marius_id, now)
    return Scene(
        c=c,
        machine_id=linked.machine_id,
        marius_id=marius_id,
        task_id=task_id,
        run_id=run_id,
        run_token=granted[0]["run_token"],
        machine_token=linked.token,
        started_at=now,
    )


async def _the_daemon_dies(machine_id: UUID, *, ago: timedelta = timedelta(hours=1)) -> None:
    """Stop the beating. That is the whole of what dying looks like from here.

    Nothing is deleted and no flag is set: the machine simply stops saying anything, which
    is what a killed process, a closed lid and a cut cable all look like from this side.
    """
    async with get_sessionmaker()() as session:
        machine = await session.get(MachineModel, machine_id)
        assert machine is not None
        machine.last_heartbeat_at = utcnow() - ago
        await session.commit()


async def _the_daemon_comes_back(machine_id: UUID) -> None:
    async with get_sessionmaker()() as session:
        machine = await session.get(MachineModel, machine_id)
        assert machine is not None
        machine.last_heartbeat_at = utcnow()
        await session.commit()


async def _set_task(task_id: UUID, *, status: TaskStatus) -> None:
    async with get_sessionmaker()() as session:
        task = await session.get(TaskModel, task_id)
        assert task is not None
        task.status = status.value
        await session.commit()


async def _task(task_id: UUID) -> TaskModel:
    async with get_sessionmaker()() as session:
        task = await session.get(TaskModel, task_id)
        assert task is not None
        return task


async def _liveness(marius_id: UUID) -> Liveness:
    async with app.state.container.uow_factory() as uow:
        marius = await uow.mariuses.get(marius_id)
    assert marius is not None
    return marius.liveness


async def _walk_the_ladder(scene: Scene, *, stop_after: int | None = None) -> timedelta:
    """Tick the clock the way the watchdog would, and report how long it took to fall.

    Returns the time from the last signal to the tick that declared the agent offline —
    which is the grace period FR-029 asks for, measured rather than asserted from a
    constant.
    """
    engine = app.state.container.liveness
    at = scene.started_at + CFG.idle_timeout + timedelta(seconds=1)
    for probe in range(1, (stop_after or CFG.max_probe_attempts) + 1):
        await engine.advance(scene.marius_id, at)
        if probe < (stop_after or CFG.max_probe_attempts):
            at += CFG.probe_window
    return at - scene.started_at


# ── 1. một cái chết không được đi tắt ─────────────────────────────────────────


async def test_a_dead_machine_is_not_declared_offline_any_faster_than_anything_else() -> None:
    """FR-029: có khoảng ân hạn, và máy tắt cũng phải đi hết khoảng ấy."""
    async with _client() as c:
        scene = await _a_machine_holding_work(c)
        await _the_daemon_dies(scene.machine_id)

        engine = app.state.container.liveness
        at = scene.started_at + CFG.idle_timeout + timedelta(seconds=1)
        for probe in range(1, CFG.max_probe_attempts):
            await engine.advance(scene.marius_id, at)
            assert await _liveness(scene.marius_id) is not Liveness.OFFLINE, (
                f"Mới trượt {probe} lần dò đã tuyên offline — máy tắt đang được đi tắt, "
                "trong khi mọi thứ khác phải trượt đủ ba lần"
            )
            at += CFG.probe_window

        await engine.advance(scene.marius_id, at)
        assert await _liveness(scene.marius_id) is Liveness.OFFLINE

        grace = at - scene.started_at
        assert grace >= CFG.idle_timeout + CFG.probe_window * (CFG.max_probe_attempts - 1)


async def test_a_machine_back_inside_the_grace_period_costs_the_task_nothing() -> None:
    """Đối chứng: cùng một cái chết, chỉ khác là nó sống lại kịp."""
    async with _client() as c:
        scene = await _a_machine_holding_work(c)
        await _the_daemon_dies(scene.machine_id)
        await _walk_the_ladder(scene, stop_after=CFG.max_probe_attempts - 1)

        await _the_daemon_comes_back(scene.machine_id)
        await app.state.container.liveness.advance(
            scene.marius_id,
            scene.started_at + CFG.idle_timeout + CFG.probe_window * 3,
        )

        assert await _liveness(scene.marius_id) is Liveness.ONLINE
        task = await _task(scene.task_id)
        assert task.status == TaskStatus.IN_PROGRESS.value, (
            "Máy về kịp trong ân hạn mà đầu việc vẫn bị đậu lại — vậy ân hạn không có ý nghĩa gì"
        )


# ── 2. rơi vào đúng luồng cũ ──────────────────────────────────────────────────


async def test_the_task_lands_on_the_offline_flow_that_already_existed() -> None:
    """FR-006b, FR-028: đậu lại, nói ra lý do, và vẫn còn động cơ đẩy."""
    async with _client() as c:
        scene = await _a_machine_holding_work(c)
        await _the_daemon_dies(scene.machine_id)
        await _walk_the_ladder(scene)

        task = await _task(scene.task_id)
        assert task.status == TaskStatus.BLOCKED.value
        assert (task.status_reason or "").strip(), (
            "Đậu lại mà không nói vì sao là đầu việc bắt người ta đi tìm hiểu, "
            "trong khi hệ đã biết câu trả lời ngay lúc nó viết"
        )

        async with app.state.container.uow_factory() as uow:
            parked = await uow.tasks.get(scene.task_id)
            logs = await uow.task_logs.list_by_task(scene.task_id)
        assert parked is not None
        assert parked.drive is not None or parked.stalled, (
            "Đầu việc mất hết động cơ đẩy mà không nổi cờ nào — đúng thứ FR-028 cấm"
        )
        assert any(entry.reason == task.status_reason for entry in logs), (
            "Lý do phải nằm trong sổ chứ không chỉ trong một thông báo"
        )


async def test_nothing_about_the_machine_reaches_the_record() -> None:
    """Cái chết là của một cái máy; thứ ghi vào sổ chỉ được nói *agent offline*.

    Hiến pháp III: tầng nghiệp vụ không được biết tới máy hay runtime. Một dòng sổ có chữ
    máy trong đó là dấu hiệu luồng riêng đã mọc ra, kể cả khi mọi bài kiểm khác vẫn xanh.
    """
    async with _client() as c:
        scene = await _a_machine_holding_work(c)
        await _the_daemon_dies(scene.machine_id)
        await _walk_the_ladder(scene)

        task = await _task(scene.task_id)
        written = (task.status_reason or "").lower()
        for machine_word in ("daemon", "machine", "workplace", "máy", "chỗ làm"):
            assert machine_word not in written, (
                f"Lý do ghi vào đầu việc có chữ {machine_word!r}: {task.status_reason!r}"
            )
        assert str(scene.machine_id) not in (task.status_reason or "")


# ── 3. lượt chạy quay về kệ ───────────────────────────────────────────────────


async def test_the_run_the_dead_machine_held_goes_back_on_the_shelf() -> None:
    """FR-029a: máy chết thì cái giữ của nó hết hạn, và lượt chạy được nhả ra."""
    async with _client() as c:
        scene = await _a_machine_holding_work(c)
        await _the_daemon_dies(scene.machine_id)

        claims = app.state.container.daemon_claims
        claims._clock = lambda: utcnow() + timedelta(days=1)  # noqa: SLF001
        released = await claims.reap()

        assert scene.run_id in released, (
            "Máy đã chết mà lượt chạy vẫn mang dấu *đang có người giữ* — không ai đến hỏi "
            "nữa thì nó nằm đó mãi"
        )
        async with get_sessionmaker()() as session:
            run = await session.get(RunModel, scene.run_id)
            assert run is not None
            assert run.status == RunStatus.QUEUED.value
            assert run.accepted_at is None


async def test_what_the_dead_machine_was_holding_stops_opening_anything() -> None:
    """Nhả cái giữ ra thì cả hai chuỗi ký tự đi cùng nó cũng phải hết tác dụng.

    Hai chuỗi, hai người cầm, hai cửa khác nhau: cái máy ghi diễn biến bằng token của
    **máy** và được nhận ra qua chính lượt chạy nó đang giữ, còn agent nói chuyện bằng token
    của **lượt chạy**. Bỏ sót cái nào thì chính lượt chạy vừa được nhả ra vẫn bị cái bên đã
    mất quyền ghi vào.
    """
    async with _client() as c:
        scene = await _a_machine_holding_work(c)
        wrote = await c.post(
            f"/daemon/runs/{scene.run_id}/events",
            json={"events": [{"seq": 2, "type": "agent_message", "payload": {}}]},
            headers=auth(scene.machine_token),
        )
        assert wrote.status_code == 200, wrote.text
        spoke = await c.get("/agent/me", headers=auth(scene.run_token))
        assert spoke.status_code == 200, spoke.text

        await _the_daemon_dies(scene.machine_id)
        claims = app.state.container.daemon_claims
        claims._clock = lambda: utcnow() + timedelta(days=1)  # noqa: SLF001
        await claims.reap()

        refused = await c.post(
            f"/daemon/runs/{scene.run_id}/events",
            json={"events": [{"seq": 3, "type": "agent_message", "payload": {}}]},
            headers=auth(scene.machine_token),
        )
        assert refused.status_code == 404, refused.text
        # 404, not 401, and that is the house rule rather than an oversight: a credential
        # that no longer resolves must not confirm that the thing it once opened was ever
        # there (Hiến pháp — Điều I).
        silenced = await c.get("/agent/me", headers=auth(scene.run_token))
        assert silenced.status_code == 404, silenced.text


# ── 4. cả máy, không phải một agent ───────────────────────────────────────────


async def test_every_agent_on_the_dead_machine_falls_with_it() -> None:
    """FR-006a: máy mất nhịp thì mọi agent trên máy đó offline, một kết luận cho tất cả."""
    async with _client() as c:
        linked = await link_machine(c, "patron@acme.dev")
        both = [
            UUID(
                (
                    await invite_agent(
                        c,
                        linked.workspace_id,
                        linked.headers,
                        name=name,
                        adapter_type="daemon",
                        workplace_id=linked.workplace_id,
                    )
                )["id"]
            )
            for name in ("Alice", "Bob")
        ]
        await _the_daemon_dies(linked.machine_id)

        probe = app.state.container.liveness._probe  # noqa: SLF001
        async with app.state.container.uow_factory() as uow:
            answers = [await probe.probe(await uow.mariuses.get(one)) for one in both]
        assert answers == [False, False], (
            "Một máy tắt phải kéo theo mọi agent trên nó, không phải agent nào tình cờ "
            "được hỏi trước"
        )


async def test_the_shelf_row_for_a_live_machine_is_left_alone() -> None:
    """Đối chứng cho phép quét: máy còn thở thì không ai lấy việc khỏi tay nó."""
    async with _client() as c:
        scene = await _a_machine_holding_work(c)

        released = await app.state.container.daemon_claims.reap()
        assert scene.run_id not in released

        async with get_sessionmaker()() as session:
            run = await session.get(RunModel, scene.run_id)
            assert run is not None and run.accepted_at is not None


async def test_the_dead_machine_leaves_no_second_run_behind() -> None:
    """Nhả ra một lần, không phải mỗi vòng quét một lần."""
    async with _client() as c:
        scene = await _a_machine_holding_work(c)
        await _the_daemon_dies(scene.machine_id)
        claims = app.state.container.daemon_claims
        claims._clock = lambda: utcnow() + timedelta(days=1)  # noqa: SLF001

        assert await claims.reap() == [scene.run_id]
        assert await claims.reap() == [], "Vòng quét thứ hai nhả lại chính thứ đã nhả rồi"

        async with get_sessionmaker()() as session:
            rows = (
                await session.execute(
                    select(RunModel.id).where(RunModel.task_id == scene.task_id)
                )
            ).scalars()
            assert len(list(rows)) == 1
