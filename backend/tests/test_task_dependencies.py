"""Cổng phụ thuộc đầu-cuối (#91) — cạnh ``blocked_by`` bền + gate ở transition/
approve_proposed/assign, qua SqlAlchemyUnitOfWork thật (SQLite file).

Đích spec 05 §1.3: task còn một ``blocked_by`` chưa ``done`` thì không vào được
``todo``/``in_progress``; cạnh không hợp lệ (tự-trỏ/trùng/khác dự án/tạo vòng) bị từ chối.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from armarius.application.use_cases.mariuses import MariusService
from armarius.application.use_cases.projects import ProjectService, RoleSpec
from armarius.application.use_cases.tasks import TaskService
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.entities.task import DependencyNotMetError, TaskStatus
from armarius.domain.entities.task_dependency import TaskDependencyError
from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus
from tests.support.projects import force_phase


def _services(uow_factory):
    registry = InMemoryAdapterRegistry()
    registry.register(EchoAdapter(step_delay=0.0))
    wake = WakeEngine(uow_factory, registry, InMemoryEventBus(), run_timeout_seconds=30)
    return (
        ProjectService(uow_factory),
        TaskService(uow_factory, wake),
        WorkspaceService(uow_factory),
    )


def _roster() -> list[RoleSpec]:
    return [
        RoleSpec(key="leader", title="Leader", seats=1, is_leader=True, description="Leads."),
        RoleSpec(key="worker", title="Worker", seats=1, description="Works."),
    ]


async def _make_project(projects, workspaces, *, name="Proj", key="PROJ", uow_factory=None):
    ws = await workspaces.create_workspace(name + "-WS")
    project = await projects.create_project(ws.id, name, key=key, roles=_roster())
    if uow_factory is not None:
        # Cổng FR-003: dự án chưa duyệt kế hoạch thì không nhận đầu việc thật. Bài kiểm
        # này soi cổng phụ thuộc, không soi cổng kế hoạch — đẩy thẳng sang *vận hành*.
        await force_phase(uow_factory, project.id)
    return ws, project


async def _mark_done(uow_factory, task_id) -> None:
    """Force a task to DONE for setup (represents a finished blocker; bypasses gates)."""
    async with uow_factory() as uow:
        t = await uow.tasks.get(task_id)
        assert t is not None
        t.status = TaskStatus.DONE
        await uow.tasks.update(t)
        await uow.commit()


async def test_transition_blocked_until_blocker_done(uow_factory) -> None:
    projects, tasks, workspaces = _services(uow_factory)
    _ws, project = await _make_project(projects, workspaces, uow_factory=uow_factory)
    blocker = await tasks.create(project_id=project.id, title="blocker")
    blocked = await tasks.create(
        project_id=project.id, title="blocked", description="mô tả đủ để giao"
    )
    await tasks.add_dependency(blocked.id, blocker.id)

    # blocker chưa done ⇒ vào todo bị chặn
    with pytest.raises(DependencyNotMetError):
        await tasks.transition(blocked.id, TaskStatus.TODO)

    await _mark_done(uow_factory, blocker.id)
    moved = await tasks.transition(blocked.id, TaskStatus.TODO)
    assert moved.status == TaskStatus.TODO


async def test_a_worker_can_no_longer_take_work_for_itself(uow_factory) -> None:
    """FR-072: đường tự-nhận đã gỡ. Thợ chỉ xin; xin xong không đổi người phụ trách."""
    projects, tasks, workspaces = _services(uow_factory)
    _ws, project = await _make_project(projects, workspaces, uow_factory=uow_factory)
    task = await tasks.create(
        project_id=project.id,
        title="việc",
        description="mô tả đủ để giao",
        status=TaskStatus.TODO,
    )
    assert not hasattr(tasks, "claim")

    asked = await tasks.request_assignment(task.id, uuid4(), note="tôi làm được việc này")
    assert asked.assigned_marius_id is None
    assert asked.status == TaskStatus.TODO


async def test_approve_proposed_respects_gate(uow_factory) -> None:
    projects, tasks, workspaces = _services(uow_factory)
    _ws, project = await _make_project(projects, workspaces, uow_factory=uow_factory)
    blocker = await tasks.create(project_id=project.id, title="blocker")
    draft = await tasks.create(
        project_id=project.id, title="draft", status=TaskStatus.DRAFT
    )
    await tasks.add_dependency(draft.id, blocker.id)

    with pytest.raises(DependencyNotMetError):
        await tasks.approve_proposed(draft.id)

    await _mark_done(uow_factory, blocker.id)
    approved = await tasks.approve_proposed(draft.id)
    assert approved.status == TaskStatus.TODO


async def test_assign_leaves_blocked_task_in_backlog(uow_factory) -> None:
    projects, tasks, workspaces = _services(uow_factory)
    mariuses = MariusService(uow_factory)
    ws, project = await _make_project(projects, workspaces, uow_factory=uow_factory)
    alice = await mariuses.register(
        workspace_id=ws.id,
        name="Alice",
        role="Worker",
        skills=[],
        adapter_type="echo",
        adapter_config={},
    )
    blocker = await tasks.create(project_id=project.id, title="blocker")
    blocked = await tasks.create(
        project_id=project.id, title="blocked", description="mô tả đủ để giao"
    )
    await tasks.add_dependency(blocked.id, blocker.id)

    res = await tasks.assign(blocked.id, alice.id)
    assert res.status == TaskStatus.BACKLOG  # không bị đẩy lên todo khi còn bị chặn

    await _mark_done(uow_factory, blocker.id)
    res2 = await tasks.assign(blocked.id, alice.id)
    assert res2.status == TaskStatus.TODO  # hết chặn ⇒ promote như cũ


async def test_add_dependency_rejects_self_loop(uow_factory) -> None:
    projects, tasks, workspaces = _services(uow_factory)
    _ws, project = await _make_project(projects, workspaces, uow_factory=uow_factory)
    t = await tasks.create(project_id=project.id, title="t")
    with pytest.raises(TaskDependencyError):
        await tasks.add_dependency(t.id, t.id)


async def test_add_dependency_rejects_duplicate(uow_factory) -> None:
    projects, tasks, workspaces = _services(uow_factory)
    _ws, project = await _make_project(projects, workspaces, uow_factory=uow_factory)
    a = await tasks.create(project_id=project.id, title="a")
    b = await tasks.create(project_id=project.id, title="b")
    await tasks.add_dependency(a.id, b.id)
    with pytest.raises(TaskDependencyError):
        await tasks.add_dependency(a.id, b.id)


async def test_add_dependency_rejects_cross_project(uow_factory) -> None:
    projects, tasks, workspaces = _services(uow_factory)
    _ws1, p1 = await _make_project(
        projects, workspaces, name="One", key="ONE", uow_factory=uow_factory
    )
    _ws2, p2 = await _make_project(
        projects, workspaces, name="Two", key="TWO", uow_factory=uow_factory
    )
    a = await tasks.create(project_id=p1.id, title="a")
    b = await tasks.create(project_id=p2.id, title="b")
    with pytest.raises(TaskDependencyError):
        await tasks.add_dependency(a.id, b.id)


async def test_add_dependency_rejects_cycle(uow_factory) -> None:
    projects, tasks, workspaces = _services(uow_factory)
    _ws, project = await _make_project(projects, workspaces, uow_factory=uow_factory)
    a = await tasks.create(project_id=project.id, title="a")
    b = await tasks.create(project_id=project.id, title="b")
    c = await tasks.create(project_id=project.id, title="c")
    await tasks.add_dependency(a.id, b.id)  # a blocked_by b
    await tasks.add_dependency(b.id, c.id)  # b blocked_by c
    with pytest.raises(TaskDependencyError):
        await tasks.add_dependency(c.id, a.id)  # c blocked_by a ⇒ vòng


async def test_remove_dependency_unblocks(uow_factory) -> None:
    projects, tasks, workspaces = _services(uow_factory)
    _ws, project = await _make_project(projects, workspaces, uow_factory=uow_factory)
    blocker = await tasks.create(project_id=project.id, title="blocker")
    blocked = await tasks.create(project_id=project.id, title="blocked")
    await tasks.add_dependency(blocked.id, blocker.id)
    await tasks.remove_dependency(blocked.id, blocker.id)
    moved = await tasks.transition(blocked.id, TaskStatus.TODO)  # hết cạnh ⇒ qua
    assert moved.status == TaskStatus.TODO


async def test_list_blockers_and_project_edges(uow_factory) -> None:
    projects, tasks, workspaces = _services(uow_factory)
    _ws, project = await _make_project(projects, workspaces, uow_factory=uow_factory)
    blocker = await tasks.create(project_id=project.id, title="blocker")
    blocked = await tasks.create(
        project_id=project.id, title="blocked", description="mô tả đủ để giao"
    )
    await tasks.add_dependency(blocked.id, blocker.id)

    blockers = await tasks.list_blockers(blocked.id)
    assert [b.id for b in blockers] == [blocker.id]

    edges = await tasks.list_project_dependencies(project.id)
    assert len(edges) == 1
    assert edges[0].task_id == blocked.id
    assert edges[0].blocks_task_id == blocker.id


# ── Đợt 2 (FR-031): hệ quả khi một đầu việc *xong* ───────────────────────────────
# Xong không phải dấu chấm hết của riêng một đầu việc — nó là lúc những đầu việc đang
# ngồi chờ nó được gỡ ra, và là lúc Trưởng dự án cần biết để giao tiếp. Không có vế này
# thì dây chuyền đứng lại dù chẳng ai làm sai.


class _RecordingLeaderChat:
    """Ghi lại từng lần Trưởng dự án bị gọi dậy, không dựng cả bộ máy đánh thức thật."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def notify(self, *, project_id, text: str, source, reason: str) -> bool:
        self.calls.append(
            {"project_id": project_id, "text": text, "source": source, "reason": reason}
        )
        return True


