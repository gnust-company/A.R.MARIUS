"""Từ lúc máy nhận việc tới lúc agent mở miệng (T049, T050, T051, FR-056, FR-057).

There is a gap in the middle of starting work, and until now nothing was watching it. A
machine takes the work; then it builds a working directory, writes the skills, and starts a
cold CLI. Two to five seconds on a good day, longer on a cold Windows box with a large skill
bundle. During all of it the agent has produced nothing, so the old rule — *a run is being
driven once it has emitted something* — read the task as one nobody had picked up, and the
sweep woke it a second time. The same work, twice, on the same machine.

Three things are settled here, and they are the same idea from three sides:

  * the drive starts **when the work is taken**, not when the agent speaks (FR-056);
  * it dies **exactly when the hold on the work dies**, because the two are one number and
    tuning them apart would either strand a task or rob a healthy machine (FR-056c);
  * *nobody took it* and *something took it and died getting ready* stop looking alike
    (FR-057) — and after the work is handed back, the waiting is counted from the hand-back
    rather than from a booking that is now ancient history (FR-056b).

The last two sections are a different question with a different answer: a task that is
ready and has nowhere to start is **waiting**, not dropped, and what it is waiting on is
named (FR-008a). That cannot be proved on a snapshot built by hand, because the whole claim
is that the queue is read from real rows — so it runs against a database. And the *shape* of
that wait has to survive onto the task itself, or the board can only ever render both shapes
of drive #5 as one sentence (FR-008b, T055).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update

from armarius.application.use_cases.projects import ProjectService
from armarius.application.use_cases.push_reason import PushReasonService
from armarius.application.use_cases.tasks import TaskService
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.entities.project import ProjectThresholds
from armarius.domain.entities.run import Run, RunStatus, WakeSource
from armarius.domain.entities.task import TaskDrive, TaskStatus
from armarius.domain.services.push_reason_rules import (
    BLOCKED_ON_CAPACITY,
    BLOCKED_ON_TASK,
    DriveSnapshot,
    infer_drive,
    is_live,
)
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.daemon.models import (
    AgentWorkplaceBindingModel,
    MachineModel,
    RunClaimModel,
    WorkplaceModel,
)
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus
from armarius.shared.clock import utcnow
from armarius.shared.config import settings
from tests.support.agents import make_agent
from tests.support.projects import force_phase

T0 = datetime(2026, 8, 26, 9, 0, 0, tzinfo=UTC)
SUSPECT = 600
GRACE = 120
HOLD = settings.run_claim_hold_seconds

THRESHOLDS = ProjectThresholds(
    hang_suspect_seconds=SUSPECT,
    hang_grace_seconds=GRACE,
    orchestration_cadence_seconds=900,
    due_soon_hours=(24, 12, 6, 1),
    patron_reminder_hours=(8, 24, 72),
    level1_recovery_attempts=3,
    rejection_round_cap=3,
    orchestration_wakes_per_hour=4,
)


def snap(**over: object) -> DriveSnapshot:
    base: dict[str, object] = {
        "task_id": uuid4(),
        "status": TaskStatus.IN_PROGRESS,
        "run_last_output_at": None,
        "wake_booked_at": None,
        "patron_item_pending": False,
        "unmet_blockers": (),
        "external_due_at": None,
        "recovery_retry_at": None,
        "slots_taken_by": (),
        "run_accepted_at": None,
        "last_taken_at": None,
    }
    base.update(over)
    return DriveSnapshot(**base)  # type: ignore[arg-type]


def drive(s: DriveSnapshot, *, now: datetime = T0):
    return infer_drive(
        s,
        now=now,
        hang_suspect_seconds=SUSPECT,
        hang_grace_seconds=GRACE,
        accept_grace_seconds=HOLD,
    )


# ── 1. the drive starts when the work is taken ────────────────────────────────


# The gap this whole file is about. A machine took the work two seconds ago and is laying out
# a working directory; the agent does not exist yet, let alone have anything to say. The task
# is being worked on, and the board has to say so — otherwise the sweep sees a task with
# nothing moving it and wakes it again (FR-056).
async def test_work_that_has_been_taken_is_already_being_driven() -> None:
    reason = drive(snap(run_accepted_at=T0 - timedelta(seconds=2)))

    assert reason is not None and reason.kind is TaskDrive.RUN_ACTIVE
    assert is_live(reason, now=T0)


# FR-056c, and the reason the number is not allowed to be two numbers. The drive has to die
# at the same instant the hold does: a moment earlier and the board calls a healthy setup
# dropped; a moment later and the work is back on the shelf while the board still shows it
# running.
async def test_the_drive_dies_at_the_same_moment_the_hold_does() -> None:
    taken_at = T0 - timedelta(seconds=HOLD)

    reason = drive(snap(run_accepted_at=taken_at))

    assert reason is not None
    assert reason.expires_at == taken_at + timedelta(seconds=HOLD)
    assert is_live(reason, now=T0) is False
    assert is_live(reason, now=T0 - timedelta(seconds=1)) is True


# Once the agent speaks, the hold stops being what is watching and the silence threshold
# takes over. Both are drive #1; what changes is which clock it carries, and the later
# evidence is the one that counts.
async def test_once_the_agent_speaks_the_clock_comes_off_the_output() -> None:
    spoke_at = T0 - timedelta(seconds=5)

    reason = drive(
        snap(run_accepted_at=T0 - timedelta(minutes=30), run_last_output_at=spoke_at)
    )

    assert reason is not None and reason.kind is TaskDrive.RUN_ACTIVE
    assert reason.expires_at is not None and reason.expires_at > spoke_at + timedelta(
        seconds=SUSPECT
    )
    assert is_live(reason, now=T0), (
        "một lượt chạy vừa nói xong mà bị tính theo hạn giữ thì bị cướp giữa chừng"
    )


# ── 2. two failures that used to look alike (FR-057) ──────────────────────────


async def test_nobody_took_it_is_not_the_same_as_took_it_and_died() -> None:
    booked_at = T0 - timedelta(seconds=30)

    untaken = drive(snap(wake_booked_at=booked_at))
    taken = drive(snap(wake_booked_at=booked_at, run_accepted_at=booked_at))

    assert untaken is not None and untaken.kind is TaskDrive.WAKE_SCHEDULED
    assert taken is not None and taken.kind is TaskDrive.RUN_ACTIVE
    assert untaken.expires_at != taken.expires_at, (
        "hai hỏng hóc khác nhau mà chung một hạn thì vẫn là gộp làm một"
    )


# FR-056b. The work was taken and given back; the task is on the shelf again and the very
# next ask can pick it up. Counting its wait from a booking twenty minutes old would declare
# it dropped at the exact moment it is most ready to be taken.
async def test_work_handed_back_waits_from_when_it_was_handed_back() -> None:
    booked_at = T0 - timedelta(minutes=20)
    handed_back_at = T0 - timedelta(seconds=10)

    reason = drive(snap(wake_booked_at=booked_at, last_taken_at=handed_back_at))

    assert reason is not None and reason.kind is TaskDrive.WAKE_SCHEDULED
    assert is_live(reason, now=T0), "việc vừa trả về kệ mà đã bị tuyên là rơi"
    assert reason.expires_at is not None and reason.expires_at > booked_at


# The re-anchoring only ever moves the clock forward. A booking made *after* the last time
# anything took the work is the later evidence, and it stays the anchor.
async def test_a_booking_newer_than_the_last_hand_back_keeps_its_own_clock() -> None:
    handed_back_at = T0 - timedelta(minutes=20)
    booked_at = T0 - timedelta(seconds=10)

    reason = drive(snap(wake_booked_at=booked_at, last_taken_at=handed_back_at))

    assert reason is not None
    assert reason.expires_at is not None and reason.expires_at > booked_at
    assert is_live(reason, now=T0)


# A task nobody ever booked and nobody ever took has no drive at all, and that is the answer
# the safety net is built to hear. Neither of the two new fields may invent one.
async def test_a_task_nothing_has_touched_still_has_no_drive() -> None:
    assert drive(snap(last_taken_at=T0 - timedelta(seconds=5))) is None


# ── 3. nowhere to start is a wait, not a fault (FR-008a, FR-008e) ─────────────
#
# Read from real rows, because that is the claim: the queue is not something the rules are
# told about, it is something the system looks up.


async def _world(uow_factory):
    workspaces = WorkspaceService(uow_factory)
    ws = await workspaces.create_workspace("WS")
    project = await workspaces.create_project(ws.id, "P")
    await force_phase(uow_factory, project.id)
    agent = await make_agent(uow_factory, workspace_id=ws.id, name="Alice")
    async with uow_factory() as uow:
        session = uow._session  # noqa: SLF001 — the tests' own back door
        workplace_id = (
            await session.execute(
                select(AgentWorkplaceBindingModel.workplace_id).where(
                    AgentWorkplaceBindingModel.marius_id == agent.id
                )
            )
        ).scalar_one()
        machine_id = (
            await session.execute(
                select(WorkplaceModel.machine_id).where(
                    WorkplaceModel.id == workplace_id
                )
            )
        ).scalar_one()
    return ws, project, agent, workplace_id, machine_id


async def _task(uow_factory, project_id, *, title="Việc"):
    tasks = TaskService(
        uow_factory,
        WakeEngine(
            uow_factory,
            InMemoryAdapterRegistry(),
            InMemoryEventBus(),
            run_timeout_seconds=30,
        ),
    )
    return await tasks.create(
        project_id=project_id,
        title=title,
        description="Gom số liệu tháng rồi kết xuất ra tệp bảng tính.",
    )


async def _run_waiting_at(
    uow_factory, *, ws_id, project_id, marius_id, task_id, workplace_id
) -> UUID:
    """A run on the shelf: queued, nobody holding it, waiting at one workplace."""
    async with uow_factory() as uow:
        run = Run(
            project_id=project_id,
            marius_id=marius_id,
            task_id=task_id,
            adapter_type="daemon",
            wake_source=WakeSource.ON_DEMAND,
            status=RunStatus.QUEUED,
            created_at=T0,
        )
        await uow.runs.add(run)
        session = uow._session  # noqa: SLF001
        await session.flush()
        session.add(
            RunClaimModel(
                run_id=run.id, workspace_id=ws_id, workplace_id=workplace_id
            )
        )
        await uow.commit()
    return run.id


async def _held_by(uow_factory, run_id, machine_id, *, until=None) -> None:
    """A hold measured against the real clock, because the queue reads the real clock.

    The rules above take `now` as an argument and so can live at any date; the lookup that
    answers *is this grip still good* cannot, and pinning the fixture to a fictional hour
    would only test which side of midnight the suite happened to run on.
    """
    async with uow_factory() as uow:
        session = uow._session  # noqa: SLF001
        await session.execute(
            update(RunClaimModel)
            .where(RunClaimModel.run_id == run_id)
            .values(
                machine_id=machine_id,
                claimed_at=T0,
                claim_expires_at=until or (utcnow() + timedelta(seconds=HOLD)),
            )
        )
        await uow.commit()


async def _ceiling(uow_factory, machine_id, allowed) -> None:
    async with uow_factory() as uow:
        session = uow._session  # noqa: SLF001
        await session.execute(
            update(MachineModel)
            .where(MachineModel.id == machine_id)
            .values(max_concurrent=allowed)
        )
        await uow.commit()


async def _snapshot(uow_factory, task_id):
    service = PushReasonService(
        uow_factory,
        ProjectService(uow_factory, THRESHOLDS),
        accept_grace_seconds=HOLD,
    )
    async with uow_factory() as uow:
        task = await uow.tasks.get(task_id)
        assert task is not None
        return await service.snapshot(uow, task, now=T0)


async def test_a_task_with_nowhere_to_start_says_what_is_in_its_way(uow_factory) -> None:
    ws, project, agent, workplace_id, machine_id = await _world(uow_factory)
    await _ceiling(uow_factory, machine_id, 1)
    busy = await _task(uow_factory, project.id, title="Việc đang chạy")
    waiting = await _task(uow_factory, project.id, title="Việc đang đợi")
    occupier = await _run_waiting_at(
        uow_factory,
        ws_id=ws.id,
        project_id=project.id,
        marius_id=agent.id,
        task_id=busy.id,
        workplace_id=workplace_id,
    )
    await _held_by(uow_factory, occupier, machine_id)
    await _run_waiting_at(
        uow_factory,
        ws_id=ws.id,
        project_id=project.id,
        marius_id=agent.id,
        task_id=waiting.id,
        workplace_id=workplace_id,
    )

    seen = await _snapshot(uow_factory, waiting.id)
    reason = drive(snap(**{**seen.__dict__, "task_id": waiting.id}))

    assert seen.slots_taken_by == (str(occupier),)
    assert reason is not None and reason.kind is TaskDrive.BLOCKED_BY_TASK
    assert reason.code == BLOCKED_ON_CAPACITY
    assert reason.expires_at is None, (
        "chờ chỗ trống thì không có đồng hồ — thứ chặn nó đã có đồng hồ riêng (FR-008e)"
    )
    assert is_live(reason, now=T0 + timedelta(days=7))


async def test_a_place_with_room_is_not_in_anybodys_way(uow_factory) -> None:
    ws, project, agent, workplace_id, machine_id = await _world(uow_factory)
    await _ceiling(uow_factory, machine_id, 4)
    busy = await _task(uow_factory, project.id, title="Việc đang chạy")
    waiting = await _task(uow_factory, project.id, title="Việc đang đợi")
    occupier = await _run_waiting_at(
        uow_factory,
        ws_id=ws.id,
        project_id=project.id,
        marius_id=agent.id,
        task_id=busy.id,
        workplace_id=workplace_id,
    )
    await _held_by(uow_factory, occupier, machine_id)
    await _run_waiting_at(
        uow_factory,
        ws_id=ws.id,
        project_id=project.id,
        marius_id=agent.id,
        task_id=waiting.id,
        workplace_id=workplace_id,
    )

    seen = await _snapshot(uow_factory, waiting.id)

    assert seen.slots_taken_by == ()


# A hold that has run out is holding nothing — the sweep is on its way to take it back. A
# task told it is blocked by a run whose grip already lapsed is a task waiting on nobody, and
# drive #5 carries no clock, so nothing would ever come and correct it.
async def test_a_lapsed_grip_does_not_block_anybody(uow_factory) -> None:
    ws, project, agent, workplace_id, machine_id = await _world(uow_factory)
    await _ceiling(uow_factory, machine_id, 1)
    busy = await _task(uow_factory, project.id, title="Việc đã chết")
    waiting = await _task(uow_factory, project.id, title="Việc đang đợi")
    occupier = await _run_waiting_at(
        uow_factory,
        ws_id=ws.id,
        project_id=project.id,
        marius_id=agent.id,
        task_id=busy.id,
        workplace_id=workplace_id,
    )
    await _held_by(
        uow_factory, occupier, machine_id, until=utcnow() - timedelta(seconds=1)
    )
    await _run_waiting_at(
        uow_factory,
        ws_id=ws.id,
        project_id=project.id,
        marius_id=agent.id,
        task_id=waiting.id,
        workplace_id=workplace_id,
    )

    seen = await _snapshot(uow_factory, waiting.id)

    assert seen.slots_taken_by == ()


# The other half of what the snapshot reads from real rows: the moment the work was taken,
# which is what turns a queued run into a task the board says is moving (FR-056).
async def test_the_snapshot_reads_the_moment_the_work_was_taken(uow_factory) -> None:
    ws, project, agent, workplace_id, machine_id = await _world(uow_factory)
    task = await _task(uow_factory, project.id)
    run_id = await _run_waiting_at(
        uow_factory,
        ws_id=ws.id,
        project_id=project.id,
        marius_id=agent.id,
        task_id=task.id,
        workplace_id=workplace_id,
    )
    await _held_by(uow_factory, run_id, machine_id)
    async with uow_factory() as uow:
        run = await uow.runs.get(run_id)
        assert run is not None
        run.accepted_at = T0
        await uow.runs.update(run)
        await uow.commit()

    seen = await _snapshot(uow_factory, task.id)

    assert seen.run_accepted_at == T0
    assert seen.last_taken_at == T0


# ── 4. the shape of the wait survives onto the task (FR-008b, T055) ───────────
#
# `blocked_by_task` covers two waits that are answered differently. *Behind another task* is
# answered by going and chasing that task; *waiting for a free machine* is answered by
# leaving it alone, because nothing is wrong. The rule has told them apart since spec 001 —
# but the task carried only the drive's kind, so the difference was computed and dropped, and
# the board could not name the state FR-008b asks for by name.


async def _on_the_board(uow_factory, task_id) -> None:
    """Move a task out of the backlog.

    The safety net has no opinion about a shelved task, and neither does the drive: a task
    nobody has scheduled is not one the system dropped. So every question about *what is
    moving this* only starts being asked once the task is on the board.
    """
    async with uow_factory() as uow:
        task = await uow.tasks.get(task_id)
        assert task is not None
        task.status = TaskStatus.TODO
        await uow.tasks.update(task)
        await uow.commit()


async def _refresh(uow_factory, task_id):
    """Settle one task's drive the way the system does, and read the task back."""
    service = PushReasonService(
        uow_factory,
        ProjectService(uow_factory, THRESHOLDS),
        accept_grace_seconds=HOLD,
    )
    async with uow_factory() as uow:
        task = await uow.tasks.get(task_id)
        assert task is not None
        await service.refresh_in(uow, task, now=utcnow())
        await uow.commit()
    async with uow_factory() as uow:
        return await uow.tasks.get(task_id)


