"""Integration — Chat-with-Leader over the real stack (SQL + adapter streaming, #82).

Proves the core behaviours end-to-end against a real UoW and the echo adapter:
  * a patron message wakes the Leader on the project session; the reply is reconstructed
    from the streamed ``assistant.delta`` events and appended to the durable transcript;
  * an offline Leader disables the chat (no queue) — ``send`` raises;
  * turn-taking: a second message while a turn is in flight is rejected;
  * a Leader-proposed draft is approved (→ todo + the assignee is woken) or rejected
    (→ cancelled).
"""

from __future__ import annotations

import asyncio

import pytest

from armarius.application.ports.adapter import (
    AdapterCapabilities,
    Diagnostics,
    ExecResult,
)
from armarius.application.use_cases.leader_chat import LeaderChatService
from armarius.application.use_cases.liveness import LivenessEngine
from armarius.application.use_cases.mariuses import MariusService
from armarius.application.use_cases.projects import ProjectService, RoleSpec
from armarius.application.use_cases.runs import RunQueryService
from armarius.application.use_cases.tasks import TaskService
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.entities.leader_chat import ChatState, LeaderChatError
from armarius.domain.entities.marius import Liveness
from armarius.domain.entities.project import ProjectStatus
from armarius.domain.entities.project_context import (
    ContextApprovalStatus,
    ProjectContext,
)
from armarius.domain.entities.run import RunStatus, WakeSource
from armarius.domain.entities.task import TaskStatus
from armarius.domain.services.wake_reason import reason as wake_reason
from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus
from armarius.infrastructure.events.topic_bus import TopicEventBus
from armarius.shared.clock import utcnow
from tests.support.fakes import FakeLivenessProbe

_TERMINAL = (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.TIMED_OUT)


def _roster() -> list[RoleSpec]:
    return [
        RoleSpec(key="leader", title="Leader", seats=1, is_leader=True, description="Leads."),
        RoleSpec(key="backend", title="Backend", seats=1, description="Owns the API."),
    ]


def _chat_service(uow_factory, bus: TopicEventBus, *, step_delay: float = 0.0) -> LeaderChatService:
    registry = InMemoryAdapterRegistry()
    registry.register(EchoAdapter(step_delay=step_delay))
    liveness = LivenessEngine(uow_factory, FakeLivenessProbe())
    return LeaderChatService(
        uow_factory,
        registry=registry,
        control_bus=bus,
        liveness=liveness,
        base_url="http://api",
        run_timeout_seconds=30,
    )


def _wake_engine(uow_factory) -> WakeEngine:
    registry = InMemoryAdapterRegistry()
    registry.register(EchoAdapter(step_delay=0.0))
    return WakeEngine(uow_factory, registry, InMemoryEventBus(), run_timeout_seconds=30)


async def _settle_chat(chat: LeaderChatService, project_id, *, attempts: int = 400):
    for _ in range(attempts):
        view = await chat.get_or_open(project_id)
        if view.conversation.state != ChatState.THINKING:
            return view
        await asyncio.sleep(0.02)
    return await chat.get_or_open(project_id)


async def _settle_runs(runs: RunQueryService, task_id, *, want_marius=None, attempts=400):
    stable, last = 0, -1
    for _ in range(attempts):
        items = await runs.list_by_task(task_id)
        has_want = want_marius is None or any(r.marius_id == want_marius for r in items)
        all_terminal = bool(items) and all(r.status in _TERMINAL for r in items)
        if has_want and all_terminal and len(items) == last:
            stable += 1
            if stable >= 8:
                return items
        else:
            stable = 0
        last = len(items)
        await asyncio.sleep(0.02)
    return await runs.list_by_task(task_id)


async def _make_operating(uow_factory, project_id) -> None:
    """Đưa dự án tới giai đoạn nhận việc thật, không đi vòng qua cả cổng kế hoạch."""
    async with uow_factory() as uow:
        stored = await uow.projects.get(project_id)
        assert stored is not None
        stored.status = ProjectStatus.OPERATING
        await uow.projects.update(stored)
        await uow.commit()