def _services_with_leader(uow_factory):
    from armarius.application.use_cases.task_log import TaskLogService
    from armarius.infrastructure.events.topic_bus import TopicEventBus

    registry = InMemoryAdapterRegistry()
    registry.register(EchoAdapter(step_delay=0.0))
    wake = WakeEngine(uow_factory, registry, InMemoryEventBus(), run_timeout_seconds=30)
    leader_chat = _RecordingLeaderChat()
    bus = TopicEventBus()
    tasks = TaskService(
        uow_factory,
        wake,
        leader_chat=leader_chat,
        task_logs=TaskLogService(uow_factory),
        control_bus=bus,
    )
    return (
        ProjectService(uow_factory),
        tasks,
        WorkspaceService(uow_factory),
        leader_chat,
        bus,
    )


async def _walk_to_done(tasks, uow_factory, task_id) -> None:
    """Đưa một đầu việc đi trọn đường hợp lệ tới *xong* (kèm thành phẩm và hai chữ ký).

    Từ Câu chuyện 3, *xong* cần đủ hai chữ ký (FR-033) — nên đường "hợp lệ" bây giờ có
    thêm khâu ký. Ghi thẳng hai chữ ký ở tầng lưu trữ vì bài kiểm này soi cổng phụ thuộc,
    không soi khâu công nhận; khâu đó có bộ kiểm riêng.
    """
    from armarius.domain.entities.approval import Approval, SignerKind
    from armarius.domain.entities.artifact import Artifact
    from armarius.shared.clock import utcnow

    await tasks.transition(task_id, TaskStatus.TODO)
    await tasks.transition(task_id, TaskStatus.IN_PROGRESS)
    async with uow_factory() as uow:
        await uow.artifacts.add(
            Artifact(task_id=task_id, name="ket-qua.txt", kind="file", uri="local://x")
        )
        for kind in (SignerKind.LEADER, SignerKind.PATRON):
            await uow.approvals.add(
                Approval(task_id=task_id, signer_kind=kind, signed_at=utcnow())
            )
        await uow.commit()
    await tasks.transition(task_id, TaskStatus.IN_REVIEW)
    await tasks.transition(task_id, TaskStatus.DONE)