async def _jam(uow_factory):
    """One machine allowed a single run, with that run held and a second one waiting."""
    ws, project, agent, workplace_id, machine_id = await _world(uow_factory)
    await _ceiling(uow_factory, machine_id, 1)
    busy = await _task(uow_factory, project.id, title="Việc đang chạy")
    waiting = await _task(uow_factory, project.id, title="Việc đang đợi")
    occupier = await _run_waiting_at(
        uow_factory,
        ws_id=ws.id,
        project_id=project.id,
        marius_id=agent.id,
        task_id=busy.id,
        workplace_id=workplace_id,
    )
    await _held_by(uow_factory, occupier, machine_id)
    await _run_waiting_at(
        uow_factory,
        ws_id=ws.id,
        project_id=project.id,
        marius_id=agent.id,
        task_id=waiting.id,
        workplace_id=workplace_id,
    )
    await _on_the_board(uow_factory, waiting.id)
    return project, waiting, occupier, machine_id


async def test_waiting_for_a_free_machine_is_written_onto_the_task(uow_factory) -> None:
    _project, waiting, _occupier, _machine = await _jam(uow_factory)

    task = await _refresh(uow_factory, waiting.id)

    assert task is not None
    assert task.drive is TaskDrive.BLOCKED_BY_TASK
    assert task.drive_code == BLOCKED_ON_CAPACITY, (
        "đầu việc đang chờ máy rảnh mà trên bảng không đọc ra được nó đang chờ gì"
    )
    assert task.drive_expires_at is None, "chờ chỗ trống thì không đeo đồng hồ (FR-008e)"


