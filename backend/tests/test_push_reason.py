"""Động cơ đẩy — what is going to move this task forward, as a pure rule (FR-056, FR-058).

The whole safety net rests on one invariant: **every task the board is actually running
either has a live drive or carries the stall flag — never neither, and never both.** Get
that right and a dropped task is a query away; get it wrong and a task can sit in
*in_progress* forever while every dashboard reports a healthy project.

These are pure-function tests off a fixed clock. No database, no loop.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from armarius.domain.entities.task import TaskDrive, TaskStatus
from armarius.domain.services.push_reason_rules import (
    DriveSnapshot,
    infer_drive,
    is_live,
    stall_reason,
    watches,
)

T0 = datetime(2026, 3, 1, 9, 0, 0, tzinfo=UTC)
SUSPECT = 600  # ngưỡng nghi treo, giây
GRACE = 120  # cửa sổ ân hạn, giây


def snap(**over: object) -> DriveSnapshot:
    """A task with nothing moving it — every test adds back exactly what it is about."""
    base: dict[str, object] = {
        "task_id": uuid4(),
        "status": TaskStatus.IN_PROGRESS,
        "run_last_output_at": None,
        "wake_booked_at": None,
        "patron_item_pending": False,
        "unmet_blockers": (),
        "external_due_at": None,
        "recovery_retry_at": None,
    }
    base.update(over)
    return DriveSnapshot(**base)  # type: ignore[arg-type]


def drive_of(s: DriveSnapshot) -> TaskDrive | None:
    reason = infer_drive(s, now=T0, hang_suspect_seconds=SUSPECT, hang_grace_seconds=GRACE)
    return reason.kind if reason else None


# ── sáu loại, mỗi loại một tình cảnh ────────────────────────────────────────────


def test_a_live_run_is_the_drive() -> None:
    assert drive_of(snap(run_last_output_at=T0 - timedelta(seconds=30))) is TaskDrive.RUN_ACTIVE


def test_a_booked_wake_is_the_drive() -> None:
    assert drive_of(snap(wake_booked_at=T0 - timedelta(seconds=5))) is TaskDrive.WAKE_SCHEDULED


def test_a_pending_patron_decision_is_the_drive() -> None:
    assert drive_of(snap(patron_item_pending=True)) is TaskDrive.WAITING_PATRON


def test_an_unfinished_blocker_is_the_drive() -> None:
    s = snap(status=TaskStatus.BLOCKED, unmet_blockers=("CALC-3",))
    assert drive_of(s) is TaskDrive.BLOCKED_BY_TASK


def test_an_outside_date_is_the_drive() -> None:
    s = snap(status=TaskStatus.BLOCKED, external_due_at=T0 + timedelta(days=2))
    assert drive_of(s) is TaskDrive.WAITING_EXTERNAL


def test_a_retry_in_flight_is_the_drive() -> None:
    """A wake that could not be delivered is being retried — that is a live drive, and
    FR-063 says explicitly it must not read as stalled."""
    s = snap(recovery_retry_at=T0 + timedelta(seconds=90))
    assert drive_of(s) is TaskDrive.WAITING_RECOVERY


# ── không có gì đẩy ─────────────────────────────────────────────────────────────


def test_a_task_with_nothing_moving_it_has_no_drive() -> None:
    """This is the whole point of the feature: *in_progress*, assigned, and not one thing
    scheduled to touch it again. Nothing else in the schema tells this apart from a task
    that is being worked on."""
    assert drive_of(snap()) is None


def test_a_task_waiting_on_a_date_already_past_is_not_driven_but_still_says_why() -> None:
    """The date came and went and nobody acted. That is a dropped task, not a waiting one.

    The kind survives on purpose: an expired drive is more useful than an absent one,
    because the alarm can then name *what* the task was waiting for instead of shrugging.
    """
    s = snap(status=TaskStatus.BLOCKED, external_due_at=T0 - timedelta(hours=1))
    reason = infer_drive(s, now=T0, hang_suspect_seconds=SUSPECT, hang_grace_seconds=GRACE)
    assert reason is not None and reason.kind is TaskDrive.WAITING_EXTERNAL
    assert is_live(reason, now=T0) is False
    assert stall_reason(reason, now=T0), "đình trệ mà không nói được vì sao"


# ── thứ tự ưu tiên ──────────────────────────────────────────────────────────────


def test_a_live_run_outranks_a_booked_wake() -> None:
    """Both can be true at once — a wake books, the run starts, the row lingers. What is
    *actually* moving it is the run, and the expiry has to be the run's, not the wake's."""
    s = snap(
        run_last_output_at=T0 - timedelta(seconds=30),
        wake_booked_at=T0 - timedelta(seconds=120),
    )
    assert drive_of(s) is TaskDrive.RUN_ACTIVE


def test_a_retry_outranks_a_patron_wait() -> None:
    """A task parked on a patron whose wake also failed to send is, right now, waiting on
    the retry: that is the thing with a clock on it."""
    s = snap(patron_item_pending=True, recovery_retry_at=T0 + timedelta(seconds=60))
    assert drive_of(s) is TaskDrive.WAITING_RECOVERY


# ── mốc hết hạn: vòng quét chỉ so mốc này với hiện tại ──────────────────────────


def test_a_live_run_expires_after_suspicion_plus_grace() -> None:
    """The stall sweep is the backstop *behind* the hung-run reaper, so its deadline must
    sit past the reaper's. Any earlier and every healthy long run trips the alarm."""
    last = T0 - timedelta(seconds=30)
    reason = infer_drive(
        snap(run_last_output_at=last),
        now=T0,
        hang_suspect_seconds=SUSPECT,
        hang_grace_seconds=GRACE,
    )
    assert reason is not None
    assert reason.expires_at == last + timedelta(seconds=SUSPECT + GRACE)


