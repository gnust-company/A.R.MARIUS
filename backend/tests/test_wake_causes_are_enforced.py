"""Hai danh sách cớ đánh thức là luật, không phải giấy tờ (spec 001 FR-047, FR-048, FR-048a).

Trước bài này, hai danh sách ấy chỉ có một bài kiểm đọc: không đường chạy nào hỏi tới
chúng. Hệ quả đúng như dự đoán — cớ của nhịp điều phối nằm ở danh sách của thợ suốt một
giai đoạn, trong khi chỗ duy nhất phát nó gọi Trưởng dự án. Danh sách nói một đằng, mã
chạy một nẻo, và không có gì bắt được.

Nên bài này gác **cả hai cửa** một lệnh gọi đi ra: cửa theo đầu việc (bộ máy đánh thức) và
cửa theo dự án (kênh của Trưởng dự án). Vá một cửa rồi tưởng xong là đúng cái bẫy đã sập
nhiều lần: viết điều kiện đúng trên đường đang nhìn rồi bỏ các đường khác.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from armarius.application.use_cases.leader_chat import LeaderChatService
from armarius.application.use_cases.liveness import LivenessEngine
from armarius.application.use_cases.tasks import TaskService
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.entities.marius import Liveness
from armarius.domain.entities.role import Role
from armarius.domain.entities.run import WakeSource
from armarius.domain.entities.seat_grant import SeatGrant
from armarius.domain.entities.wakeup import WakeupRequest, WakeupStatus
from armarius.domain.services.wake_reason import reason as wake_reason
from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.database.models import WakeupModel
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus
from armarius.infrastructure.events.topic_bus import TopicEventBus
from armarius.infrastructure.persistence.mappers import wakeup_to_entity
from armarius.shared.clock import utcnow
from tests.support.agents import make_agent
from tests.support.fakes import FakeLivenessProbe
from tests.support.projects import force_phase


def _engine(uow_factory) -> WakeEngine:  # noqa: ANN001 - the fixture's own type
    registry = InMemoryAdapterRegistry()
    registry.register(EchoAdapter(step_delay=0.0))
    return WakeEngine(uow_factory, registry, InMemoryEventBus(), run_timeout_seconds=30)


def _chat(uow_factory) -> LeaderChatService:  # noqa: ANN001 - the fixture's own type
    registry = InMemoryAdapterRegistry()
    registry.register(EchoAdapter(step_delay=0.0))
    return LeaderChatService(
        uow_factory,
        registry=registry,
        control_bus=TopicEventBus(),
        liveness=LivenessEngine(uow_factory, FakeLivenessProbe()),
        base_url="http://api",
        run_timeout_seconds=30,
    )


async def _world(uow_factory):  # noqa: ANN001, ANN202
    """Một dự án đang vận hành: một Trưởng dự án có ghế, một thợ giữ đầu việc."""
    workspaces = WorkspaceService(uow_factory)
    ws = await workspaces.create_workspace("WS")
    project = await workspaces.create_project(ws.id, "P")
    await force_phase(uow_factory, project.id)

    async def _agent(name: str):  # noqa: ANN202
        return await make_agent(uow_factory, 
            workspace_id=ws.id,
            name=name,
            role="Backend",
            skills=[],
            adapter_type="echo",
            adapter_config={},
        )

    leader = await _agent("Leader")
    worker = await _agent("Dev")
    tasks = TaskService(uow_factory, _engine(uow_factory))
    task = await tasks.create(
        project_id=project.id,
        title="Kết xuất báo cáo",
        description="Gom số liệu tháng rồi kết xuất ra tệp bảng tính.",
    )
    async with uow_factory() as uow:
        # The leader seat, and the task in the worker's hands — the two facts the guard
        # reads. Written straight in: `assign` would fire its own wake and this file is
        # about which wakes are allowed, not about how many there are.
        leader_role = await uow.roles.add(
            Role(
                project_id=project.id,
                key="leader",
                title="Trưởng dự án",
                seats=1,
                is_leader=True,
                created_at=utcnow(),
            )
        )
        await uow.seat_grants.add(
            SeatGrant(
                project_id=project.id,
                role_id=leader_role.id,
                marius_id=leader.id,
                granted_by_user_id="patron",
                created_at=utcnow(),
            )
        )
        held = await uow.tasks.get(task.id)
        assert held is not None
        held.assigned_marius_id = worker.id
        held.status_reason = "chờ số liệu"
        await uow.tasks.update(held)
        await uow.commit()
    return project, leader, worker, task


async def _wakes(uow_factory, task_id: UUID) -> list[WakeupRequest]:  # noqa: ANN001
    """Every wake booked on a task, refused ones included — there is no repository read
    for those on purpose: nothing in the running system needs them, only an audit does."""
    async with uow_factory() as uow:
        session = uow._session  # noqa: SLF001 - the test looks at the data, no public door
        assert session is not None
        rows = (
            await session.execute(
                select(WakeupModel)
                .where(WakeupModel.task_id == task_id)
                .order_by(WakeupModel.created_at, WakeupModel.id)
            )
        ).scalars()
        return [wakeup_to_entity(r) for r in rows]


# ── cửa thứ nhất: lệnh gọi theo đầu việc ──────────────────────────────────────


async def test_a_worker_is_not_woken_by_a_cause_that_belongs_to_the_leader(
    uow_factory,  # noqa: ANN001
) -> None:
    _project, _leader, worker, task = await _world(uow_factory)
    engine = _engine(uow_factory)

    run_id = await engine.enqueue(
        marius_id=worker.id,
        task_id=task.id,
        source=WakeSource.TASK_IN_REVIEW,
        reason=wake_reason("task_in_review", task="P-1"),
    )

    assert run_id is None, "cớ của Trưởng dự án không được gọi thợ dậy"
    rows = await _wakes(uow_factory, task.id)
    assert [w.status for w in rows] == [WakeupStatus.REFUSED], rows
    # Ghi lại, không phải chỉ bỏ đi: cái đáng bắt là *nếp*, và một lần từ chối không ai
    # đọc lại được thì y hệt sự im lặng đã để hai danh sách trôi khỏi mã.
    assert rows[0].source is WakeSource.TASK_IN_REVIEW
    assert rows[0].marius_id == worker.id
    async with uow_factory() as uow:
        assert await uow.runs.get_active_for(worker.id, task.id) is None


async def test_the_leader_is_not_woken_by_a_cause_that_belongs_to_the_worker(
    uow_factory,  # noqa: ANN001
) -> None:
    """Chiều ngược lại phải chặn y hệt, nếu không thì luật chỉ đúng một phía."""
    _project, leader, _worker, task = await _world(uow_factory)
    engine = _engine(uow_factory)

    run_id = await engine.enqueue(
        marius_id=leader.id,
        task_id=task.id,
        source=WakeSource.DEPENDENCY_CLEARED,
        reason=wake_reason("dependency_cleared", blocker="P-2"),
    )

    assert run_id is None
    assert [w.status for w in await _wakes(uow_factory, task.id)] == [WakeupStatus.REFUSED]


async def test_the_cause_the_role_owns_still_goes_through(uow_factory) -> None:  # noqa: ANN001
    """Cổng chỉ có nghĩa nếu nó **mở** đúng chỗ. Một cổng chặn tất là một cổng hỏng."""
    _project, leader, worker, task = await _world(uow_factory)
    engine = _engine(uow_factory)

    assert await engine.enqueue(
        marius_id=worker.id,
        task_id=task.id,
        source=WakeSource.APPROVAL_REJECTED,
        reason=wake_reason("output_rejected", note="thiếu đối chiếu"),
    ) is not None
    assert await engine.enqueue(
        marius_id=leader.id,
        task_id=task.id,
        source=WakeSource.BRIEF_REVIEW,
        reason=wake_reason("brief_review", rounds=3),
    ) is not None
    await engine.drain()


async def test_a_leader_put_back_on_the_seat_is_still_the_leader(uow_factory) -> None:  # noqa: ANN001
    """Đổi người ra khỏi ghế trưởng rồi đổi chính người ấy vào lại là chuyện người chủ làm
    được qua giao diện. Trước T199 mỗi lần trao ghế viết một dòng **mới**, nên sau hai thao
    tác đó người này có hai dòng: dòng cũ đã thu hồi nằm trước, dòng đang hiệu lực nằm sau.
    Đọc dòng đầu rồi dừng thì kết luận họ chẳng có vai gì, và mọi lời gọi dành cho Trưởng dự
    án im lặng rơi — đúng cái sự im lặng luật này sinh ra để chặn. Giờ chỉ còn một dòng."""
    project, leader, _worker, task = await _world(uow_factory)
    async with uow_factory() as uow:
        grants = await uow.seat_grants.list_by_project(project.id)
        seat = next(g for g in grants if g.marius_id == leader.id)
        role_id = seat.role_id
        await uow.seat_grants.remove(seat.id)
        await uow.seat_grants.add(
            SeatGrant(
                project_id=project.id,
                role_id=role_id,
                marius_id=leader.id,
                granted_by_user_id="patron",
                created_at=utcnow(),
            )
        )
        await uow.commit()
    engine = _engine(uow_factory)

    run_id = await engine.enqueue(
        marius_id=leader.id,
        task_id=task.id,
        source=WakeSource.BRIEF_REVIEW,
        reason=wake_reason("brief_review", rounds=3),
    )

    assert run_id is not None, "người đang ngồi ghế trưởng phải nhận được cớ của Trưởng dự án"
    await engine.drain()


async def test_being_named_reaches_the_leader_as_it_reaches_a_teammate(
    uow_factory,  # noqa: ANN001
) -> None:
    """Nhắc tên là lời gọi duy nhất do **người gửi** chọn người nhận. Chặn nó ở phía Trưởng
    dự án nghĩa là một câu hỏi thẳng trong luồng trao đổi không bao giờ tới nơi."""
    _project, leader, _worker, task = await _world(uow_factory)
    engine = _engine(uow_factory)

    run_id = await engine.enqueue(
        marius_id=leader.id,
        task_id=task.id,
        source=WakeSource.MENTION,
        reason=wake_reason("mentioned"),
    )

    assert run_id is not None
    await engine.drain()


# ── cửa thứ hai: lệnh gọi theo dự án, đi thẳng tới Trưởng dự án ───────────────


async def test_the_project_channel_refuses_a_cause_the_leader_does_not_own(
    uow_factory,  # noqa: ANN001
) -> None:
    """Cửa này không đi qua bộ máy đánh thức: nó viết thẳng vào phiên chung của dự án. Chốt
    ở cửa kia không che được nó, nên nó phải có chốt của riêng mình."""
    project, leader, _worker, _task = await _world(uow_factory)
    chat = _chat(uow_factory)
    async with uow_factory() as uow:
        online = await uow.mariuses.get(leader.id)
        assert online is not None
        online.liveness = Liveness.ONLINE
        await uow.mariuses.update(online)
        await uow.commit()

    delivered = await chat.notify(
        project_id=project.id,
        source=WakeSource.DEPENDENCY_CLEARED,
        reason=wake_reason("dependency_cleared", blocker="P-2"),
    )

    assert delivered is False
    async with uow_factory() as uow:
        session = uow._session  # noqa: SLF001 - the test looks at the data, no public door
        assert session is not None
        rows = list((await session.execute(select(WakeupModel))).scalars())
    assert [r.status for r in rows] == [str(WakeupStatus.REFUSED)], rows
    view = await chat.get_or_open(project.id)
    # Và không lời nào lọt vào phiên trò chuyện: một lệnh gọi bị từ chối mà vẫn để lại câu
    # trong luồng thì Trưởng dự án vẫn đọc được nó ở lượt sau — chặn nửa vời còn tệ hơn.
    assert view.conversation.transcript == []


async def test_the_project_channel_still_carries_the_leaders_own_causes(
    uow_factory,  # noqa: ANN001
) -> None:
    project, leader, _worker, _task = await _world(uow_factory)
    chat = _chat(uow_factory)
    async with uow_factory() as uow:
        online = await uow.mariuses.get(leader.id)
        assert online is not None
        online.liveness = Liveness.ONLINE
        await uow.mariuses.update(online)
        await uow.commit()

    delivered = await chat.notify(
        project_id=project.id,
        source=WakeSource.IDLE_REMINDER,
        reason=wake_reason("cadence_snags", count=2),
    )

    assert delivered is True, "cớ của nhịp điều phối phải tới được Trưởng dự án"


async def test_a_leader_holding_the_task_wears_both_hats(uow_factory) -> None:  # noqa: ANN001
    """Trưởng dự án tự ôm một đầu việc thì vừa là Trưởng vừa là người phụ trách việc đó.
    Chọn một vai rồi chặn vai kia là từ chối đúng những lời gọi hợp lệ."""
    _project, leader, _worker, task = await _world(uow_factory)
    async with uow_factory() as uow:
        held = await uow.tasks.get(task.id)
        assert held is not None
        held.assigned_marius_id = leader.id
        await uow.tasks.update(held)
        await uow.commit()
    engine = _engine(uow_factory)

    assert await engine.enqueue(
        marius_id=leader.id,
        task_id=task.id,
        source=WakeSource.DEPENDENCY_CLEARED,
        reason=wake_reason("dependency_cleared", blocker="P-2"),
    ) is not None
    await engine.drain()


async def test_somebody_with_no_part_in_the_work_is_refused(uow_factory) -> None:  # noqa: ANN001
    """FR-049 ở dạng sắc nhất: người không giữ đầu việc và cũng không dẫn dự án thì không
    có gì đang chờ họ, nên chỉ lời gọi gọi thẳng tên mới lọt."""
    project, _leader, _worker, task = await _world(uow_factory)
    async with uow_factory() as uow:
        loaded = await uow.projects.get(project.id)
        assert loaded is not None
        workspace_id = loaded.workspace_id
    bystander = await make_agent(uow_factory, 
        workspace_id=workspace_id,
        name="Ngoài cuộc",
        role="Backend",
        skills=[],
        adapter_type="echo",
        adapter_config={},
    )
    engine = _engine(uow_factory)

    assert await engine.enqueue(
        marius_id=bystander.id,
        task_id=task.id,
        source=WakeSource.COMMENT,
        reason=wake_reason("new_comment"),
    ) is None
    assert await engine.enqueue(
        marius_id=bystander.id,
        task_id=task.id,
        source=WakeSource.MENTION,
        reason=wake_reason("mentioned"),
    ) is not None
    await engine.drain()
