"""The stall watchdog — the loop that notices a task nobody is going to touch again.

Everything else in this system moves work because something *asked* it to: a patron
assigns, an agent finishes, a review sends work back. That leaves one shape uncovered, and
it is the one that costs a project a week: nothing asked, because the thing that was going
to ask died. A run crashes mid-turn. A wake never reaches the gateway. The process
restarts holding a timer that lived in memory. The task stays in *in_progress*, the board
looks healthy, and no query in the schema can tell that apart from work in progress.

So every watched task carries a **drive** — what is going to touch it next, and until when
(FR-056) — and this loop is the backstop that checks the clock on it (FR-057). Two passes,
deliberately unequal:

  * **the cheap scan** is one indexed query on `tasks`: watched status, and either no drive,
    a drive past its deadline, or a flag already raised. On a healthy project it returns
    nothing, and that is the common case by an enormous margin — this runs every minute,
    forever, on every project. The third clause is what gives an alarm a way back *down*:
    without it a task that recovers gains a live drive, falls out of the scan, and keeps a
    red flag on the board for good.
  * **the real check** re-derives the drive from live state, but only for what the scan
    flagged. The stored drive is a cached decision and can be stale in the *good*
    direction: a run may have started since. Raising an alarm off the cache alone would
    cry wolf, and an alarm that cries wolf is an alarm that gets muted.

What survives both passes is a task the system dropped. It gets the flag, a line in the
task's own history, a push on the project channel, and a rung on the recovery ladder
(FR-058, FR-059). The flag also seals the door into *done* — enforced in the entity, not
here, because that gate has to hold against every caller and not just this one.

Built to the same shape as ``LivenessWatchdog`` and ``OrchestrationLoop``: one background
task cancelled on shutdown, with the body callable on its own so tests drive it off a fixed
clock instead of waiting for real seconds.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from armarius.application.use_cases.inbox import InboxService
from armarius.application.use_cases.push_reason import PushReasonService
from armarius.application.use_cases.task_log import TaskLogService
from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.task import Task
from armarius.domain.entities.task_log import ActorKind, TaskLogKind
from armarius.domain.services.push_reason_rules import is_live, stall_reason
from armarius.infrastructure.events.topic_bus import TopicEventBus, project_topic
from armarius.shared.clock import utcnow
from armarius.shared.logging import get_logger

logger = get_logger(__name__)

EVENT_TASK_STALLED = "dau-viec.dinh-tre"


class RecoveryLadder(Protocol):
    """What the watchdog hands a dropped task to (FR-059).

    Detection and recovery are split on purpose: this loop's whole job is deciding that a
    task has been dropped, and it must keep doing that even if every recovery route is
    broken. A missing ladder degrades the feature to "the flag is raised and recorded",
    which is still strictly better than silence.
    """

    async def climb(self, task: Task, *, cause: str, now: datetime) -> None: ...


class StallWatchdog:
    def __init__(
        self,
        uow_factory: UowFactory,
        push_reasons: PushReasonService,
        *,
        task_log: TaskLogService,
        control_bus: TopicEventBus,
        ladder: RecoveryLadder | None = None,
        inbox: InboxService | None = None,
        interval_seconds: float = 60.0,
        batch_limit: int = 500,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._uow = uow_factory
        self._drives = push_reasons
        self._log = task_log
        self._bus = control_bus
        self._ladder = ladder
        # The three-tier reminder ladder rides this loop (FR-065). Same family of
        # problem — something is waiting and nobody has acted — and the same argument
        # for one background clock rather than four.
        self._inbox = inbox
        self._interval = interval_seconds
        self._batch = batch_limit
        self._clock = clock
        self._task: asyncio.Task[None] | None = None

    # ── the loop body ────────────────────────────────────────────────────────────
    async def sweep(self, now: datetime | None = None) -> int:
        """One pass. Returns how many tasks came out of it newly flagged as stalled."""
        now = now or self._clock()
        async with self._uow() as uow:
            candidates = list(
                await uow.tasks.list_stall_candidates(now, limit=self._batch)
            )

        flagged = 0
        for task in candidates:
            try:
                if await self._examine(task, now=now):
                    flagged += 1
            except Exception:  # pragma: no cover - one bad task must not stop the rest
                logger.exception("stall check failed for task %s", task.id)

        if self._inbox is not None:
            try:
                await self._inbox.send_due_reminders(now)
            except Exception:  # pragma: no cover - reminders must not break detection
                logger.exception("sending due inbox reminders failed")
        return flagged

    async def _examine(self, task: Task, *, now: datetime) -> bool:
        """Re-derive this task's drive from live state and act on the verdict.

        Returns True only when the task went from *not flagged* to *flagged* — repeat
        sweeps over a task that is already known to be stalled must not re-announce it, or
        the project channel fills with the same news every minute.
        """
        async with self._uow() as uow:
            fresh = await uow.tasks.get(task.id)
            if fresh is None:  # pragma: no cover - closed between scan and check
                return False
            # Read *before* refreshing: `refresh_in` lowers the flag itself when the drive
            # comes back to life, so asking afterwards always answers "not stalled" and the
            # record would never show that an alarm had been lifted.
            was_flagged = fresh.stalled
            reason = await self._drives.refresh_in(uow, fresh, now=now)
            if reason is not None and is_live(reason, now=now):
                # The scan was reading a stale cache, or the task recovered since it was
                # flagged. Either way it is fine now; `refresh_in` has lowered the flag.
                await uow.commit()
                if was_flagged:
                    await self._log.record(
                        task.id,
                        TaskLogKind.STALL_CLEARED,
                        actor_kind=ActorKind.SYSTEM,
                        reason="động cơ đẩy đã sống trở lại",
                    )
                return False

            verdict = stall_reason(reason, now=now) or "không rõ vì sao"
            already = was_flagged
            fresh.stalled = True
            fresh.stalled_reason = verdict
            fresh.updated_at = now
            await uow.tasks.update(fresh)
            await uow.commit()

        if not already:
            await self._log.record(
                task.id,
                TaskLogKind.STALL_FLAGGED,
                actor_kind=ActorKind.SYSTEM,
                reason=verdict,
            )
            await self._publish(fresh, verdict)

        # The ladder is climbed on **every** sweep, not only the first: Level 1 is a series
        # of spaced retries, and a task that stays stuck has to keep advancing towards the
        # Leader. It is the *announcement* that happens once, not the recovery.
        if self._ladder is not None:
            await self._ladder.climb(fresh, cause=verdict, now=now)
        return not already

    # ── rebuilding after a restart (FR-068) ──────────────────────────────────────
    async def rebuild_drives(self, now: datetime | None = None) -> int:
        """Recompute every open task's drive from the last durable state. Returns the count.

        Run once at startup, because a drive is a claim about the future and a restart
        invalidates every claim made by the process that died: a run it was streaming is
        now a run nobody is reading, and a timer it was holding is gone. Rebuilding from
        stored rows is what makes the safety net survive the failure it exists to catch —
        a net that forgets on restart is exactly no net at all on the day it matters.

        A run left mid-flight is treated as hung rather than trusted: its drive expires on
        the reaper's own deadline, so the next sweep judges it on the clock instead of
        believing a process that is no longer running.
        """
        now = now or self._clock()
        async with self._uow() as uow:
            open_tasks = list(await uow.tasks.list_open(limit=10_000))

        rebuilt = 0
        for task in open_tasks:
            try:
                async with self._uow() as uow:
                    fresh = await uow.tasks.get(task.id)
                    if fresh is None:  # pragma: no cover
                        continue
                    await self._drives.refresh_in(uow, fresh, now=now)
                    await uow.commit()
                rebuilt += 1
            except Exception:  # pragma: no cover - one bad task must not stop startup
                logger.exception("could not rebuild the drive for task %s", task.id)
        return rebuilt

    # ── plumbing ─────────────────────────────────────────────────────────────────
    async def _publish(self, task: Task, verdict: str) -> None:
        """Tell the project channel. Identifiers and labels only — never the description
        (contracts/su-kien-day.md §4)."""
        if task.project_id is None:  # pragma: no cover - defensive
            return
        await self._bus.publish(
            project_topic(task.project_id),
            EVENT_TASK_STALLED,
            {
                "task_id": str(task.id),
                "identifier": task.identifier,
                "stalled": True,
                "reason": verdict,
            },
        )

    def start(self) -> None:
        """Spawn the background loop (idempotent)."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self.sweep()
            except Exception:  # pragma: no cover - a bad tick must not kill the loop
                logger.exception("stall watchdog tick failed")
            await asyncio.sleep(self._interval)
