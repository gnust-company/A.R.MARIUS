"""Buổi hỏi–đáp dựng đội là một lượt chạy cấp workspace (T048a, FR-040c, FR-040b).

Ba điều được canh ở đây, và chúng là ba điều khác nhau:

1. **Hình dạng**: lượt ấy không đầu việc, không dự án, và mang theo lời nhắn của chính nó.
   Nhờ vậy nó xác thực bằng token của lượt chạy như mọi cú gọi `/agent/*` khác, và hệ thống
   giữ đúng hai loại token (FR-014a).
2. **Không đứng đợi**: `start`/`answer` trả về trước khi agent kịp nói. Đường daemon không có
   kiểu gọi-rồi-đợi — server treo việc lên, máy rảnh lúc nào lấy lúc ấy.
3. **Không đợi thì phải có đường báo hỏng**: một lượt kết thúc mà agent không nói gì thì buổi
   phỏng vấn hết người lái, và màn hình phải biết — nếu không người chủ ngồi nhìn một khung
   chat không bao giờ nhúc nhích.
"""

from __future__ import annotations

import pytest

from armarius.application.ports.workspace_trace import EVENT_ONBOARDING_CHANGED
from armarius.application.use_cases.onboarding_session import (
    OnboardingService,
    WorkspaceAgentUnavailable,
)
from armarius.application.use_cases.projects import ProjectService
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.application.use_cases.workspace_agent import (
    WORKSPACE_AGENT_ROLE,
    WorkspaceAgentService,
)
from armarius.domain.entities.marius import Liveness, Marius
from armarius.domain.entities.onboarding import OnboardingStatus
from armarius.domain.entities.run import RunStatus
from armarius.domain.entities.workspace import Workspace
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus
from tests.support.fakes import FakeAdapter, FakeUowFactory


class _RecordingTrace:
    """Every announcement made on a workspace channel, in order."""

    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []

    async def publish(self, workspace_id, type, data) -> None:  # noqa: A002
        self.published.append((type, dict(data)))


def _world(*, adapter: FakeAdapter, trace: _RecordingTrace | None = None):
    """A workspace with a ready Workspace Agent, its onboarding service and a wake engine.

    The engine is the real one, wired to the same store, because two of the three things
    above are about what the engine does with a run that has no task: dress it on the way
    out, and close it on the way back.
    """
    factory = FakeUowFactory()
    ws = Workspace(name="Studio", slug="studio", owner_user_id="u1")
    factory.store.workspaces[ws.id] = ws
    registry = InMemoryAdapterRegistry()
    registry.register(adapter)
    engine = WakeEngine(factory, registry, InMemoryEventBus())
    onboarding = OnboardingService(
        factory,
        ProjectService(factory),
        WorkspaceAgentService(factory),
        registry,
        workspace_trace=trace,
        close_run=engine.conclude_run,
    )
    host = Marius(
        workspace_id=ws.id,
        name="Workspace Agent",
        role=WORKSPACE_AGENT_ROLE,
        adapter_type="fake",
        liveness=Liveness.ONLINE,
    )
    factory.store.mariuses[host.id] = host
    ws.workspace_agent_id = host.id
    return factory, onboarding, engine, ws.id, host


def _the_run(factory: FakeUowFactory):
    runs = list(factory.store.runs.values())
    assert len(runs) == 1, f"mong đúng một lượt chạy, có {len(runs)}"
    return runs[0]


# ── 1. hình dạng của lượt chạy ────────────────────────────────────────────────


async def test_one_turn_of_the_interview_is_one_workspace_level_run() -> None:
    factory, onboarding, _engine, ws_id, host = _world(adapter=FakeAdapter(defer=True))

    await onboarding.start(ws_id)

    run = _the_run(factory)
    assert run.marius_id == host.id
    # Không đầu việc và không dự án: lúc này chưa có dự án nào để mà thuộc về. Đúng hình dạng
    # thứ ba mà cửa xác thực đã biết đọc (FR-013d).
    assert run.task_id is None
    assert run.project_id is None
    assert run.status == RunStatus.QUEUED


async def test_the_chat_can_be_found_from_the_run_taking_its_turn() -> None:
    """Hỏi ngược lại — workspace này đang mở buổi nào — trả lời sai đúng lúc người chủ huỷ
    rồi mở lại. Buổi phỏng vấn phải tra được **từ** lượt chạy."""
    factory, onboarding, _engine, ws_id, _host = _world(adapter=FakeAdapter(defer=True))

    session = await onboarding.start(ws_id)

    run = _the_run(factory)
    async with factory() as uow:
        found = await uow.onboardings.get_by_run(run.id)
    assert found is not None and found.id == session.id


async def test_the_machine_is_handed_the_message_the_turn_was_queued_with() -> None:
    """Lượt chạy không có đầu việc thì không dựng lời nhắn từ đầu việc được — nó mang theo
    lời nhắn của chính nó, và cửa giao việc trao lại đúng lời ấy (FR-011)."""
    factory, onboarding, engine, ws_id, _host = _world(adapter=FakeAdapter(defer=True))
    await onboarding.start(ws_id)
    run = _the_run(factory)

    packet = await engine.compose_packet(run.id)

    assert packet is not None
    assert "ARMARIUS · PROJECT ONBOARDING" in packet.prompt
    # Và nó chỉ đúng buổi phỏng vấn này, không phải một buổi nào khác.
    async with factory() as uow:
        session = await uow.onboardings.get_by_run(run.id)
    assert str(session.id) in packet.prompt


