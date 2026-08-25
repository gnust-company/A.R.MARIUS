"""Ghế là **một dòng đang sống**, và cửa đánh thức duyệt trên đúng dòng nó ghi (T199, T198).

Hai việc, cùng một bệnh: một câu trả lời đúng ở thời điểm đọc, sai ở thời điểm ghi.

**T199** — bảng ghế trước đây giữ cả lịch sử. Trả ghế thì lật cờ sang *đã thu hồi*; trao lại
thì viết một dòng **mới** bên cạnh. "Ai đang ngồi ghế này" vì thế là "dòng mới nhất còn ghi
đã trao" — một phép lọc mà tám chỗ đọc đều phải nhớ, và chỗ quên nhớ đã đọc dòng chết rồi
kết luận dự án không có Trưởng. Ghế còn trỏ vào vai bằng **chuỗi mã vai**, thứ người chủ sửa
được, nên đổi mã vai là ghế tự rỗng.

**T198** — cửa đánh thức đọc vai người nhận ở một giao dịch, rồi mở lượt chạy ở giao dịch
khác. Giữa hai giao dịch ấy ghế có thể bị rút, và lời gọi vẫn đi vì nó được duyệt trên ảnh
chụp cũ.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from armarius.application.use_cases.projects import ProjectService, RoleSpec
from armarius.application.use_cases.seats import leader_marius_id
from armarius.application.use_cases.tasks import TaskService
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.entities.run import WakeSource
from armarius.domain.services.wake_reason import reason as wake_reason
from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus
from armarius.infrastructure.persistence.repositories import SqlRunRepository
from armarius.shared.errors import NotFound
from tests.support.agents import make_agent
from tests.support.projects import force_phase

pytestmark = pytest.mark.asyncio


def _roster() -> list[RoleSpec]:
    return [
        RoleSpec(key="leader", title="Trưởng dự án", seats=1, is_leader=True,
                 description="Điều phối dự án."),
        RoleSpec(key="backend", title="Backend", seats=1, description="Lo phần máy chủ."),
    ]


async def _world(uow_factory):  # noqa: ANN001, ANN202
    """Một dự án có roster thật, một agent sẵn sàng ngồi ghế."""
    ws = await WorkspaceService(uow_factory).create_workspace("WS")
    projects = ProjectService(uow_factory)
    project = await projects.create_project(ws.id, "Apollo", roles=_roster())
    agent = await make_agent(uow_factory, 
        workspace_id=ws.id, name="Leader", role="Backend", skills=[],
        adapter_type="echo", adapter_config={},
    )
    return projects, project, agent


# ── T199: một ghế, một dòng ───────────────────────────────────────────────────


async def test_seating_the_same_agent_twice_leaves_one_row(uow_factory) -> None:  # noqa: ANN001
    """Trao ghế hai lần từng viết hai dòng, và hai dòng đọc ra là **hai ghế đã đầy**."""
    projects, project, agent = await _world(uow_factory)

    first = await projects.grant_seat(project.id, "leader", agent.id, system=True)
    second = await projects.grant_seat(project.id, "leader", agent.id, system=True)

    assert second.id == first.id
    assert len(await projects.list_seat_grants(project.id)) == 1


async def test_giving_a_seat_back_leaves_nothing_to_filter_out(uow_factory) -> None:  # noqa: ANN001
    projects, project, agent = await _world(uow_factory)
    grant = await projects.grant_seat(project.id, "leader", agent.id, system=True)

    await projects.revoke_seat_by_role(project.id, agent.id, "leader", system=True)

    assert await projects.list_seat_grants(project.id) == []
    async with uow_factory() as uow:
        assert await uow.seat_grants.get(grant.id) is None
        assert await leader_marius_id(uow, project.id) is None


async def test_a_seat_given_back_cannot_be_given_back_again(uow_factory) -> None:  # noqa: ANN001
    """Không còn dòng thì lời từ chối là *không tìm thấy*, không phải *sai trạng thái*."""
    projects, project, agent = await _world(uow_factory)
    await projects.grant_seat(project.id, "leader", agent.id, system=True)
    await projects.revoke_seat_by_role(project.id, agent.id, "leader", system=True)

    with pytest.raises(NotFound):
        await projects.revoke_seat_by_role(project.id, agent.id, "leader", system=True)


async def test_renaming_a_role_does_not_empty_its_seat(uow_factory) -> None:  # noqa: ANN001
    """Ghế trỏ vào **dòng vai**. Trước T199 nó trỏ vào chuỗi mã vai, nên người chủ đổi mã là
    ghế tự rỗng — mà chẳng ai đụng vào ghế cả."""
    projects, project, agent = await _world(uow_factory)
    await projects.grant_seat(project.id, "leader", agent.id, system=True)

    async with uow_factory() as uow:
        role = next(r for r in await uow.roles.list_by_project(project.id) if r.is_leader)
        role.key = "truong-du-an"
        await uow.roles.update(role)
        await uow.commit()

    async with uow_factory() as uow:
        assert await leader_marius_id(uow, project.id) == agent.id


async def test_the_seat_records_which_patron_put_them_there(uow_factory) -> None:  # noqa: ANN001
    """FR-034 vẫn đứng: đây là thứ quyết ai phải ký cho sản phẩm của agent này."""
    projects, project, agent = await _world(uow_factory)
    seat = await projects.grant_seat(
        project.id, "leader", agent.id, system=True, granted_by_user_id="patron-1"
    )
    assert seat.granted_by_user_id == "patron-1"
    assert seat.role_key == "leader"


# ── T198: duyệt và ghi trong cùng một giao dịch ───────────────────────────────


async def test_the_seat_is_read_by_the_transaction_that_opens_the_run(  # noqa: ANN001
    uow_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phép tra vai và lệnh ghi lượt chạy phải đi qua **cùng một** giao dịch.

    Đọc ở giao dịch riêng thì câu trả lời chỉ là một ảnh chụp: ghế trưởng bị rút đúng khe
    giữa hai giao dịch thì lời gọi vẫn đi, vì nó đã được duyệt trên roster không còn nữa.
    Khe ấy không dựng lại được một cách chắc chắn trong bài kiểm, nên chỗ canh là hình dạng
    sinh ra nó: cùng một kho, tức cùng một phiên, tức cùng một giao dịch.
    """
    from armarius.application.use_cases import wake_engine as module

    projects, project, agent = await _world(uow_factory)
    await force_phase(uow_factory, project.id)
    await projects.grant_seat(project.id, "leader", agent.id, system=True)

    registry = InMemoryAdapterRegistry()
    registry.register(EchoAdapter(step_delay=0.0))
    engine = WakeEngine(uow_factory, registry, InMemoryEventBus(), run_timeout_seconds=30)
    task = await TaskService(uow_factory, engine).create(
        project_id=project.id,
        title="Kết xuất báo cáo",
        description="Gom số liệu tháng rồi kết xuất ra tệp bảng tính.",
    )

    read_by: list[int] = []
    written_by: list[int] = []
    real_holds = module.holds_the_leader_seat
    real_add = SqlRunRepository.add

    async def spy_holds(uow, project_id: UUID, marius_id: UUID) -> bool:  # noqa: ANN001
        read_by.append(id(uow.runs))
        return await real_holds(uow, project_id, marius_id)

    async def spy_add(self, run):  # noqa: ANN001, ANN202
        written_by.append(id(self))
        return await real_add(self, run)

    monkeypatch.setattr(module, "holds_the_leader_seat", spy_holds)
    monkeypatch.setattr(SqlRunRepository, "add", spy_add)

    run_id = await engine.enqueue(
        marius_id=agent.id,
        task_id=task.id,
        source=WakeSource.BRIEF_REVIEW,
        reason=wake_reason("brief_review", rounds=3),
    )
    await engine.drain()

    assert run_id is not None
    assert read_by and written_by
    assert read_by[-1] == written_by[-1], (
        "vai người nhận được đọc ở một giao dịch khác giao dịch mở lượt chạy — "
        "đúng cái khe T198 nói tới"
    )
