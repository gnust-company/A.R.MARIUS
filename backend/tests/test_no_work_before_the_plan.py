"""Không giao việc thật trước khi kế hoạch được duyệt (spec 001 FR-003, T186).

Cổng giai đoạn đang đứng ở đúng một cửa: lối **tạo**. Nhưng cửa đó không phải cửa đánh
thức ai. Hai cửa còn lại mới là chỗ một người thợ bị gọi dậy và bảo bắt tay vào làm:

  - **giao việc** — luôn bắn một lệnh gọi tới người vừa nhận, kể cả đầu việc còn là *nháp*;
  - **duyệt một đề xuất** — đẩy *nháp* thành *chờ làm*, tức là biến một lời đề nghị thành
    việc thật, rồi cũng gọi người phụ trách dậy.

Cả hai đều đi lọt khi dự án còn ở *lập kế hoạch*. Nghĩa là một đầu việc nháp tạo hợp lệ
lúc đang bàn kế hoạch vẫn giao đi được, và thợ bắt đầu làm trước khi người chủ gật.

Lối tạo tha cho *nháp* vì một bản nháp không gọi ai dậy; hai lối này thì luôn gọi, nên ở
đây không có ngoại lệ cho nháp.
"""

from __future__ import annotations

import pytest

from armarius.application.use_cases.projects import ProjectService, RoleSpec
from armarius.application.use_cases.tasks import ProjectNotReadyForTasks, TaskService
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.entities.project import ProjectStatus
from armarius.domain.entities.task import TaskStatus
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus
from tests.support.agents import make_agent
from tests.support.projects import force_phase

_LIVE = (ProjectStatus.OPERATING, ProjectStatus.MAINTAINING)
_NOT_LIVE = (ProjectStatus.SETUP, ProjectStatus.PLANNING, ProjectStatus.CLOSED)


def _roster() -> list[RoleSpec]:
    return [
        RoleSpec(key="leader", title="Leader", seats=1, is_leader=True, description="Leads."),
        RoleSpec(key="dev", title="Dev", seats=1, description="Builds."),
    ]


async def _stage(uow_factory, phase: ProjectStatus):
    """Một dự án ép về giai đoạn cần thử, một người thợ, và một đầu việc *nháp* đã đủ mô
    tả — tức là mọi cổng khác đều mở, chỉ còn cổng giai đoạn."""
    workspaces = WorkspaceService(uow_factory)
    projects = ProjectService(uow_factory)
    tasks = TaskService(
        uow_factory,
        WakeEngine(uow_factory, InMemoryAdapterRegistry(), InMemoryEventBus()),
    )

    ws = await workspaces.create_workspace("WS")
    project = await projects.create_project(ws.id, "Apollo", roles=_roster())
    worker = await make_agent(uow_factory, 
        workspace_id=ws.id, name="Alice", role="Dev",
        skills=[], adapter_type="echo", adapter_config={},
    )
    task = await tasks.create(
        project_id=project.id,
        title="Xuất báo cáo tháng",
        description="Gom số liệu bán hàng rồi kết xuất ra tệp bảng tính.",
        status=TaskStatus.DRAFT,
    )
    await force_phase(uow_factory, project.id, phase)
    return tasks, task, worker


@pytest.mark.parametrize("phase", _NOT_LIVE)
async def test_a_task_cannot_be_handed_to_a_worker_before_the_plan_is_approved(
    uow_factory, phase: ProjectStatus
) -> None:
    tasks, task, worker = await _stage(uow_factory, phase)
    with pytest.raises(ProjectNotReadyForTasks):
        await tasks.assign(task.id, worker.id)


@pytest.mark.parametrize("phase", _NOT_LIVE)
async def test_a_refused_assignment_leaves_nobody_on_the_task(
    uow_factory, phase: ProjectStatus
) -> None:
    """Cổng phải chặn **trước** khi ghi, không phải chặn sau rồi để lại nửa việc."""
    tasks, task, worker = await _stage(uow_factory, phase)
    with pytest.raises(ProjectNotReadyForTasks):
        await tasks.assign(task.id, worker.id)

    async with uow_factory() as uow:
        stored = await uow.tasks.get(task.id)
        assert stored is not None
        assert stored.assigned_marius_id is None
        assert list(await uow.runs.list_by_task(task.id)) == []


@pytest.mark.parametrize("phase", _NOT_LIVE)
async def test_a_draft_cannot_be_released_onto_the_board_either(
    uow_factory, phase: ProjectStatus
) -> None:
    """Cửa thứ hai, cùng một luật.

    Duyệt một đề xuất là chỗ *nháp* thành việc thật rồi gọi người phụ trách dậy — đúng
    nghĩa "tạo đầu việc thật" mà FR-003 nói tới, chỉ là đi bằng lối khác lối tạo.
    """
    tasks, task, _ = await _stage(uow_factory, phase)
    with pytest.raises(ProjectNotReadyForTasks):
        await tasks.approve_proposed(task.id)

    async with uow_factory() as uow:
        stored = await uow.tasks.get(task.id)
        assert stored is not None
        assert stored.status is TaskStatus.DRAFT


@pytest.mark.parametrize("phase", _LIVE)
async def test_a_live_project_still_hands_work_over(
    uow_factory, phase: ProjectStatus
) -> None:
    """Bài kiểm đối chứng: cổng chặn đúng ba giai đoạn kia, không chặn cả hệ thống."""
    tasks, task, worker = await _stage(uow_factory, phase)
    await tasks.approve_proposed(task.id)
    assigned = await tasks.assign(task.id, worker.id)
    assert assigned.assigned_marius_id == worker.id
