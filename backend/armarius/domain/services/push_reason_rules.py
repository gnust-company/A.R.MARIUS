"""Động cơ đẩy — what is going to move this task forward, as pure rules (FR-056, FR-058).

Every task the board is actually running carries exactly one **drive**: the single thing
that is going to touch it next. Six kinds, and the list is closed on purpose — if a
situation fits none of them, the task is not "in some other state", it has been *dropped*,
and that is precisely what the safety net is looking for.

The value of stating it this way is that "is this task still moving?" stops being a
judgement call spread across six use cases and becomes one comparison the sweep can make
cheaply: is there a drive, and is its deadline still ahead of now.

Two design decisions worth keeping straight:

**Drives are computed at the moments the task changes, not inside the sweep** (QĐ-4). The
sweep is a backstop that runs forever on every open task; making it re-derive each drive
would put a fan-out of lookups on the hot path. The use cases already know when they
booked a wake or parked on a patron — they say so, and the sweep only compares a timestamp.

**Not every drive has a clock.** A wait on a patron ends when the patron answers, chased by
the three-tier reminder ladder (FR-065); a wait on another task ends when that task moves,
and *that* task has a drive row of its own. Inventing a deadline for either would create a
second alarm competing with the one already watching, and the two would disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from armarius.domain.entities.task import TaskDrive, TaskStatus

# The statuses the safety net watches. *Done* and *cancelled* are finished with; a *draft*
# is the Leader's own proposal waiting on a decision, and *backlog* is shelved deliberately
# — neither of those was dropped by the system, and an alarm that fires on every shelved
# item is an alarm that gets muted.
WATCHED_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.IN_REVIEW, TaskStatus.BLOCKED}
)

# How long a booked wake has to become a run before the net stops believing in it. A wake
# that sat in the queue this long is not going to fire; something ate it.
_WAKE_GRACE = timedelta(minutes=10)

# How long a *provisional* drive is believed. See `provisional_drive`.
_PROVISIONAL_GRACE = timedelta(minutes=10)


@dataclass(frozen=True)
class DriveSnapshot:
    """One task as the drive rules see it.

    Deliberately not the ``Task`` entity: every field after ``status`` is an answer about
    some *other* table, and passing the entity would either hide those lookups inside the
    rule or leave the rule unable to ask them.
    """

    task_id: UUID
    status: TaskStatus
    # When the live run on this task last emitted anything. None → no run is live.
    run_last_output_at: datetime | None
    # When a wake was queued for this task and has not opened a run yet.
    wake_booked_at: datetime | None
    # Whether an inbox item for this task is still waiting on a patron.
    patron_item_pending: bool
    # Identifiers of `blocked_by` tasks that are not finished.
    unmet_blockers: tuple[str, ...]
    # A date the task is legitimately parked until (an outside party, a scheduled event).
    external_due_at: datetime | None
    # When the next delivery retry is due, while a wake is failing to reach the agent.
    recovery_retry_at: datetime | None


@dataclass(frozen=True)
class PushReason:
    """The drive on one task: what is moving it, and until when.

    ``expires_at`` of None means *this drive does not expire on a clock* — see the module
    docstring. It does not mean "expired" and it does not mean "forever unchecked".
    """

    kind: TaskDrive
    expires_at: datetime | None = None
    # What the drive points at, when it points at something: the blocking task, the inbox
    # item, the run. Kept as text because the six kinds reference four different tables and
    # a typed foreign key to "one of four things" is a worse lie than a label.
    ref: str | None = None


def watches(status: TaskStatus) -> bool:
    """Whether the safety net has an opinion about a task in this status."""
    return status in WATCHED_STATUSES


def is_live(reason: PushReason, *, now: datetime) -> bool:
    """Whether this drive is still believable at ``now``."""
    return reason.expires_at is None or reason.expires_at > now


def infer_drive(
    snap: DriveSnapshot,
    *,
    now: datetime,
    hang_suspect_seconds: int,
    hang_grace_seconds: int,
) -> PushReason | None:
    """The one drive on this task, or None when nothing is going to move it.

    The order below is precedence, and it is not arbitrary: more than one of these can be
    true at once (a wake books, the run starts, the wake row lingers), and the answer has
    to be the thing *actually* moving the task, because the deadline comes from it. Pick
    the stale wake over the live run and a healthy long-running task trips the alarm ten
    minutes in.

    Returning a reason does not mean the task is healthy — a drive can come back already
    expired, which is how a reaped run is told apart from a run that was never there.
    """
    # 1. Someone is literally working on it. The deadline is the hung-run reaper's own:
    #    suspicion plus grace. The stall net sits *behind* that reaper, so its patience has
    #    to outlast it, or every healthy long run reads as dropped.
    if snap.run_last_output_at is not None:
        return PushReason(
            kind=TaskDrive.RUN_ACTIVE,
            expires_at=snap.run_last_output_at
            + timedelta(seconds=hang_suspect_seconds + hang_grace_seconds),
        )

    # 2. A delivery retry is in flight. FR-063 says this explicitly must not count as
    #    stalled — the system is already doing something about it. Ranked above the waits
    #    below because it is the one with a clock ticking on it right now.
    if snap.recovery_retry_at is not None and snap.recovery_retry_at > now:
        return PushReason(
            kind=TaskDrive.WAITING_RECOVERY, expires_at=snap.recovery_retry_at
        )

    # 3. A wake is booked and has not opened a run yet.
    if snap.wake_booked_at is not None:
        return PushReason(
            kind=TaskDrive.WAKE_SCHEDULED, expires_at=snap.wake_booked_at + _WAKE_GRACE
        )

    # 4. Parked on a human. No clock here — the reminder ladder chases it (FR-065).
    if snap.patron_item_pending:
        return PushReason(kind=TaskDrive.WAITING_PATRON)

    # 5. Parked on another task. No clock here either — that task has a drive of its own,
    #    and if *it* stalls, the alarm rings there, where someone can act on it.
    if snap.unmet_blockers:
        return PushReason(
            kind=TaskDrive.BLOCKED_BY_TASK, ref=", ".join(snap.unmet_blockers)
        )

    # 6. Parked until a date. Once that date passes with nothing having happened, the wait
    #    stops being a wait: the drive comes back expired rather than absent, so the record
    #    can still say *what* it was waiting for.
    if snap.external_due_at is not None:
        return PushReason(
            kind=TaskDrive.WAITING_EXTERNAL, expires_at=snap.external_due_at
        )

    return None


def provisional_drive(status: TaskStatus, *, now: datetime) -> PushReason | None:
    """The drive a status *implies*, written the instant the status changes.

    A status change and the thing that will act on it do not happen together: a task enters
    *todo*, and the wake that will carry it is booked a few lines later, after the
    transaction commits. Between those two moments `infer_drive` would honestly answer
    "nothing is moving this" — and a sweep landing in that window would raise an alarm on a
    task that is perfectly fine.

    So the status leaves behind a placeholder, and the placeholder **always carries a
    clock**, even for the two kinds whose real form has none. That is the point: this is a
    guess about a setup still in progress, not a verified wait. Ten minutes later either the
    authoritative refresh has replaced it with something real, or nothing ever did the setup
    — and the second case is exactly the dropped task the net is for. Leaving a provisional
    drive un-clocked would make "moved to *blocked* and forgotten" invisible forever, which
    is the failure mode this feature exists to close.
    """
    if status not in WATCHED_STATUSES:
        return None
    expires = now + _PROVISIONAL_GRACE
    if status is TaskStatus.BLOCKED:
        return PushReason(kind=TaskDrive.BLOCKED_BY_TASK, expires_at=expires)
    if status is TaskStatus.IN_PROGRESS:
        return PushReason(kind=TaskDrive.RUN_ACTIVE, expires_at=expires)
    if status is TaskStatus.IN_REVIEW:
        return PushReason(kind=TaskDrive.WAITING_PATRON, expires_at=expires)
    return PushReason(kind=TaskDrive.WAKE_SCHEDULED, expires_at=expires)


def stall_reason(reason: PushReason | None, *, now: datetime) -> str | None:
    """Why this task counts as stalled, in words a person can act on — or None if it does not.

    The wording matters more than it looks. "Đình trệ" on its own sends the reader hunting
    through four tables; naming which drive ran out, or that there was never one, points
    them at the thing to fix.
    """
    if reason is None:
        return "không có gì được hẹn để đẩy đầu việc này đi tiếp"
    if is_live(reason, now=now):
        return None
    return _EXPIRED_WORDING.get(reason.kind, f"động cơ đẩy '{reason.kind}' đã quá hạn")


_EXPIRED_WORDING: dict[TaskDrive, str] = {
    TaskDrive.RUN_ACTIVE: "lượt chạy trên đầu việc này đã im quá cả cửa sổ ân hạn",
    TaskDrive.WAKE_SCHEDULED: "lệnh đánh thức đã hẹn nhưng không mở được lượt chạy nào",
    TaskDrive.WAITING_RECOVERY: "đã hết hạn chờ lần thử lại mà không có lần nào tới nơi",
    TaskDrive.WAITING_EXTERNAL: "mốc bên ngoài đã trôi qua mà không có gì xảy ra",
}
