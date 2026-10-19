"""Hai cửa sổ cùng bấm xong bước *agent đầu tiên*, mỗi cửa sổ một runtime, trên Postgres thật
(spec 003 FR-127).

Cả hai cùng đọc *người chủ nhà chưa có chỗ làm*, cả hai cùng ghi một dòng gắn. Khoá trên
`agent_workplace_bindings.marius_id` cho một dòng đi qua. Dòng kia phải về tay người gọi thành
đúng `agent_already_placed` — như thể nó tới muộn một nhịp — chứ không thành một lỗi 500 về khoá.

Ở tệp riêng, vì lý do viết ở đầu `test_daemon_enrollment_races.py`: SQLite xếp mọi người ghi sau
một khoá chung của cả cơ sở dữ liệu, nên hai lời gọi có thật sự chồng lên nhau hay không tuỳ vào
chỗ coroutine nhường lượt. Hai kết nối thật mới làm chỗ chồng ấy có thật.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from armarius.application.use_cases.workspace_agent import WorkspaceAgentService
from armarius.domain.entities.user import User
from armarius.domain.entities.workspace import Workspace
from armarius.infrastructure.daemon.enrollment import DaemonEnrollmentService
from armarius.infrastructure.daemon.models import AgentWorkplaceBindingModel
from armarius.infrastructure.daemon.workplaces import (
    DaemonWorkplaceService,
    ReportedWorkplace,
)
from armarius.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from armarius.shared.errors import Conflict


@pytest_asyncio.fixture
async def sessions(
    postgres_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Mỗi phiên một kết nối (`NullPool`): một pool đưa cùng một kết nối cho cả hai sẽ biến
    cuộc đua thành một hàng đợi."""
    yield async_sessionmaker(postgres_engine, expire_on_commit=False, class_=AsyncSession)


async def test_two_windows_choosing_at_once_leave_one_place_and_one_clear_refusal(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(sessions)

    async with uow_factory() as uow:
        user = User.create(
            email="dua@example.com", username="dua", full_name="dua", password="password1234"
        )
        await uow.users.add(user)
        workspace = Workspace(name="dua", slug="dua", owner_user_id=str(user.id))
        await uow.workspaces.add(workspace)
        await uow.commit()

    enrollment = DaemonEnrollmentService(sessions)
    started = await enrollment.start_link(platform="linux", daemon_version="0.1.0", hostname="box")
    await enrollment.approve_link(
        started.code, workspace_id=workspace.id, approved_by_user_id=user.id
    )
    issued = await enrollment.poll_link(started.code)
    assert issued is not None
    machine = await enrollment.authenticate(issued.token)
    assert machine is not None
    places = await DaemonWorkplaceService(sessions).sync(
        machine,
        reported=[
            ReportedWorkplace(cli_kind="claude_code", cli_version="2.1.226"),
            ReportedWorkplace(cli_kind="gemini", cli_version="0.56.0"),
        ],
        symlink_capable=True,
    )
    assert len(places) == 2 and all(p.ready for p in places)

    service = WorkspaceAgentService(uow_factory)
    host = await service.provide_host(workspace.id)

    async def choose(place_id):
        try:
            return await service.place_host(workspace.id, host.id, place_id)
        except Conflict as refused:
            return refused

    answers = await asyncio.gather(*(choose(p.id) for p in places))

    refused = [a for a in answers if isinstance(a, Conflict)]
    placed = [a for a in answers if not isinstance(a, Conflict)]
    assert len(placed) == 1 and len(refused) == 1, answers
    assert refused[0].code == "agent_already_placed"

    async with sessions() as session:
        rows = await session.scalar(
            select(func.count()).select_from(AgentWorkplaceBindingModel)
        )
    assert rows == 1, "một người chủ nhà, một chỗ làm, dù bao nhiêu cửa sổ bấm cùng lúc"