async def test_a_run_about_nothing_at_all_is_not_dressed_up() -> None:
    """Không đầu việc **và** không lời nhắn nào được ghi lại thì không ai tả nổi lượt chạy
    ấy, và một lượt chạy không ai tả nổi là một lượt chạy không ai làm được."""
    from armarius.domain.entities.run import Run

    factory, _onboarding, engine, _ws_id, host = _world(adapter=FakeAdapter(defer=True))
    orphan = Run(marius_id=host.id, status=RunStatus.QUEUED)
    async with factory() as uow:
        await uow.runs.add(orphan)
        await uow.commit()

    assert await engine.compose_packet(orphan.id) is None


# ── 2. không đứng đợi ─────────────────────────────────────────────────────────


async def test_start_does_not_wait_for_the_agent_to_speak() -> None:
    """Máy nhận việc rồi mới chạy. Trả về lúc này nghĩa là chưa có câu hỏi nào — và đó
    không phải lỗi."""
    _factory, onboarding, _engine, ws_id, _host = _world(adapter=FakeAdapter(defer=True))

    session = await onboarding.start(ws_id)

    assert session.status == OnboardingStatus.OPEN
    assert session.collected["pending_question"] is None


async def test_a_runtime_that_refuses_the_turn_outright_still_reads_as_409() -> None:
    """Nhận việc là một chuyện, làm xong là chuyện khác. Từ chối ngay thì người chủ phải
    biết ngay — đây là ca duy nhất còn báo lỗi thẳng vào câu gọi."""
    factory, onboarding, _engine, ws_id, _host = _world(
        adapter=FakeAdapter(defer=True, raise_on_execute=RuntimeError("máy tắt"))
    )

    with pytest.raises(WorkspaceAgentUnavailable):
        await onboarding.start(ws_id)

    assert (await onboarding.active_for(ws_id)) is None
    assert _the_run(factory).status == RunStatus.FAILED


# ── 3. đường báo hỏng khi không còn ai đợi ────────────────────────────────────


async def test_a_turn_that_ends_without_a_word_closes_the_chat() -> None:
    factory, onboarding, engine, ws_id, _host = _world(adapter=FakeAdapter(defer=True))
    session = await onboarding.start(ws_id)
    run = _the_run(factory)

    await engine.conclude_run(run.id, status=RunStatus.COMPLETED)
    await onboarding.run_ended(run.id)

    assert (await onboarding.get(session.id)).status == OnboardingStatus.ABANDONED


async def test_a_turn_that_ends_after_the_agent_spoke_leaves_the_chat_alone() -> None:
    factory, onboarding, engine, ws_id, _host = _world(adapter=FakeAdapter(defer=True))
    session = await onboarding.start(ws_id)
    run = _the_run(factory)
    await onboarding.agent_post_question(
        session.id,
        {"question": "What are you building?", "options": [], "multi": False},
        by_run=run.id,
    )

    await engine.conclude_run(run.id, status=RunStatus.COMPLETED)
    await onboarding.run_ended(run.id)

    assert (await onboarding.get(session.id)).status == OnboardingStatus.OPEN


async def test_the_turn_of_a_chat_that_was_left_never_closes_the_one_it_was_left_for() -> None:
    """Người chủ huỷ giữa chừng rồi mở lại: lượt của buổi cũ kết thúc muộn, và nó phải chạm
    đúng buổi cũ. Đọc theo *workspace này đang mở buổi nào* thì một agent im lặng ở buổi bỏ
    dở sẽ đóng buổi đang sống."""
    factory, onboarding, engine, ws_id, _host = _world(adapter=FakeAdapter(defer=True))
    first = await onboarding.start(ws_id)
    stale_run = _the_run(factory)

    second = await onboarding.start(ws_id)  # buổi mới, buổi cũ bị bỏ
    assert second.id != first.id

    await engine.conclude_run(stale_run.id, status=RunStatus.COMPLETED)
    await onboarding.run_ended(stale_run.id)

    assert (await onboarding.get(second.id)).status == OnboardingStatus.OPEN


async def test_closing_the_turn_of_a_run_with_no_task_actually_closes_it() -> None:
    """Trước T048a lối khép lượt chạy trả về ngay khi lượt ấy không có đầu việc: nó sẽ nằm
    mở mãi, giữ một chỗ trên máy và một token còn sống theo."""
    factory, onboarding, engine, ws_id, _host = _world(adapter=FakeAdapter(defer=True))
    await onboarding.start(ws_id)
    run = _the_run(factory)

    await engine.conclude_run(run.id, status=RunStatus.COMPLETED)

    assert (await _reread(factory, run.id)).status == RunStatus.COMPLETED


async def test_the_screen_is_told_when_the_agent_speaks() -> None:
    """Không ai đứng đợi câu trả lời nữa, nên phải có cái gõ cửa màn hình."""
    trace = _RecordingTrace()
    _factory, onboarding, _engine, ws_id, _host = _world(
        adapter=FakeAdapter(defer=True), trace=trace
    )
    session = await onboarding.start(ws_id)
    assert trace.published == []  # mở chat chưa phải là một bước của cuộc hỏi–đáp

    run = _the_run(_factory)
    await onboarding.agent_post_question(
        session.id,
        {"question": "What are you building?", "options": [], "multi": False},
        by_run=run.id,
    )

    assert [t for t, _ in trace.published] == [EVENT_ONBOARDING_CHANGED]
    # Chỉ id, không mang theo lời agent nói: kênh này là tín hiệu đi đọc lại
    # (contracts/push-events.md, nguyên tắc 1 và 4).
    assert trace.published[0][1] == {"session_id": str(session.id)}


async def _reread(factory: FakeUowFactory, run_id):
    async with factory() as uow:
        return await uow.runs.get(run_id)
