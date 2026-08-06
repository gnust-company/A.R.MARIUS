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
from armarius.domain.entities.task import Task
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
    ) -> None:
        self._uow = uow_factory
        self._projects = projects
        self._clock = clock

    # ── reading ──────────────────────────────────────────────────────────────────
    async def snapshot(
        self, uow: UnitOfWork, task: Task, *, now: datetime
    ) -> DriveSnapshot:
        """Gather what the pure rule needs about one task, from four other tables.

        The expensive half of the feature, which is why it runs at task-change time rather
        than per sweep. ``recovery_retry_at`` comes from the ladder row: a delivery that is
        being retried is a live drive (FR-063), and the ladder is where the retry clock is.
        """
        runs = await uow.runs.list_by_task(task.id)
        # The newest sign of life across every live run on this task. A run with no
        # timestamps at all is skipped rather than dated to the epoch — an undated run
        # is not evidence of work, and treating it as ancient would flag a task the
        # instant a run row was inserted but not yet started.
        run_marks = [
            stamp
            for r in runs
            if r.status in ACTIVE_RUN_STATUSES
            and (stamp := as_utc(r.last_output_at or r.started_at or r.created_at))
            is not None
        ]
        live_run_output = max(run_marks) if run_marks else None

        pending_wakes = await uow.wakeups.list_pending_for_task(task.id)
        # Oldest pending wake: if several are queued, the one that has been waiting
        # longest is the one whose failure to fire says the most.
        wake_marks = [
            stamp for w in pending_wakes if (stamp := as_utc(w.created_at)) is not None
        ]
        wake_booked = min(wake_marks) if wake_marks else None

        inbox = await uow.inbox.list_pending_for_task(task.id)
        blockers = await uow.dependencies.list_unfinished_blockers(task.id)
        ladder = await uow.push_reasons.get_for_task(task.id)

        return DriveSnapshot(
            task_id=task.id,
            status=task.status,
            run_last_output_at=live_run_output,
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
            recovery_retry_at=as_utc(ladder.next_retry_at) if ladder else None,
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
        )

        task.drive = reason.kind if reason else None
        task.drive_expires_at = reason.expires_at if reason else None
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