async def test_the_two_waits_are_told_apart_on_the_task_itself(uow_factory) -> None:
    """Cùng một loại động cơ, hai cái chờ khác hẳn nhau.

    Chờ một đầu việc khác thì đi giục bên kia; chờ máy rảnh thì để yên, vì không có gì
    hỏng. Cùng hiện ra một câu là dạy người đọc bảng đi làm sai việc.
    """
    ws, project, _agent, _workplace, _machine = await _world(uow_factory)
    blocker = await _task(uow_factory, project.id, title="Việc chặn")
    waiting = await _task(uow_factory, project.id, title="Việc bị chặn")
    tasks = TaskService(
        uow_factory,
        WakeEngine(
            uow_factory,
            InMemoryAdapterRegistry(),
            InMemoryEventBus(),
            run_timeout_seconds=30,
        ),
    )
    await tasks.add_dependency(waiting.id, blocker.id)
    await _on_the_board(uow_factory, waiting.id)

    task = await _refresh(uow_factory, waiting.id)

    assert task is not None
    assert task.drive is TaskDrive.BLOCKED_BY_TASK
    assert task.drive_code == BLOCKED_ON_TASK, task.drive_code


async def test_the_shape_goes_away_with_the_wait(uow_factory) -> None:
    """Cái chờ hết thì hình dạng của nó cũng phải hết.

    Động cơ số 5 không có đồng hồ, nên không có gì tự đến sửa một cái nhãn cũ nằm lại: nó
    sẽ ở đó tới hết đời đầu việc, và bảng sẽ trả lời một câu hỏi không còn ai hỏi.
    """
    _project, waiting, occupier, machine_id = await _jam(uow_factory)
    settled = await _refresh(uow_factory, waiting.id)
    assert settled is not None and settled.drive_code == BLOCKED_ON_CAPACITY

    await _ceiling(uow_factory, machine_id, 4)  # the jam clears
    task = await _refresh(uow_factory, waiting.id)

    assert task is not None
    assert task.drive_code is None, task.drive_code