async def _register_leader(mariuses, projects, ws, project, *, online_via=None):
    leader = await mariuses.register(
        workspace_id=ws.id, name="Lead", role="Leader",
        skills=[], adapter_type="echo", adapter_config={},
    )
    await projects.grant_seat(project.id, "leader", leader.id, system=True)
    if online_via is not None:
        await online_via.record_signal(leader.id)  # → ONLINE
    return leader


async def test_send_streams_leader_reply_into_transcript(uow_factory) -> None:
    bus = TopicEventBus()
    workspaces = WorkspaceService(uow_factory)
    mariuses = MariusService(uow_factory)
    projects = ProjectService(uow_factory)
    liveness = LivenessEngine(uow_factory, FakeLivenessProbe(True))
    chat = _chat_service(uow_factory, bus)

    ws = await workspaces.create_workspace("WS")
    project = await projects.create_project(ws.id, "Apollo", roles=_roster())
    await _register_leader(mariuses, projects, ws, project, online_via=liveness)

    view = await chat.send(project_id=project.id, message="How's the project going?")
    assert view.conversation.state == ChatState.THINKING
    assert view.leader_online is True

    settled = await _settle_chat(chat, project.id)
    assert settled.conversation.state == ChatState.IDLE
    roles = [t["role"] for t in settled.conversation.transcript]
    assert roles == ["patron", "leader"]
    assert settled.conversation.transcript[1]["text"]  # reply came from the stream
    # The dedicated project session was seeded and persisted for resume.
    assert (
        settled.conversation.session_params.get("session_id")
        == f"armarius:project:{project.id}:leader"
    )


async def test_offline_leader_disables_chat(uow_factory) -> None:
    bus = TopicEventBus()
    workspaces = WorkspaceService(uow_factory)
    mariuses = MariusService(uow_factory)
    projects = ProjectService(uow_factory)
    chat = _chat_service(uow_factory, bus)

    ws = await workspaces.create_workspace("WS")
    project = await projects.create_project(ws.id, "Apollo", roles=_roster())
    await _register_leader(mariuses, projects, ws, project)  # left OFFLINE

    view = await chat.get_or_open(project.id)
    assert view.leader_online is False
    with pytest.raises(LeaderChatError):
        await chat.send(project_id=project.id, message="are you there?")


async def test_turn_taking_rejects_concurrent_send(uow_factory) -> None:
    bus = TopicEventBus()
    workspaces = WorkspaceService(uow_factory)
    mariuses = MariusService(uow_factory)
    projects = ProjectService(uow_factory)
    liveness = LivenessEngine(uow_factory, FakeLivenessProbe(True))
    chat = _chat_service(uow_factory, bus, step_delay=0.1)  # keep the turn in flight

    ws = await workspaces.create_workspace("WS")
    project = await projects.create_project(ws.id, "Apollo", roles=_roster())
    await _register_leader(mariuses, projects, ws, project, online_via=liveness)

    await chat.send(project_id=project.id, message="first")
    with pytest.raises(LeaderChatError):
        await chat.send(project_id=project.id, message="second (too soon)")
    await _settle_chat(chat, project.id)  # drain so no bg task outlives the test


async def test_proposed_task_approve_flips_todo_and_wakes(uow_factory) -> None:
    wake = _wake_engine(uow_factory)
    workspaces = WorkspaceService(uow_factory)
    mariuses = MariusService(uow_factory)
    projects = ProjectService(uow_factory)
    tasks = TaskService(uow_factory, wake)
    runs = RunQueryService(uow_factory)

    ws = await workspaces.create_workspace("WS")
    project = await projects.create_project(ws.id, "Apollo", roles=_roster())
    worker = await mariuses.register(
        workspace_id=ws.id, name="Dev", role="Backend",
        skills=[], adapter_type="echo", adapter_config={},
    )
    await projects.grant_seat(project.id, "backend", worker.id, system=True)
    # Duyệt một đề xuất là biến nó thành việc thật, nên nó đòi dự án đã qua cổng kế hoạch
    # (FR-003). Bài kiểm này nói về chuyện *duyệt xong thì gọi ai dậy*, nên đưa dự án tới
    # đúng giai đoạn nó phải ở thay vì mượn một cảnh mà luật không cho phép.
    await _make_operating(uow_factory, project.id)

    draft = await tasks.create(
        project_id=project.id, title="Build /login", status=TaskStatus.DRAFT,
        description="Dựng màn hình đăng nhập và nối vào lối xác thực.",
        assigned_marius_id=worker.id,
    )
    assert draft.status == TaskStatus.DRAFT

    approved = await tasks.approve_proposed(draft.id)
    assert approved.status == TaskStatus.TODO

    items = await _settle_runs(runs, draft.id, want_marius=worker.id)
    assert any(r.marius_id == worker.id for r in items)


