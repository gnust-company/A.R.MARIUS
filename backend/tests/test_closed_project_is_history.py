"""Dự án đã đóng thì lưới an toàn thôi nhìn tới (spec 001 FR-005, T182).

`change_phase` hứa thẳng trong chú thích của nó: *"once closed, nothing wakes for this
project again"*. Vòng nhịp điều phối giữ lời hứa ấy — nó chỉ quét các dự án đang sống.
Vòng quét canh gác thì không: truy vấn của nó lọc **chỉ theo trạng thái đầu việc**, không
hỏi đầu việc ấy thuộc dự án nào. Đóng một dự án chỉ đổi một cột trên bảng dự án; đầu việc
còn mở của nó nằm nguyên đó, nên vòng quét vẫn nhặt, vẫn gắn cờ đình trệ, và thang phục
hồi vẫn gọi thợ dậy — về một dự án người chủ đã tuyên bố là xong.

Chính sự lệch giữa hai vòng là bằng chứng đây là chỗ bỏ sót chứ không phải chủ ý.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.domain.entities.marius import Marius
from armarius.domain.entities.project import Project, ProjectStatus
from armarius.domain.entities.run import WakeSource
from armarius.domain.entities.task import Task, TaskStatus
from armarius.domain.entities.workspace import Workspace
from armarius.domain.services.project_rules import ProjectClosed
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus
from armarius.shared.clock import utcnow


async def _seed(factory, *, phase: ProjectStatus) -> tuple[Workspace, Task]:
    """Một dự án ở giai đoạn đã cho, mang một đầu việc *đang làm* không có động cơ đẩy —
    đúng hình dạng mà vòng quét canh gác coi là bị bỏ rơi."""
    ws = Workspace(name="Studio", slug=f"s-{uuid4().hex[:6]}", owner_user_id="u1")
    project = Project(workspace_id=ws.id, name="Apollo", key="APO", status=phase)
    task = Task(
        project_id=project.id,
        title="Xuất báo cáo",
        description="Gom số liệu rồi kết xuất.",
        status=TaskStatus.IN_PROGRESS,
        drive=None,
        updated_at=utcnow() - timedelta(hours=2),
    )
    async with factory() as uow:
        await uow.workspaces.add(ws)
        await uow.projects.add(project)
        await uow.tasks.add(task)
        await uow.commit()
    return ws, task


async def test_a_live_projects_dropped_task_is_still_picked_up(uow_factory) -> None:
    """Bài kiểm đối chứng: nếu bài dưới xanh vì truy vấn không trả gì cả thì bài này đỏ."""
    _, task = await _seed(uow_factory, phase=ProjectStatus.OPERATING)
    async with uow_factory() as uow:
        found = await uow.tasks.list_stall_candidates(utcnow())
    assert [t.id for t in found] == [task.id]


async def test_a_closed_projects_task_falls_out_of_the_stall_scan(uow_factory) -> None:
    await _seed(uow_factory, phase=ProjectStatus.CLOSED)
    async with uow_factory() as uow:
        found = await uow.tasks.list_stall_candidates(utcnow())
    assert found == []


async def test_a_closed_projects_task_is_not_rebuilt_after_a_restart(uow_factory) -> None:
    """Cùng một lời hứa, ở lối khác: dựng lại động cơ đẩy lúc khởi động (FR-068) cũng
    không được chạm vào lịch sử. Tính lại động cơ đẩy cho một đầu việc chẳng ai đánh thức
    nữa là việc làm không, và nó nạp lại chính đầu việc ấy vào tầm ngắm."""
    await _seed(uow_factory, phase=ProjectStatus.CLOSED)
    async with uow_factory() as uow:
        assert await uow.tasks.list_open() == []


async def test_nothing_can_wake_an_agent_about_a_closed_project(uow_factory) -> None:
    """Lọc ở vòng quét là chưa đủ, vì vòng quét không phải cửa duy nhất.

    Thợ dọn lượt chạy treo cũng gọi người dậy, và nó đọc bảng *lượt chạy* chứ không đọc
    bảng đầu việc: một lượt chạy đang sống lúc người chủ đóng dự án vẫn treo được sau đó,
    và lúc bị dọn thì người phụ trách bị gọi dậy lần nữa — về một dự án đã tuyên bố xong.
    FR-005 nói *mọi* nhịp đánh thức phải dừng, nên chỗ chặn đặt ở nơi mọi lệnh gọi đi qua.
    """
    ws, task = await _seed(uow_factory, phase=ProjectStatus.CLOSED)
    marius = Marius(workspace_id=ws.id, name="Alice", role="Dev")
    async with uow_factory() as uow:
        await uow.mariuses.add(marius)
        await uow.commit()

    engine = WakeEngine(uow_factory, InMemoryAdapterRegistry(), InMemoryEventBus())
    with pytest.raises(ProjectClosed):
        await engine.enqueue(
            marius_id=marius.id, task_id=task.id, source=WakeSource.CONTINUATION
        )

    async with uow_factory() as uow:
        assert list(await uow.runs.list_by_task(task.id)) == []


async def test_only_the_closed_phase_is_excluded(uow_factory) -> None:
    """Bốn giai đoạn còn lại vẫn được quét.

    *Thiết lập* và *lập kế hoạch* chưa có bảng để quét, nhưng một đầu việc thật lọt vào
    đó là chuyện bất thường — chính là thứ lưới an toàn sinh ra để nói. Chỉ *đóng* mới là
    lịch sử, và chỉ *đóng* mới được im.
    """
    for phase in ProjectStatus:
        if phase is ProjectStatus.CLOSED:
            continue
        _, task = await _seed(uow_factory, phase=phase)
        async with uow_factory() as uow:
            found = await uow.tasks.list_stall_candidates(utcnow())
        assert task.id in {t.id for t in found}, phase
