"""Sửa một đầu việc sau khi tạo (spec 001 FR-070, FR-070a, T187).

Bộ định tuyến có tạo, giao, đổi trạng thái, mở lại, ký, tiêu chí, việc kế tiếp, phụ thuộc,
bình luận, thành phẩm, gọi dậy, nhật ký — và **không lối nào sửa** tiêu đề, mô tả, độ ưu
tiên hay hạn chót sau khi tạo. Không có lối này thì FR-070 chỉ đúng trên giấy: người chủ
đặt sai một hạn chót lúc tạo là phải huỷ đầu việc rồi tạo lại, mất cả bình luận, thành
phẩm và vết.

FR-070a chốt cổng nào áp là do **ai gọi**, không phải do trường nào bị chạm: người chủ sửa
thẳng, có hiệu lực ngay. Lối này là lối của người chủ, nên nó không treo chờ ai duyệt.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest

from armarius.application.use_cases.mariuses import MariusService
from armarius.application.use_cases.projects import ProjectService, RoleSpec
from armarius.application.use_cases.task_log import TaskLogService
from armarius.application.use_cases.tasks import TaskService, TitleRequiredError
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.entities.project import ProjectStatus
from armarius.domain.entities.run import WakeSource
from armarius.domain.entities.task import TaskPriority, TaskStatus
from armarius.domain.entities.task_log import TaskLogKind
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus
from tests.support.projects import force_phase

_DEADLINE = datetime(2026, 9, 1, 12, 0, 0)


def _roster() -> list[RoleSpec]:
    return [
        RoleSpec(key="leader", title="Leader", seats=1, is_leader=True, description="Leads."),
        RoleSpec(key="dev", title="Dev", seats=1, description="Builds."),
    ]


async def _stage(uow_factory, *, phase: ProjectStatus = ProjectStatus.OPERATING):
    workspaces = WorkspaceService(uow_factory)
    projects = ProjectService(uow_factory)
    tasks = TaskService(
        uow_factory,
        WakeEngine(uow_factory, InMemoryAdapterRegistry(), InMemoryEventBus()),
        task_logs=TaskLogService(uow_factory),
    )
    ws = await workspaces.create_workspace("WS")
    project = await projects.create_project(ws.id, "Apollo", roles=_roster())
    # Tạo đầu việc lúc dự án còn nhận việc, rồi mới đưa dự án tới giai đoạn cần thử —
    # nếu không thì chính cổng FR-003 chặn ngay ở bước dựng cảnh.
    await force_phase(uow_factory, project.id, ProjectStatus.OPERATING)
    task = await tasks.create(
        project_id=project.id,
        title="Xuất báo cáo tháng",
        description="Gom số liệu bán hàng rồi kết xuất ra tệp bảng tính.",
        due_date=_DEADLINE,
        definition_of_done="Tệp bảng tính nộp lên kho thành phẩm.",
    )
    await force_phase(uow_factory, project.id, phase)
    return tasks, task


async def test_the_patron_edit_takes_effect_at_once(uow_factory) -> None:
    tasks, task = await _stage(uow_factory)

    edited = await tasks.edit(
        task.id,
        title="Xuất báo cáo quý",
        description="Gom số liệu bán hàng cả quý rồi kết xuất.",
        priority="high",
        user_id="u1",
    )

    assert edited.title == "Xuất báo cáo quý"
    assert edited.description == "Gom số liệu bán hàng cả quý rồi kết xuất."
    assert edited.priority is TaskPriority.HIGH
    async with uow_factory() as uow:
        stored = await uow.tasks.get(task.id)
    assert stored is not None and stored.title == "Xuất báo cáo quý"


async def test_a_field_left_out_is_left_alone(uow_factory) -> None:
    """Sửa từng phần, không phải ghi đè cả đầu việc."""
    tasks, task = await _stage(uow_factory)

    edited = await tasks.edit(task.id, title="Tên mới", user_id="u1")

    assert edited.title == "Tên mới"
    assert edited.description == "Gom số liệu bán hàng rồi kết xuất ra tệp bảng tính."
    assert edited.due_date == _DEADLINE
    assert edited.definition_of_done == "Tệp bảng tính nộp lên kho thành phẩm."


async def test_a_wrong_deadline_can_be_wiped_not_just_replaced(uow_factory) -> None:
    """Chính là ví dụ FR-070a nêu ra.

    "Không đưa" và "đưa vào ô trống" phải là hai chuyện khác nhau, nếu không thì cái hạn
    chót đặt nhầm gỡ ra không được — mà gỡ nó ra là lý do lối này tồn tại.
    """
    tasks, task = await _stage(uow_factory)

    edited = await tasks.edit(task.id, due_date=None, user_id="u1")

    assert edited.due_date is None
    assert edited.title == "Xuất báo cáo tháng"  # không đưa ⇒ không đụng


async def test_a_task_cannot_be_left_without_a_title(uow_factory) -> None:
    tasks, task = await _stage(uow_factory)
    with pytest.raises(TitleRequiredError):
        await tasks.edit(task.id, title="   ", user_id="u1")

    async with uow_factory() as uow:
        stored = await uow.tasks.get(task.id)
    assert stored is not None and stored.title == "Xuất báo cáo tháng"


async def test_every_edit_leaves_a_line_naming_what_changed(uow_factory) -> None:
    """FR-079 — sửa yêu cầu gốc mà không có vết thì cãi nhau về sau không có gì để đối
    chiếu. Vết ghi *trường nào* đổi, không chép lại cả nội dung: sổ này không phải kho."""
    tasks, task = await _stage(uow_factory)

    await tasks.edit(task.id, title="Tên mới", due_date=None, user_id="u1")

    async with uow_factory() as uow:
        entries = [
            e for e in await uow.task_logs.list_by_task(task.id)
            if e.kind is TaskLogKind.EDITED
        ]
    assert len(entries) == 1
    assert set(entries[0].detail.get("fields", [])) == {"title", "due_date"}
    assert entries[0].actor_user_id == "u1"


async def test_an_edit_that_changes_nothing_is_not_an_event(uow_factory) -> None:
    """Ghi một dòng cho một lần sửa không sửa gì làm loãng đúng cái sổ dùng để tra."""
    tasks, task = await _stage(uow_factory)

    await tasks.edit(task.id, title="Xuất báo cáo tháng", user_id="u1")

    async with uow_factory() as uow:
        entries = [
            e for e in await uow.task_logs.list_by_task(task.id)
            if e.kind is TaskLogKind.EDITED
        ]
    assert entries == []


async def test_a_closed_projects_task_is_read_only(uow_factory) -> None:
    """FR-005 — lịch sử đọc được, không viết được. Khác cổng FR-003: một đầu việc *nháp*
    ở giai đoạn lập kế hoạch vẫn sửa được, vì sửa một bản nháp không giao việc cho ai."""
    from armarius.domain.services.project_rules import ProjectClosed

    tasks, task = await _stage(uow_factory, phase=ProjectStatus.CLOSED)
    with pytest.raises(ProjectClosed):
        await tasks.edit(task.id, title="Tên mới", user_id="u1")


async def test_a_draft_while_still_planning_can_be_edited(uow_factory) -> None:
    tasks, task = await _stage(uow_factory, phase=ProjectStatus.PLANNING)
    async with uow_factory() as uow:
        stored = await uow.tasks.get(task.id)
        assert stored is not None
        stored.status = TaskStatus.DRAFT
        await uow.tasks.update(stored)
        await uow.commit()

    edited = await tasks.edit(
        task.id, description="Bản nháp viết lại cho rõ.", user_id="u1"
    )
    assert edited.description == "Bản nháp viết lại cho rõ."


async def test_the_deadline_moves_where_it_is_told(uow_factory) -> None:
    tasks, task = await _stage(uow_factory)
    later = _DEADLINE + timedelta(days=14)

    edited = await tasks.edit(task.id, due_date=later, user_id="u1")

    assert edited.due_date == later


# ── Người phụ trách phải biết yêu cầu vừa bị sửa (FR-046, T195) ────────────────────


class _RecordedWakes:
    """Bắt lấy mọi lệnh gọi dậy phát ra, thay vì để nó chạy thật."""

    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID, WakeSource, object]] = []

    async def enqueue(self, *, marius_id, task_id, source, reason=None, **_):  # noqa: ANN001
        self.calls.append((marius_id, task_id, source, reason))
        return uuid4()


async def _staged_with_a_worker_on_it(uow_factory):
    """Một đầu việc *đang làm*, đã có người phụ trách — tình huống duy nhất mà sửa yêu
    cầu là sửa dưới chân một người đang làm dở."""
    workspaces = WorkspaceService(uow_factory)
    projects = ProjectService(uow_factory)
    mariuses = MariusService(uow_factory)
    wakes = _RecordedWakes()
    tasks = TaskService(uow_factory, wakes, task_logs=TaskLogService(uow_factory))  # type: ignore[arg-type]

    ws = await workspaces.create_workspace("WS")
    project = await projects.create_project(ws.id, "Apollo", roles=_roster())
    await force_phase(uow_factory, project.id, ProjectStatus.OPERATING)
    worker = await mariuses.register(
        workspace_id=ws.id, name="Alice", role="Dev",
        skills=[], adapter_type="echo", adapter_config={},
    )
    task = await tasks.create(
        project_id=project.id,
        title="Xuất báo cáo tháng",
        description="Gom số liệu bán hàng rồi kết xuất ra tệp bảng tính.",
        due_date=_DEADLINE,
        assigned_marius_id=worker.id,
    )
    async with uow_factory() as uow:
        stored = await uow.tasks.get(task.id)
        assert stored is not None
        stored.status = TaskStatus.IN_PROGRESS
        await uow.tasks.update(stored)
        await uow.commit()
    wakes.calls.clear()
    return tasks, task, worker, wakes


async def test_rewriting_the_brief_tells_the_worker(uow_factory) -> None:
    """Sửa xong mà không nói thì người phụ trách vẫn làm bản cũ tới lúc nộp."""
    tasks, task, worker, wakes = await _staged_with_a_worker_on_it(uow_factory)

    await tasks.edit(task.id, description="Đổi: gom số liệu cả quý.", user_id="u1")

    assert len(wakes.calls) == 1
    marius_id, task_id, source, reason = wakes.calls[0]
    assert marius_id == worker.id
    assert task_id == task.id
    assert source is WakeSource.REQUIREMENT_CHANGED
    assert reason is not None
    assert "description" in reason.render_en()


async def test_moving_the_deadline_tells_the_worker(uow_factory) -> None:
    tasks, task, _, wakes = await _staged_with_a_worker_on_it(uow_factory)

    await tasks.edit(task.id, due_date=None, user_id="u1")

    assert len(wakes.calls) == 1
    assert wakes.calls[0][2] is WakeSource.REQUIREMENT_CHANGED


async def test_a_cosmetic_change_does_not_interrupt_anyone(uow_factory) -> None:
    """Đổi độ ưu tiên không đổi việc phải làm. Gọi dậy vì nó là cắt ngang một lượt làm
    việc để báo một tin không dùng được — và một lệnh gọi vô nghĩa dạy người thợ rằng
    lệnh gọi nói chung không đáng đọc."""
    tasks, task, _, wakes = await _staged_with_a_worker_on_it(uow_factory)

    await tasks.edit(task.id, priority="critical", title="Tên gọn hơn", user_id="u1")

    assert wakes.calls == []


async def test_nobody_on_the_task_means_nobody_to_tell(uow_factory) -> None:
    tasks, task = await _stage(uow_factory)
    wakes = _RecordedWakes()
    tasks._wake = wakes  # type: ignore[assignment]

    await tasks.edit(task.id, description="Viết lại cho rõ.", user_id="u1")

    assert wakes.calls == []


async def test_a_finished_task_is_not_reopened_by_an_edit(uow_factory) -> None:
    """Đầu việc đã đóng thì sửa một dòng chữ không được kéo người ta quay lại làm — muốn
    làm tiếp thì mở lại đầu việc, và đó là một thao tác khác, có lý do kèm theo."""
    tasks, task, _, wakes = await _staged_with_a_worker_on_it(uow_factory)
    async with uow_factory() as uow:
        stored = await uow.tasks.get(task.id)
        assert stored is not None
        stored.status = TaskStatus.DONE
        await uow.tasks.update(stored)
        await uow.commit()

    await tasks.edit(task.id, description="Ghi chú thêm sau khi xong.", user_id="u1")

    assert wakes.calls == []