async def test_proposed_task_reject_cancels(uow_factory) -> None:
    wake = _wake_engine(uow_factory)
    workspaces = WorkspaceService(uow_factory)
    projects = ProjectService(uow_factory)
    tasks = TaskService(uow_factory, wake)

    ws = await workspaces.create_workspace("WS")
    project = await projects.create_project(ws.id, "Apollo", roles=_roster())
    draft = await tasks.create(
        project_id=project.id, title="Maybe later", status=TaskStatus.DRAFT,
    )
    rejected = await tasks.reject_proposed(draft.id)
    assert rejected.status == TaskStatus.CANCELLED


# ── một lượt gọi hụt không phải bằng chứng agent còn sống (FR-064) ──────────────


class UnreachableAdapter:
    """Một bộ nối mà cổng không tới được.

    Điểm quan trọng: nó **trả về** FAILED chứ không ném lỗi — đúng như bộ nối thật làm khi
    gặp lỗi mạng. Chính hình thù đó là chỗ lỗi từng nấp: nhánh ném lỗi để nguyên trạng
    thái sống, còn nhánh trả về FAILED thì lại ghi nhận một tín hiệu sống.
    """

    type = "unreachable"
    capabilities = AdapterCapabilities(resumable=True, streaming=True, transport="process")

    async def execute(self, ctx):  # noqa: ANN001
        return ExecResult(status=RunStatus.FAILED, error="could not reach the gateway")

    async def test_environment(self, config: dict):  # noqa: ANN001, ARG002
        return Diagnostics(ok=False, detail="gateway unreachable")


@pytest.mark.asyncio
async def test_a_wake_that_could_not_be_delivered_does_not_mark_the_leader_alive(
    uow_factory,
) -> None:
    """Quan sát được trên dịch vụ thật, không phải suy ra.

    Bộ nối báo cổng không tới được bằng cách **trả về** FAILED, nên dòng ghi tín hiệu sống
    lại đánh dấu Trưởng dự án *trực tuyến* đúng vì lần gọi tới nó đã hụt. Hệ quả là FR-064
    không bao giờ chạm tới được: bất cứ thứ gì cứ gọi một Trưởng dự án đã chết — một lần
    leo thang, một lượt rà theo nhịp — đều kéo nó về trực tuyến, nên nó không bao giờ suy
    xuống ngoại tuyến, nên người chủ không bao giờ được báo là dự án mất người điều phối.
    """
    bus = TopicEventBus()
    registry = InMemoryAdapterRegistry()
    registry.register(UnreachableAdapter())  # type: ignore[arg-type]
    liveness = LivenessEngine(uow_factory, FakeLivenessProbe())
    chat = LeaderChatService(
        uow_factory,
        registry=registry,
        control_bus=bus,
        liveness=liveness,
        base_url="http://api",
        run_timeout_seconds=30,
    )
    workspaces = WorkspaceService(uow_factory)
    projects = ProjectService(uow_factory)
    mariuses = MariusService(uow_factory)
    ws = await workspaces.create_workspace("WS")
    project = await projects.create_project(ws.id, "Apollo", roles=_roster())
    leader = await mariuses.register(
        workspace_id=ws.id, name="Lead", role="Leader",
        skills=[], adapter_type="unreachable", adapter_config={},
    )
    await projects.grant_seat(project.id, "leader", leader.id, system=True)

    # Kéo về sát ranh giới rồi gọi một lượt hụt.
    async with uow_factory() as uow:
        stored = await uow.mariuses.get(leader.id)
        stored.liveness = Liveness.CHECKING
        stored.probe_attempts = 2
        await uow.mariuses.update(stored)
        await uow.commit()

    await chat.notify(
        project_id=project.id,
        text="Đầu việc đang đình trệ, cần bạn quyết.",
        source=WakeSource.NUDGE,
        reason=wake_reason("escalated_to_leader", task="T-1", attempt=1, ceiling=3),
    )
    await _settle_chat(chat, project.id)

    async with uow_factory() as uow:
        after = await uow.mariuses.get(leader.id)
    assert after is not None
    assert after.liveness is not Liveness.ONLINE, (
        "một lần gọi hụt được ghi nhận là tín hiệu sống, nên Trưởng dự án đã chết vẫn "
        "mãi mãi trực tuyến và người chủ không bao giờ được báo (FR-064)"
    )


