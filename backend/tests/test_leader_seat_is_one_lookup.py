"""Ai đang ngồi ghế trưởng — một câu trả lời, không phải bốn (spec 001 FR-048a).

Bốn chỗ trong mã từng tự tra lấy, và bốn chỗ **không hiểu giống nhau**. Ba chỗ đọc cái cờ
"vai này là vai trưởng"; chỗ thứ tư so chuỗi chữ, ghế nào ghi đúng chữ `leader` mới tính.
Còn chỗ thứ năm thì dừng ở dòng ghế đầu tiên khớp người mà không xét dòng ấy còn hiệu lực
không — trong khi trao lại ghế là viết một dòng **mới**, nên dòng đã thu hồi nằm trước dòng
đang hiệu lực.

Cả hai đều không phải chuyện dặn nhau nhớ là xong. Chúng là những bản chép tay của cùng một
phép tra, và mỗi bản là một cơ hội sai. Bài này giữ cho phép tra ấy chỉ có một bản.
"""

from __future__ import annotations

from armarius.application.use_cases.mariuses import MariusService
from armarius.application.use_cases.seats import (
    holds_the_leader_seat,
    leader_marius_id,
)
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.entities.role import Role
from armarius.domain.entities.seat_grant import SeatGrant, SeatGrantStatus
from armarius.shared.clock import utcnow


async def _seated(uow_factory, *, role_key: str):  # noqa: ANN001, ANN202
    """Một dự án có ghế trưởng mang tên `role_key`, và một agent đang ngồi ghế đó."""
    workspaces = WorkspaceService(uow_factory)
    mariuses = MariusService(uow_factory)
    ws = await workspaces.create_workspace("WS")
    project = await workspaces.create_project(ws.id, "P")
    leader = await mariuses.register(
        workspace_id=ws.id,
        name="Leader",
        role="Backend",
        skills=[],
        adapter_type="echo",
        adapter_config={},
    )
    async with uow_factory() as uow:
        await uow.roles.add(
            Role(
                project_id=project.id,
                key=role_key,
                title="Trưởng dự án",
                seats=1,
                is_leader=True,
                created_at=utcnow(),
            )
        )
        await uow.seat_grants.add(
            SeatGrant(
                project_id=project.id,
                role_key=role_key,
                marius_id=leader.id,
                status=SeatGrantStatus.GRANTED,
                granted_by_user_id="patron",
                created_at=utcnow(),
            )
        )
        await uow.commit()
    return project, leader


async def test_a_leader_put_back_on_the_seat_is_still_found(uow_factory) -> None:  # noqa: ANN001
    """Rút ghế rồi trao lại chính người ấy: hai dòng, dòng chết nằm trước. Đọc dòng đầu rồi
    dừng thì kết luận dự án không có trưởng, và mọi lời gọi dành cho trưởng im lặng rơi."""
    project, leader = await _seated(uow_factory, role_key="leader")
    async with uow_factory() as uow:
        grants = await uow.seat_grants.list_by_project(project.id)
        seat = next(g for g in grants if g.marius_id == leader.id)
        seat.revoke()
        await uow.seat_grants.update(seat)
        await uow.seat_grants.add(
            SeatGrant(
                project_id=project.id,
                role_key="leader",
                marius_id=leader.id,
                status=SeatGrantStatus.GRANTED,
                granted_by_user_id="patron",
                created_at=utcnow(),
            )
        )
        await uow.commit()

    async with uow_factory() as uow:
        assert await leader_marius_id(uow, project.id) == leader.id
        assert await holds_the_leader_seat(uow, project.id, leader.id) is True


async def test_the_leader_seat_is_read_off_the_flag_not_off_its_name(uow_factory) -> None:  # noqa: ANN001
    """Cửa thêm vai của giao diện cho tạo một vai có bật cờ trưởng mà mang tên khác — và cửa
    ấy bỏ qua luật roster. Chỗ nào so chuỗi chữ sẽ báo dự án chưa có trưởng, trong khi chỗ
    khác nhìn thấy trưởng rành rành. Hai câu trả lời cho một câu hỏi là hỏng, dù bên nào
    đúng đi nữa."""
    project, leader = await _seated(uow_factory, role_key="truong-du-an")

    async with uow_factory() as uow:
        assert await leader_marius_id(uow, project.id) == leader.id


async def test_a_revoked_seat_leaves_the_project_without_a_leader(uow_factory) -> None:  # noqa: ANN001
    """Chiều ngược lại: rút ghế mà không trao lại thì phải trả về trống. Một phép tra chỉ
    biết nói "có" là một phép tra hỏng."""
    project, leader = await _seated(uow_factory, role_key="leader")
    async with uow_factory() as uow:
        grants = await uow.seat_grants.list_by_project(project.id)
        seat = next(g for g in grants if g.marius_id == leader.id)
        seat.revoke()
        await uow.seat_grants.update(seat)
        await uow.commit()

    async with uow_factory() as uow:
        assert await leader_marius_id(uow, project.id) is None
        assert await holds_the_leader_seat(uow, project.id, leader.id) is False