def test_a_drive_past_its_expiry_is_not_live() -> None:
    reason = infer_drive(
        snap(run_last_output_at=T0 - timedelta(seconds=SUSPECT + GRACE + 60)),
        now=T0,
        hang_suspect_seconds=SUSPECT,
        hang_grace_seconds=GRACE,
    )
    assert reason is not None, "vẫn suy ra được loại — nhưng nó đã quá hạn"
    assert is_live(reason, now=T0) is False


@pytest.mark.parametrize(
    "kind_setup", [{"patron_item_pending": True}, {"unmet_blockers": ("X-1",)}]
)
def test_waits_owned_by_someone_else_have_no_clock(kind_setup: dict[str, object]) -> None:
    """Two drives deliberately never expire on a clock: a patron wait is chased by the
    three-tier reminder ladder (FR-065), and a blocked-by wait ends when the blocking task
    moves — and *that* task has a row of its own. Giving either an arbitrary deadline would
    invent a second, competing alarm for something already watched."""
    s = snap(status=TaskStatus.BLOCKED, **kind_setup)  # type: ignore[arg-type]
    reason = infer_drive(s, now=T0, hang_suspect_seconds=SUSPECT, hang_grace_seconds=GRACE)
    assert reason is not None
    assert reason.expires_at is None
    assert is_live(reason, now=T0 + timedelta(days=30)) is True


# ── đầu việc nào được canh ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "status",
    [TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.IN_REVIEW, TaskStatus.BLOCKED],
)
def test_the_net_watches_work_that_is_supposed_to_be_moving(status: TaskStatus) -> None:
    assert watches(status) is True


@pytest.mark.parametrize(
    "status",
    [TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.DRAFT, TaskStatus.BACKLOG],
)
def test_the_net_leaves_alone_what_a_human_parked_on_purpose(status: TaskStatus) -> None:
    """*Done* and *cancelled* are finished. A *draft* is the Leader's proposal awaiting a
    decision, and *backlog* is shelved deliberately — neither was dropped by the system, and
    an alarm that fires on every shelved item is an alarm nobody reads."""
    assert watches(status) is False


# ── bất biến ────────────────────────────────────────────────────────────────────


def test_every_watched_task_is_either_driven_or_stalled_and_the_verdict_is_the_right_one() -> None:
    """The invariant, stated over a board holding one of every situation at once.

    Written as a sweep with the expected verdict spelled out beside each case, rather than
    one assertion per case: the failure this guards against is a *gap* between the cases,
    and a gap is invisible when each case is checked alone. The expected verdicts are what
    stops it collapsing into a tautology — "driven or stalled" is true of any classifier;
    "driven **here** and stalled **there**" is not.
    """
    board: list[tuple[str, DriveSnapshot, bool]] = [
        ("đang có lượt chạy", snap(run_last_output_at=T0 - timedelta(seconds=30)), True),
        ("đã hẹn đánh thức", snap(wake_booked_at=T0 - timedelta(seconds=5)), True),
        ("chờ người chủ", snap(patron_item_pending=True), True),
        (
            "bị chặn bởi việc khác",
            snap(status=TaskStatus.BLOCKED, unmet_blockers=("CALC-3",)),
            True,
        ),
        (
            "chờ mốc bên ngoài",
            snap(status=TaskStatus.BLOCKED, external_due_at=T0 + timedelta(days=2)),
            True,
        ),
        ("chờ hành động phục hồi", snap(recovery_retry_at=T0 + timedelta(seconds=90)), True),
        ("đang làm mà không ai hẹn quay lại", snap(), False),
        ("chờ làm mà không ai hẹn quay lại", snap(status=TaskStatus.TODO), False),
        (
            "lượt chạy đã quá cả ân hạn",
            snap(run_last_output_at=T0 - timedelta(seconds=SUSPECT + GRACE + 60)),
            False,
        ),
        (
            "mốc bên ngoài đã trôi qua",
            snap(status=TaskStatus.BLOCKED, external_due_at=T0 - timedelta(hours=1)),
            False,
        ),
    ]
    for label, s, expected_driven in board:
        assert watches(s.status), "bài kiểm này chỉ nói về đầu việc đang được canh"
        reason = infer_drive(
            s, now=T0, hang_suspect_seconds=SUSPECT, hang_grace_seconds=GRACE
        )
        driven = reason is not None and is_live(reason, now=T0)
        wanted = "còn động cơ đẩy" if expected_driven else "phải nổi cờ đình trệ"
        assert driven is expected_driven, (
            f"'{label}': đáng lẽ {wanted}, nhưng luật trả về {reason}"
        )