async def test_finishing_a_task_unlocks_what_was_only_waiting_on_it(uow_factory) -> None:
    projects, tasks, workspaces, _leader, _bus = _services_with_leader(uow_factory)
    _ws, project = await _make_project(projects, workspaces, uow_factory=uow_factory)
    blocker = await tasks.create(project_id=project.id, title="blocker", description="mô tả")
    blocked = await tasks.create(project_id=project.id, title="blocked", description="mô tả")
    await tasks.add_dependency(blocked.id, blocker.id)

    await _walk_to_done(tasks, uow_factory, blocker.id)

    async with uow_factory() as uow:
        freed = await uow.tasks.get(blocked.id)
    assert freed is not None
    assert freed.status == TaskStatus.TODO


async def test_a_task_still_waiting_on_someone_else_is_left_alone(uow_factory) -> None:
    projects, tasks, workspaces, _leader, _bus = _services_with_leader(uow_factory)
    _ws, project = await _make_project(projects, workspaces, uow_factory=uow_factory)
    first = await tasks.create(project_id=project.id, title="một", description="mô tả")
    second = await tasks.create(project_id=project.id, title="hai", description="mô tả")
    blocked = await tasks.create(project_id=project.id, title="chờ", description="mô tả")
    await tasks.add_dependency(blocked.id, first.id)
    await tasks.add_dependency(blocked.id, second.id)

    await _walk_to_done(tasks, uow_factory, first.id)

    async with uow_factory() as uow:
        still_waiting = await uow.tasks.get(blocked.id)
    assert still_waiting is not None
    assert still_waiting.status != TaskStatus.TODO


