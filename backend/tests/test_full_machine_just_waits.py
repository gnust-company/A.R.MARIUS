"""Máy đầy thì việc thứ sáu **đợi**, và không ai làm gì nó cả (T079a, FR-008 → FR-008e).

Người chủ nói ra hành vi này bằng đúng một câu: *trần 5, đang chạy 5, việc thứ 6 tới thì nó
đợi*. Bài này viết đúng câu ấy và không viết gì thêm — bốn điều **không** rồi một điều **có**:

  * không bị huỷ,
  * không bị hẹn giờ thử lại,
  * không bị lưới an toàn tuyên là đình trệ, kể cả khi để trôi quá ngưỡng mười phút,
  * mang một trạng thái **phân biệt được** với *máy chết*,
  * rồi một lượt chạy kết thúc, máy hỏi lại theo nhịp thường — và **đúng việc thứ sáu ấy**
    được lấy đi, không cần ai đánh thức nó.

**Vì sao bốn điều đầu đều là điều *không*.** Mỗi cái là một thứ mà một hệ thống có thiện chí
sẽ tự làm: thấy việc nằm lâu thì huỷ, thấy không ai nhận thì hẹn giờ thử lại, thấy quá mười
phút thì reo chuông. Cả ba đều biến một cái hàng đợi đang hoạt động **đúng** thành một sự cố —
và cái thứ ba còn tệ hơn hai cái kia, vì nó dạy người đọc bỏ qua chuông.

**Vì sao chạy trên Postgres thật.** Nửa cuối — máy hỏi lại và lấy đúng việc thứ sáu — đi qua
phép đếm chỗ trống có giữ khoá theo máy, thứ SQLite không có tương đương. Chính bài kiểm trên
Postgres thật đã tìm ra chỗ thiếu khoá ấy lúc làm T045; chạy lại nửa này trên SQLite là hỏi một
câu dễ hơn rồi coi như đã trả lời câu khó.

**Vì sao dựng bằng chính mã production, không viết tay hàng lên kệ.** Việc lên kệ đi qua
`DaemonClaimService.offer` — thứ duy nhất trong hệ thống ghi hàng ấy. Một hàng viết tay sẽ để
bài này chạy đúng trên một hình dạng không ai sinh ra.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from armarius.application.use_cases.push_reason import PushReasonService
from armarius.domain.entities.project import ProjectStatus
from armarius.domain.entities.run import RunStatus
from armarius.domain.entities.task import TaskDrive, TaskStatus
from armarius.domain.entities.user import User
from armarius.domain.entities.workspace import Workspace
from armarius.domain.services.push_reason_rules import (
    BLOCKED_ON_CAPACITY,
    is_live,
    stall_reason,
)
from armarius.infrastructure.daemon.claim import DaemonClaimService
from armarius.infrastructure.daemon.enrollment import MachineIdentity
from armarius.infrastructure.daemon.models import (
    AgentWorkplaceBindingModel,
    MachineModel,
    RunClaimModel,
    WorkplaceModel,
)
from armarius.infrastructure.database.models import (
    MariusModel,
    ProjectModel,
    RunModel,
    TaskModel,
)
from armarius.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from armarius.shared.clock import utcnow

#: Trần của người chủ, và cũng là số việc chiếm hết chỗ.
CEILING = 5

#: Ngưỡng lưới an toàn khi dự án không đặt riêng — mười phút, đúng con số trong câu hỏi.
HANG_SUSPECT_SECONDS = 600


@pytest_asyncio.fixture
async def sessions(
    postgres_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    yield async_sessionmaker(postgres_engine, expire_on_commit=False, class_=AsyncSession)


class _NoProjectThresholds:
    """Dự án không đặt ngưỡng riêng, nên lưới dùng mặc định của chính nó.

    Không phải một chỗ tắt: `refresh_in` rơi về đúng 600 giây khi không có ngưỡng riêng, nên
    cái được đo ở đây là con số hệ thống thật sự dùng.
    """

    async def get_thresholds(self, project_id: UUID | None) -> None:  # noqa: ARG002
        return None


@dataclass
class FullMachine:
    machine: MachineIdentity
    workplace_id: UUID
    #: Năm lượt chạy chiếm hết chỗ, theo thứ tự lên kệ.
    holding: list[UUID]
    #: Lượt chạy thứ sáu, và đầu việc của nó.
    sixth_run: UUID
    sixth_task: UUID


async def _a_machine_with_six_jobs(
    sessions: async_sessionmaker[AsyncSession],
) -> FullMachine:
    """Một workspace, một máy trần 5, một agent trên đó, và sáu đầu việc chờ nó."""
    uow = SqlAlchemyUnitOfWork(sessions)
    async with uow:
        person = User.create(
            email="patron@example.com",
            username="patron",
            full_name="Patron",
            password="password1234",
        )
        await uow.users.add(person)
        workspace = Workspace(name="WS", slug="ws", owner_user_id=str(person.id))
        await uow.workspaces.add(workspace)
        await uow.commit()

    workspace_id = UUID(str(workspace.id))
    machine_id, workplace_id, marius_id, project_id = (uuid4() for _ in range(4))
    now = utcnow()
    runs: list[UUID] = []
    tasks: list[UUID] = []

    async with sessions() as session:
        session.add(
            MachineModel(
                id=machine_id,
                workspace_id=workspace_id,
                owner_user_id=UUID(str(person.id)),
                display_name="box",
                token_hash=f"test-{uuid4().hex}",
                max_concurrent=CEILING,
                last_heartbeat_at=now,
                created_at=now,
            )
        )
        session.add(
            WorkplaceModel(
                id=workplace_id,
                workspace_id=workspace_id,
                machine_id=machine_id,
                cli_kind="claude_code",
                ready=True,
                created_at=now,
            )
        )
        session.add(
            MariusModel(
                id=marius_id,
                workspace_id=workspace_id,
                name="Marin",
                adapter_type="daemon",
                created_at=now,
            )
        )
        session.add(
            ProjectModel(
                id=project_id,
                workspace_id=workspace_id,
                name="Apollo",
                slug="apollo",
                key="APOLLO",
                status=ProjectStatus.OPERATING.value,
                created_at=now,
            )
        )
        await session.flush()
        session.add(
            AgentWorkplaceBindingModel(
                marius_id=marius_id,
                workspace_id=workspace_id,
                workplace_id=workplace_id,
                created_at=now,
            )
        )
        for _ in range(CEILING + 1):
            task_id, run_id = uuid4(), uuid4()
            tasks.append(task_id)
            runs.append(run_id)
            session.add(
                TaskModel(
                    id=task_id,
                    project_id=project_id,
                    title="Ship the thing",
                    description="Whatever the patron asked for.",
                    status=TaskStatus.IN_PROGRESS.value,
                    assigned_marius_id=marius_id,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                RunModel(
                    id=run_id,
                    project_id=project_id,
                    marius_id=marius_id,
                    task_id=task_id,
                    adapter_type="daemon",
                    status=RunStatus.QUEUED.value,
                    created_at=now,
                )
            )
        await session.commit()

    # Lên kệ qua đúng lối production ghi hàng ấy, không viết tay.
    shelf = DaemonClaimService(sessions)
    for run_id in runs:
        await shelf.offer(
            run_id=run_id, workspace_id=workspace_id, workplace_id=workplace_id
        )

    return FullMachine(
        machine=MachineIdentity(
            machine_id=machine_id,
            workspace_id=workspace_id,
            owner_user_id=UUID(str(person.id)),
            token_expires_at=None,
        ),
        workplace_id=workplace_id,
        holding=runs[:CEILING],
        sixth_run=runs[CEILING],
        sixth_task=tasks[CEILING],
    )


async def _fill(
    sessions: async_sessionmaker[AsyncSession], world: FullMachine
) -> list[UUID]:
    """Máy xin, và lấy đúng bằng trần của nó."""
    service = DaemonClaimService(sessions)
    granted = await service.claim(
        world.machine, workplace_ids=[world.workplace_id], free_slots=10
    )
    taken = [g.run_id for g in granted]
    assert len(taken) == CEILING, f"trần {CEILING} mà máy lấy được {len(taken)}"
    assert world.sixth_run not in taken, "việc thứ sáu bị phát ra dù máy đã đầy"
    return taken


async def _drive_of(
    factory, task_id: UUID, *, now
):  # noqa: ANN001, ANN201 - the app's own uow factory type
    """Động cơ đẩy hiện tại của một đầu việc, tính lại bằng chính đường production."""
    drives = PushReasonService(
        factory, _NoProjectThresholds(), accept_grace_seconds=120
    )
    async with factory() as uow:
        task = await uow.tasks.get(task_id)
        assert task is not None
        reason = await drives.refresh_in(uow, task, now=now)
        await uow.commit()
    return reason


# ── điều thứ nhất, thứ hai: không huỷ, không hẹn giờ ─────────────────────────


async def test_the_sixth_job_is_left_exactly_where_it_was(sessions) -> None:  # noqa: ANN001
    """Không huỷ, không xếp lại, không hẹn giờ (FR-008b).

    Việc thứ sáu phải nằm nguyên trên kệ dưới dạng *chưa ai nhận*: cùng trạng thái, cùng chỗ
    làm, không máy nào ghi tên vào. Đây là điều dễ vi phạm nhất với ý tốt nhất — một cú dọn
    hàng đợi tưởng mình đang giúp.
    """
    world = await _a_machine_with_six_jobs(sessions)
    await _fill(sessions, world)

    async with sessions() as session:
        run = await session.get(RunModel, world.sixth_run)
        claim = await session.get(RunClaimModel, world.sixth_run)

    assert run is not None and claim is not None, "việc thứ sáu biến mất khỏi kệ"
    assert run.status == RunStatus.QUEUED.value, (
        f"việc thứ sáu đổi trạng thái thành {run.status} — không ai được đụng vào nó"
    )
    assert claim.machine_id is None, "việc thứ sáu bị ghi tên một cái máy đang đầy"
    assert claim.claimed_at is None, "việc thứ sáu bị đánh dấu đã trao tay"
    assert claim.claim_expires_at is None, (
        "việc thứ sáu bị đặt một cái hẹn — nó không chờ đồng hồ, nó chờ chỗ trống"
    )
    assert run.accepted_at is None, "việc thứ sáu bị tính là đã có người nhận"


async def test_asking_again_while_still_full_changes_nothing(sessions) -> None:  # noqa: ANN001
    """Máy hỏi lại lúc vẫn đầy: về tay không, và việc thứ sáu vẫn y nguyên.

    Một cú hỏi về tay không là câu trả lời **bình thường** của cửa này (FR-055d), không phải
    một lần thử hỏng cần đếm hay cần lùi nhịp.
    """
    world = await _a_machine_with_six_jobs(sessions)
    await _fill(sessions, world)

    service = DaemonClaimService(sessions)
    again = await service.claim(
        world.machine, workplace_ids=[world.workplace_id], free_slots=10
    )
    assert again == [], f"máy đầy mà vẫn được phát việc: {[g.run_id for g in again]}"

    async with sessions() as session:
        claim = await session.get(RunClaimModel, world.sixth_run)
    assert claim is not None and claim.machine_id is None


# ── điều thứ ba, thứ tư: lưới không reo, và trạng thái đọc ra được ───────────


async def test_waiting_for_room_is_a_state_of_its_own_not_a_silence(
    sessions, postgres_uow_factory
) -> None:  # noqa: ANN001
    """*Đang chờ tới lượt* phải phân biệt được với *máy chết* (FR-008a, FR-008e, Điều VII).

    Một mã riêng, `blocked_on_capacity`, và nó **nêu tên** những lượt chạy đang giữ chỗ. Không
    có mã thì màn hình chỉ còn hai lựa chọn để kể: *đang chạy* hoặc *không có gì cả* — và cái
    thứ hai đọc y hệt một cái máy đã tắt.
    """
    world = await _a_machine_with_six_jobs(sessions)
    holding = await _fill(sessions, world)

    now = utcnow()
    reason = await _drive_of(postgres_uow_factory, world.sixth_task, now=now)

    assert reason is not None, "đầu việc chờ chỗ trống không có động cơ nào — nó rơi khỏi lưới"
    assert reason.kind is TaskDrive.BLOCKED_BY_TASK
    assert reason.code == BLOCKED_ON_CAPACITY, (
        f"chờ chỗ trống bị kể thành {reason.code} — không tách được khỏi chờ một đầu việc khác"
    )
    named = {part.strip() for part in (reason.ref or "").split(",")}
    assert named == {str(run_id) for run_id in holding}, (
        f"động cơ không nêu đúng những lượt chạy đang giữ chỗ: {reason.ref}"
    )


async def test_the_safety_net_never_calls_an_orderly_queue_a_stall(
    sessions, postgres_uow_factory
) -> None:  # noqa: ANN001
    """Để trôi quá ngưỡng mười phút: vẫn không phải đình trệ (FR-008c).

    Hai nửa, và nửa thứ hai mới là nửa thật. Luật nói *không đình trệ* — nhưng thứ quyết định
    trong lúc chạy là cái vòng quét, và nó chỉ nhặt những đầu việc có hạn đã trôi qua. Một
    động cơ **không đồng hồ** nên không bao giờ vào tầm nhặt của nó. Kiểm cả hai vì hai nửa
    hỏng độc lập với nhau: luật đúng mà truy vấn nhặt nhầm thì chuông vẫn reo.
    """
    world = await _a_machine_with_six_jobs(sessions)
    await _fill(sessions, world)

    now = utcnow()
    reason = await _drive_of(postgres_uow_factory, world.sixth_task, now=now)
    assert reason is not None and reason.expires_at is None, (
        "chờ chỗ trống bị gắn một cái đồng hồ — đo cùng một cái tắc nghẽn hai lần"
    )

    long_after = now + timedelta(seconds=HANG_SUSPECT_SECONDS * 2)
    assert is_live(reason, now=long_after), "động cơ chết theo thời gian dù không có gì đổi"
    assert stall_reason(reason, now=long_after) is None, (
        "một hàng đợi đang chạy đúng bị tuyên là đình trệ"
    )

    async with postgres_uow_factory() as uow:
        candidates = await uow.tasks.list_stall_candidates(long_after, limit=500)
    assert world.sixth_task not in {task.id for task in candidates}, (
        "vòng quét nhặt đầu việc đang xếp hàng — chuông sẽ reo về một chuyện không hỏng"
    )


# ── điều thứ năm: chỗ trống mở ra thì đúng việc ấy đi ────────────────────────


async def test_the_moment_a_slot_frees_the_waiting_job_is_the_one_taken(
    sessions,
) -> None:  # noqa: ANN001
    """Bằng chứng hành vi, không phải bốn điều *không* ở trên (FR-008d, FR-008e).

    Một lượt chạy kết thúc, rồi máy hỏi lại **theo nhịp thường** — không cú hích, không ai
    đánh thức, không đường nào khác. Đúng việc thứ sáu ấy phải đi ra. Bốn bài trên chứng minh
    không ai phá nó; bài này chứng minh nó vẫn còn chạy được.
    """
    world = await _a_machine_with_six_jobs(sessions)
    holding = await _fill(sessions, world)

    # Một lượt chạy khép lại, đúng như cửa khép ghi: trạng thái đổi, hàng trên kệ để nguyên
    # cho vòng quét dọn. Chỗ trống phải mở ra từ **lượt chạy**, không từ hàng.
    async with sessions() as session:
        await session.execute(
            update(RunModel)
            .where(RunModel.id == holding[0])
            .values(status=RunStatus.COMPLETED.value, finished_at=utcnow())
        )
        await session.commit()

    service = DaemonClaimService(sessions)
    granted = await service.claim(
        world.machine, workplace_ids=[world.workplace_id], free_slots=10
    )

    assert [g.run_id for g in granted] == [world.sixth_run], (
        f"chỗ trống mở ra mà việc đang chờ không đi: {[g.run_id for g in granted]}"
    )

    async with sessions() as session:
        claim = await session.get(RunClaimModel, world.sixth_run)
        run = await session.get(RunModel, world.sixth_run)
    assert claim is not None and claim.machine_id == world.machine.machine_id
    assert run is not None and run.accepted_at is not None


async def test_one_slot_frees_and_only_one_job_goes(sessions) -> None:  # noqa: ANN001
    """Một chỗ trống là một việc — trần vẫn là trần sau khi nó mở ra.

    Phép đếm chỗ trống đọc *lượt chạy đang giữ máy*, không đọc *hàng trên kệ*; một cú đếm nhầm
    sang hàng sẽ thấy máy vẫn đủ năm hàng và không phát gì, hoặc thấy trống hẳn và phát quá.
    """
    world = await _a_machine_with_six_jobs(sessions)
    holding = await _fill(sessions, world)

    async with sessions() as session:
        await session.execute(
            update(RunModel)
            .where(RunModel.id.in_(holding[:2]))
            .values(status=RunStatus.COMPLETED.value, finished_at=utcnow())
        )
        await session.commit()

    service = DaemonClaimService(sessions)
    granted = await service.claim(
        world.machine, workplace_ids=[world.workplace_id], free_slots=10
    )
    # Hai chỗ mở ra nhưng chỉ còn một việc trên kệ: máy nhận một, và không bịa ra cái thứ hai.
    assert [g.run_id for g in granted] == [world.sixth_run]

    async with sessions() as session:
        left = await session.execute(
            select(RunClaimModel.run_id).where(RunClaimModel.machine_id.is_(None))
        )
    assert left.scalars().all() == [], "còn việc nằm lại trên kệ dù máy đã có chỗ"
