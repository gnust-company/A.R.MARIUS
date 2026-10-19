"""Chỗ làm của agent đổi thì kiểm ngay, không đợi hết quãng giãn (FR-006e).

Người chủ gặp đúng ca này ngày 2026-10-12, với DB trống và daemon `v0.2.0` cài như một người
dùng mới: đăng ký, hai mươi phút sau mới nối máy, máy chạy, runtime ready — mà người chủ nhà
vẫn offline thêm mười mấy phút nữa. Nó được tạo lúc đăng ký, khi chưa có máy nào, nên lịch kiểm
lại đã giãn tới 16 phút; gắn nó vào chỗ làm không báo gì cho bộ kiểm.

Mọi bài ở đây đi qua **cửa thật** và **không** chạy vòng kiểm định kỳ lần nào: câu hỏi là trạng
thái ngay sau việc đổi chỗ làm, không phải sau khi đồng hồ kịp chạy tới.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from armarius.application.ports.liveness_probe import LivenessProbe
from armarius.application.ports.workspace_trace import EVENT_MARIUS_ONLINE
from armarius.application.use_cases.liveness import LivenessEngine
from armarius.domain.entities.marius import Liveness, Marius
from armarius.domain.entities.workspace import Workspace
from armarius.domain.services.liveness_fsm import LivenessConfig
from armarius.infrastructure.database.engine import get_sessionmaker, init_db
from armarius.infrastructure.database.models import MariusModel
from armarius.infrastructure.events.topic_bus import TopicEventBus
from armarius.infrastructure.events.workspace_trace import ControlBusWorkspaceTrace
from armarius.main import app
from armarius.shared.clock import utcnow
from tests.support.fakes import FakeLivenessProbe, FakeUowFactory
from tests.support.machines import auth, link_machine, link_machine_to, put_host_to_work


@pytest.fixture(autouse=True)
async def _bootstrap():
    await init_db()
    yield


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(c: AsyncClient, email: str) -> tuple[dict[str, str], str]:
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Vũ", "password": "password1234"},
    )
    assert r.status_code == 201, r.text
    headers = auth(r.json()["tokens"]["access_token"])
    workspaces = await c.get("/v1/workspaces", headers=headers)
    return headers, workspaces.json()[0]["id"]


async def _directory(c: AsyncClient, headers: dict[str, str], ws: str) -> list[dict]:
    r = await c.get(f"/v1/workspaces/{ws}/mariuses", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def _set_liveness(marius_id: str, **columns) -> None:
    async with get_sessionmaker()() as session:
        await session.execute(
            update(MariusModel).where(MariusModel.id == UUID(marius_id)).values(**columns)
        )
        await session.commit()


async def test_the_host_is_online_as_soon_as_its_owner_chooses_where_it_works() -> None:
    """Đúng ca người chủ gặp: người chủ nhà đã giãn tới 16 phút trước khi máy nối vào.

    Từ đặc tả 003 (FR-112, sửa 2026-10-12) việc nối máy không tự đặt người chủ nhà nữa — người
    chủ chọn runtime cho nó. Lần chọn ấy là lần đổi chỗ làm mà FR-006e nói tới.
    """
    async with _client() as c:
        headers, ws = await _register(c, "host-waited@armarius.dev")
        host = next(m for m in await _directory(c, headers, ws) if m["role"] == "Workspace Agent")

        # Hai mươi phút không có máy nào: mỗi vòng ba lần kiểm trượt, và quãng chờ lần sau
        # đã giãn tới 16 phút.
        now = utcnow()
        await _set_liveness(
            host["id"],
            liveness="offline",
            probe_attempts=3,
            backoff_step=5,
            offline_since=now,
            next_probe_at=now + timedelta(minutes=16),
        )

        machine = await link_machine_to(c, headers, ws)
        chosen = await put_host_to_work(c, headers, ws, machine.workplace_id)
        assert chosen.status_code == 200, chosen.text

        host = next(m for m in await _directory(c, headers, ws) if m["id"] == host["id"])
        assert host["liveness"] == "online", (
            "người chủ đã chọn runtime mà người chủ nhà vẫn ngồi chờ hết quãng giãn: "
            f"{host}"
        )


async def test_an_agent_created_on_a_ready_place_is_online_in_the_answer() -> None:
    """Tạo agent xong là chat được ngay, không phải đợi vòng kiểm định kỳ tới lượt nó."""
    async with _client() as c:
        machine = await link_machine(c, "created-online@armarius.dev")

        created = await c.post(
            f"/v1/workspaces/{machine.workspace_id}/mariuses",
            headers=machine.headers,
            json={"name": "Cassia", "workplace_id": machine.workplace_id},
        )
        assert created.status_code == 201, created.text
        assert created.json()["liveness"] == "online", (
            f"câu trả lời của lệnh tạo agent vẫn nói nó offline: {created.json()}"
        )

        listed = next(
            m
            for m in await _directory(c, machine.headers, machine.workspace_id)
            if m["name"] == "Cassia"
        )
        assert listed["liveness"] == "online", listed


async def test_removing_a_machine_stops_its_agents_being_online_at_once() -> None:
    """Chiều ngược lại: mất chỗ làm cũng là đổi chỗ làm, và cũng phải kiểm ngay."""
    async with _client() as c:
        machine = await link_machine(c, "machine-removed@armarius.dev")
        created = await c.post(
            f"/v1/workspaces/{machine.workspace_id}/mariuses",
            headers=machine.headers,
            json={"name": "Decima", "workplace_id": machine.workplace_id},
        )
        assert created.status_code == 201, created.text
        agent_id = created.json()["id"]
        # Vừa trả lời xong: theo nhịp thường, nó còn được tin là online thêm 90 giây nữa.
        await _set_liveness(agent_id, liveness="online", last_seen_at=utcnow())

        removed = await c.delete(
            f"/v1/workspaces/{machine.workspace_id}/machines/{machine.machine_id}",
            headers=machine.headers,
        )
        assert removed.status_code == 204, removed.text

        agent = next(
            m
            for m in await _directory(c, machine.headers, machine.workspace_id)
            if m["id"] == agent_id
        )
        # Đang kiểm, không phải offline: luật ba lần trượt mới tuyên offline vẫn đứng nguyên
        # (FR-006b). Cái phải đổi là lần kiểm đã bắt đầu, thay vì 90 giây nữa mới bắt đầu.
        assert agent["liveness"] == "checking", (
            f"máy giữ agent đã bị gỡ mà agent vẫn được tin là online: {agent}"
        )


# ── bộ kiểm, không qua cửa HTTP: những điều cửa thật không chạm tới được ─────────

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


class _BrokenProbe(LivenessProbe):
    async def probe(self, marius: Marius) -> bool:
        raise RuntimeError("không đọc được DB")


def _engine_with(
    marius: Marius, probe: LivenessProbe
) -> tuple[LivenessEngine, FakeUowFactory, TopicEventBus]:
    factory = FakeUowFactory()
    ws = Workspace(name="Studio", slug="studio", owner_user_id="u1")
    factory.store.workspaces[ws.id] = ws
    marius.workspace_id = ws.id
    factory.store.mariuses[marius.id] = marius
    bus = TopicEventBus()
    engine = LivenessEngine(
        factory, probe, cfg=LivenessConfig(), workspace_trace=ControlBusWorkspaceTrace(bus)
    )
    return engine, factory, bus


async def test_a_new_place_brings_the_agent_back_and_tells_the_screen() -> None:
    """Màn hình chỉ đổi khi có tin (Hiến pháp IV): online ngay mà không báo thì vẫn khoá chat."""
    m = Marius(
        liveness=Liveness.OFFLINE, backoff_step=5, next_probe_at=T0 + timedelta(minutes=16)
    )
    engine, factory, bus = _engine_with(m, FakeLivenessProbe(True))

    await engine.placement_changed([m.id], now=T0)

    assert factory.store.mariuses[m.id].liveness == Liveness.ONLINE
    online = [
        e.data for e in bus.backlog(f"ws:{m.workspace_id}") if e.type == EVENT_MARIUS_ONLINE
    ]
    assert online == [{"marius_id": str(m.id)}], (
        "agent đã online nhưng không có tin nào, khung chat trên màn hình vẫn khoá"
    )


async def test_a_miss_at_the_new_place_starts_the_wait_from_the_beginning() -> None:
    """Quãng giãn tích ở chỗ cũ là chuyện của chỗ cũ."""
    m = Marius(
        liveness=Liveness.OFFLINE, backoff_step=5, next_probe_at=T0 + timedelta(minutes=16)
    )
    engine, factory, _bus = _engine_with(m, FakeLivenessProbe(False))

    await engine.placement_changed([m.id], now=T0)

    after = factory.store.mariuses[m.id]
    assert after.liveness == Liveness.CHECKING, after.liveness
    assert after.probe_attempts == 1, "phải kiểm ngay một lần, không đợi tới lượt"
    assert after.backoff_step == 0, "quãng giãn của chỗ cũ vẫn bị mang sang chỗ mới"


async def test_a_turn_in_flight_is_left_alone() -> None:
    """Đang chạy một lượt đã là bằng chứng sống; kéo nó về *đang kiểm* là xoá mốc canh treo."""
    m = Marius(liveness=Liveness.WORKING, turn_started_at=T0)
    probe = FakeLivenessProbe(False)
    engine, factory, _bus = _engine_with(m, probe)

    await engine.placement_changed([m.id], now=T0 + timedelta(seconds=5))

    after = factory.store.mariuses[m.id]
    assert after.liveness == Liveness.WORKING
    assert after.turn_started_at == T0
    assert probe.calls == 0


async def test_a_look_that_fails_does_not_fail_the_change_of_place() -> None:
    """Việc đổi chỗ làm đã xong; lần kiểm theo sau hỏng thì vòng kiểm định kỳ đo lại."""
    m = Marius(liveness=Liveness.OFFLINE)
    engine, _factory, _bus = _engine_with(m, _BrokenProbe())

    await engine.placement_changed([m.id], now=T0)