async def test_finishing_a_task_records_the_completion_mark(uow_factory) -> None:
    projects, tasks, workspaces, _leader, _bus = _services_with_leader(uow_factory)
    _ws, project = await _make_project(projects, workspaces, uow_factory=uow_factory)
    task = await tasks.create(project_id=project.id, title="việc", description="mô tả")

    await _walk_to_done(tasks, uow_factory, task.id)

    async with uow_factory() as uow:
        done = await uow.tasks.get(task.id)
    assert done is not None
    assert done.completed_at is not None


async def test_finishing_a_task_wakes_the_leader_to_pass_the_word(uow_factory) -> None:
    projects, tasks, workspaces, leader, _bus = _services_with_leader(uow_factory)
    _ws, project = await _make_project(projects, workspaces, uow_factory=uow_factory)
    task = await tasks.create(project_id=project.id, title="việc", description="mô tả")

    await _walk_to_done(tasks, uow_factory, task.id)

    # Hai lần gọi, không phải một: đầu việc xong (FR-031), và vì đây là đầu việc duy nhất
    # nên cả đợt cũng khép luôn — Trưởng dự án được gọi lần nữa để soạn bản tổng kết
    # (FR-043). Gộp hai chuyện đó vào một lần gọi sẽ mất mất một trong hai.
    assert len(leader.calls) == 2
    assert all(c["project_id"] == project.id for c in leader.calls)
    assert leader.calls[0]["reason"] == "một đầu việc vừa xong"
    assert leader.calls[1]["reason"] == "cả đợt việc đã xong"


async def test_the_project_channel_hears_the_unlock(uow_factory) -> None:
    projects, tasks, workspaces, _leader, bus = _services_with_leader(uow_factory)
    _ws, project = await _make_project(projects, workspaces, uow_factory=uow_factory)
    blocker = await tasks.create(project_id=project.id, title="blocker", description="mô tả")
    blocked = await tasks.create(project_id=project.id, title="blocked", description="mô tả")
    await tasks.add_dependency(blocked.id, blocker.id)

    await _walk_to_done(tasks, uow_factory, blocker.id)

    from armarius.infrastructure.events.topic_bus import project_topic

    types = [e.type for e in bus.backlog(project_topic(project.id))]
    assert "dau-viec.mo-khoa" in types
    assert "dau-viec.doi-trang-thai" in types


async def test_a_refused_move_names_the_blockers_that_are_missing(uow_factory) -> None:
    """FR-025: "còn việc phụ thuộc" không giúp được ai — phải nói rõ việc nào."""
    projects, tasks, workspaces, _leader, _bus = _services_with_leader(uow_factory)
    _ws, project = await _make_project(projects, workspaces, uow_factory=uow_factory)
    first = await tasks.create(project_id=project.id, title="một", description="mô tả")
    second = await tasks.create(project_id=project.id, title="hai", description="mô tả")
    blocked = await tasks.create(project_id=project.id, title="chờ", description="mô tả")
    await tasks.add_dependency(blocked.id, first.id)
    await tasks.add_dependency(blocked.id, second.id)

    with pytest.raises(DependencyNotMetError) as refused:
        await tasks.transition(blocked.id, TaskStatus.TODO)

    assert set(refused.value.blockers) == {first.identifier, second.identifier}
    for identifier in (first.identifier, second.identifier):
        assert identifier in str(refused.value)