class _CapturingAdapter:
    """Keeps the packet it was handed, so a test can read what the Leader was actually
    told rather than what the builder would produce if called the same way."""

    type = "capturing"
    capabilities = AdapterCapabilities(resumable=True, streaming=True, transport="process")

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def execute(self, ctx):  # noqa: ANN001
        self.prompts.append(ctx.prompt)
        if ctx.on_event is not None:
            await ctx.on_event("assistant.delta", {"text": "ok"})
        return ExecResult(status=RunStatus.COMPLETED, session_params=ctx.session_params)

    async def test_environment(self, config: dict):  # noqa: ANN001, ARG002
        return Diagnostics(ok=True, detail="fine")


@pytest.mark.asyncio
async def test_the_leader_is_told_the_approved_brief_not_the_raw_project_columns(
    uow_factory,
) -> None:
    """FR-009 trên dịch vụ thật (T183).

    Dựng đúng tình huống làm lộ chỗ hụt: một bản Bối cảnh **đã duyệt** nằm cạnh hai cột
    thô trên bảng dự án mang chữ khác. Thợ đọc bản đã duyệt; trước lần sửa này, Trưởng dự
    án đọc hai cột thô — nên người chủ sửa Bối cảnh rồi duyệt xong, hai bên vẫn cãi nhau
    trên hai bản khác nhau.
    """
    bus = TopicEventBus()
    adapter = _CapturingAdapter()
    registry = InMemoryAdapterRegistry()
    registry.register(adapter)  # type: ignore[arg-type]
    liveness = LivenessEngine(uow_factory, FakeLivenessProbe(True))
    chat = LeaderChatService(
        uow_factory,
        registry=registry,
        control_bus=bus,
        liveness=liveness,
        base_url="http://api",
        run_timeout_seconds=30,
    )
    workspaces = WorkspaceService(uow_factory)
    projects = ProjectService(uow_factory)
    mariuses = MariusService(uow_factory)

    ws = await workspaces.create_workspace("WS")
    project = await projects.create_project(ws.id, "Apollo", roles=_roster())
    leader = await mariuses.register(
        workspace_id=ws.id, name="Lead", role="Leader",
        skills=[], adapter_type="capturing", adapter_config={},
    )
    await projects.grant_seat(project.id, "leader", leader.id, system=True)
    await liveness.record_signal(leader.id)

    # Hai cột thô nói một đằng…
    async with uow_factory() as uow:
        stored = await uow.projects.get(project.id)
        assert stored is not None
        stored.objective = "STALE OBJECTIVE COLUMN"
        stored.context = "STALE CONTEXT COLUMN"
        await uow.projects.update(stored)
        # …bản Bối cảnh đã duyệt nói một nẻo.
        await uow.project_contexts.add(
            ProjectContext(
                project_id=project.id,
                version=1,
                objective="Ship the approved calculator.",
                constraints="No third-party maths libraries.",
                approval_status=ContextApprovalStatus.APPROVED,
                approved_at=utcnow(),
            )
        )
        await uow.commit()

    await chat.send(project_id=project.id, message="Where are we?")
    await _settle_chat(chat, project.id)

    assert adapter.prompts, "Trưởng dự án chưa được gọi lần nào"
    packet = adapter.prompts[-1]
    assert "Ship the approved calculator." in packet
    assert "No third-party maths libraries." in packet
    assert "STALE OBJECTIVE COLUMN" not in packet
    assert "STALE CONTEXT COLUMN" not in packet
