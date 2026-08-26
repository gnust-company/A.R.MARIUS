"""Keeping each task's drive honest — the single writer (spec 001 FR-056, QĐ-4).

`push_reason_rules` decides *which* drive a task has; this decides *when* anyone asks. The
answer is: at the moments the task changes, and never inside the sweep's hot loop.

That split is the whole performance story of the safety net. A drive is derived from four
other tables — runs, wakes, inbox items, dependency edges — so deriving it costs several
round trips. The use cases already know when they booked a wake or parked on a patron, so
they say so; the sweep then answers "is this task still moving?" by comparing one stored
timestamp against now, over an index, with no join at all.

Everything that writes `task.drive` goes through here. One writer, so the field cannot come
to mean two different things in two call sites — which is exactly what happened to the
signature round number this codebase already had to unpick once.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from armarius.application.ports.unit_of_work import UnitOfWork
from armarius.application.use_cases.projects import ProjectService
from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.inbox_item import InboxItemStatus
from armarius.domain.entities.run import ACTIVE_RUN_STATUSES
from armarius.domain.entities.task import Task, TaskDrive
from armarius.domain.services.push_reason_rules import (
    DriveSnapshot,
    PushReason,
    infer_drive,
    is_live,
    stall_reason,
    watches,
)
from armarius.shared.clock import as_utc, utcnow
from armarius.shared.logging import get_logger

logger = get_logger(__name__)


class PushReasonService:
    def __init__(
        self,
        uow_factory: UowFactory,
        projects: ProjectService,
        *,
        clock: Callable[[], datetime] = utcnow,
        accept_grace_seconds: int,
    ) -> None:
        self._uow = uow_factory
        self._projects = projects
        self._clock = clock
        # How long work stays *accepted but not yet started* before the drive on it dies.
        # Handed in rather than read here: it is the same number the hold on the work is
        # written with, and FR-056c forbids the two being tuned apart. The one place that
        # can guarantee they are the same number is the place that wires both.
        self._accept_grace = accept_grace_seconds

    # ── reading ──────────────────────────────────────────────────────────────────
    async def snapshot(
        self, uow: UnitOfWork, task: Task, *, now: datetime
    ) -> DriveSnapshot:
        """Gather what the pure rule needs about one task, from four other tables.

        The expensive half of the feature, which is why it runs at task-change time rather
        than per sweep.
        """
        runs = await uow.runs.list_by_task(task.id)
        # The newest sign of life across every live run on this task. *Work has happened* is
        # the only thing this measures, so a run that has neither spoken nor started
        # contributes nothing — it is not evidence of work, it is a run waiting to become
        # one.
        #
        # This used to fall back to the moment the row was inserted, to stop a freshly
        # written run from reading as a task nobody was moving. That fallback is no longer
        # needed and is now actively wrong: *somebody has the work* has a field of its own
        # below (FR-056), which covers the same gap honestly. Kept, it would also swallow the
        # case underneath it — a run waiting for a free slot would report itself as a live
        # run, and the task would never be seen waiting for room at all (FR-008a).
        run_marks = [
            stamp
            for r in runs
            if r.status in ACTIVE_RUN_STATUSES
            and (stamp := as_utc(r.last_output_at or r.started_at)) is not None
        ]
        live_run_output = max(run_marks) if run_marks else None

        # When a runtime took the newest live run. Read separately from the marks above
        # because it answers a different question: those say *work has been happening*, this
        # says *somebody has the work*, and between the two lies the whole of getting ready
        # (FR-056). A run with no timestamps at all is skipped up there for good reason; the
        # same run may still have been accepted a second ago, and dropping that would leave
        # the task looking unclaimed while a machine is setting it up.
        accept_marks = [
            stamp
            for r in runs
            if r.status in ACTIVE_RUN_STATUSES
            and (stamp := as_utc(r.accepted_at)) is not None
        ]
        accepted = max(accept_marks) if accept_marks else None

        # Both queue answers in one read: what is filling every slot this task could start
        # in, and when its work was last taken. Asked apart they are two readings of one
        # queue at two moments, and the drive and its deadline could then disagree.
        queued = await uow.queue.position_of(task.id)

        pending_wakes = await uow.wakeups.list_pending_for_task(task.id)
        # Oldest pending wake: if several are queued, the one that has been waiting
        # longest is the one whose failure to fire says the most.
        wake_marks = [
            stamp for w in pending_wakes if (stamp := as_utc(w.created_at)) is not None
        ]
        wake_booked = min(wake_marks) if wake_marks else None

        inbox = await uow.inbox.list_pending_for_task(task.id)
        blockers = await uow.dependencies.list_unfinished_blockers(task.id)

        return DriveSnapshot(
            task_id=task.id,
            status=task.status,
            run_last_output_at=live_run_output,
            run_accepted_at=accepted,
            slots_taken_by=queued.runs_filling_every_slot,
            last_taken_at=queued.last_taken_at,
            wake_booked_at=wake_booked,
            patron_item_pending=any(
                i.status is InboxItemStatus.PENDING for i in inbox
            ),
            unmet_blockers=tuple(b.identifier or str(b.id) for b in blockers),
            # A task parked until a date is parked in *blocked*: a deadline on a task that
            # is being worked on is a deadline, not a reason to stop. Reading `due_date` on
            # any other status would call every scheduled task "waiting on the outside
            # world" and silence the alarm on exactly the tasks that need it.
            external_due_at=as_utc(task.due_date) if task.status.value == "blocked" else None,
            # Read back off the task, **not** off the recovery ladder. Those are two
            # different clocks, and conflating them undoes FR-058 entirely: the watchdog
            # flags a dropped task, the ladder books its next Level-1 attempt, and the very
            # next sweep reads that booking as a live drive and lowers the flag again. The
            # alarm then flickers, and the board shows a dropped task as healthy most of
            # the time. That is not a subtle regression — it is the feature not working.
            #
            # A task the safety net is retrying **is** stalled: the retry is the response
            # to the stall, not evidence against it. What FR-063 calls *waiting on
            # recovery* is narrower — a wake that could not be **delivered**, where the
            # work is fine and the transport is not. Whoever fails to deliver says so on
            # the task, and it is read back here.
            recovery_retry_at=(
                as_utc(task.drive_expires_at)
                if task.drive is TaskDrive.WAITING_RECOVERY
                else None
            ),
        )

    # ── writing ──────────────────────────────────────────────────────────────────
    async def refresh_in(
        self, uow: UnitOfWork, task: Task, *, now: datetime | None = None
    ) -> PushReason | None:
        """Recompute this task's drive and write it onto the task, inside the caller's
        transaction. Returns the drive, or None when nothing is moving the task.

        Clearing the stall flag is part of the same write on purpose: a task that has
        regained a live drive is no longer dropped, and leaving the alarm up would train
        the reader to ignore it. Raising the flag is **not** done here — that belongs to the
        sweep, which also owes the record an entry and the project a notification.
        """
        now = now or self._clock()
        if not watches(task.status):
            # Closed, drafted or shelved: no drive, no alarm, and no leftover ladder.
            task.drive = None
            task.drive_expires_at = None
            task.drive_code = None
            task.stalled = False
            task.stalled_reason = None
            await uow.tasks.update(task)
            await uow.push_reasons.clear_for_task(task.id)
            return None

        thresholds = (
            await self._projects.get_thresholds(task.project_id)
            if task.project_id
            else None
        )
        snap = await self.snapshot(uow, task, now=now)
        reason = infer_drive(
            snap,
            now=now,
            hang_suspect_seconds=thresholds.hang_suspect_seconds if thresholds else 600,
            hang_grace_seconds=thresholds.hang_grace_seconds if thresholds else 120,
            accept_grace_seconds=self._accept_grace,
        )

        task.drive = reason.kind if reason else None
        task.drive_expires_at = reason.expires_at if reason else None
        task.drive_code = reason.code if reason else None
        if reason is not None and is_live(reason, now=now):
            task.stalled = False
            task.stalled_reason = None
        task.updated_at = task.updated_at or now
        await uow.tasks.update(task)
        return reason

    async def refresh(self, task_id: UUID, *, now: datetime | None = None) -> None:
        """Recompute one task's drive in its own transaction.

        For callers that have already committed — a wake engine that just opened a run, a
        watchdog that just reaped one. A failure here is logged and swallowed: a drive that
        is briefly stale gets corrected by the very next sweep, whereas an exception thrown
        back into a wake path would abandon work that had already succeeded.
        """
        try:
            async with self._uow() as uow:
                task = await uow.tasks.get(task_id)
                if task is None:
                    return
                await self.refresh_in(uow, task, now=now)
                await uow.commit()
        except Exception:  # pragma: no cover - never break the caller's real work
            logger.exception("could not refresh the push reason for task %s", task_id)

    @staticmethod
    def verdict(reason: PushReason | None, *, now: datetime) -> str | None:
        """Why this task counts as stalled, or None when it does not. Thin passthrough so
        callers need not import the rule module for one line."""
        return stall_reason(reason, now=now)
