"""Liveness watchdog (LLD §10) — the background clock that drives the LivenessEngine.

The engine is pure per-tick logic; something has to *call* it. This watchdog is that
caller: a single background loop that, every ``interval_seconds``, advances every Marius in
every workspace one tick — firing probes as the FSM decides and letting silent agents decay
ONLINE → CHECKING → OFFLINE over time. It is started in the app lifespan and cancelled on
shutdown; the loop body (`tick_all`) is separately callable so tests can drive it
deterministically off a fixed clock.

It also reaps hung runs (FR-062). That belongs here rather than in its own loop because
it is the same question asked of a different subject: an agent that has gone quiet, and a
*run* that has gone quiet. A run row that still says RUNNING is the most convincing lie in
the schema — every other check believes it, so a task under one looks busy indefinitely.
Declaring it hung closes the ghost, pulls the task back to *todo*, and re-wakes the same
assignee pointed at the saved next action, so the work resumes where it stopped rather
than starting over.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta
from uuid import UUID

from armarius.application.ports.workspace_trace import (
    WorkspaceTracePublisher,
    announce_run_state,
)
from armarius.application.use_cases.liveness import LivenessEngine
from armarius.application.use_cases.push_reason import PushReasonService
from armarius.application.use_cases.task_log import TaskLogService
from armarius.application.use_cases.types import UowFactory
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.domain.entities.run import RunStatus, WakeSource
from armarius.domain.entities.task import TaskStatus
from armarius.domain.entities.task_log import ActorKind, TaskLogKind
from armarius.shared.clock import as_utc, utcnow
from armarius.shared.logging import get_logger

logger = get_logger(__name__)


class LivenessWatchdog:
    def __init__(
        self,
        uow_factory: UowFactory,
        liveness: LivenessEngine,
        *,
        interval_seconds: float = 30.0,
        hang_suspect_seconds: int = 600,
        hang_grace_seconds: int = 120,
        wakes: WakeEngine | None = None,
        task_log: TaskLogService | None = None,
        push_reasons: PushReasonService | None = None,
        workspace_trace: WorkspaceTracePublisher | None = None,
        clock=utcnow,
    ) -> None:
        self._uow = uow_factory
        self._liveness = liveness
        self._interval = interval_seconds
        self._suspect = hang_suspect_seconds
        self._grace = hang_grace_seconds
        self._wakes = wakes
        self._log = task_log
        self._drives = push_reasons
        # Its own channel, not the wake engine's: reaping a hung run must not depend on
        # whatever else that object can do.
        self._workspace_trace = workspace_trace
        self._clock = clock
        self._task: asyncio.Task[None] | None = None

    async def tick_all(self, now: datetime | None = None) -> int:
        """Advance every Marius in every workspace one tick. Returns the workspace count."""
        now = now or self._clock()
        async with self._uow() as uow:
            workspaces = list(await uow.workspaces.list())
        for ws in workspaces:
            await self._liveness.tick(workspace_id=ws.id, now=now)
        await self.reap_hung_runs(now)
        return len(workspaces)

    # ── reaping hung runs (FR-062) ───────────────────────────────────────────────
    async def reap_hung_runs(self, now: datetime | None = None) -> int:
        """Declare, close and recover every run that has gone silent past grace.

        Returns how many were reaped. Two thresholds rather than one: silence past
        ``hang_suspect_seconds`` makes a run *suspected*, and only silence past the grace
        window on top of that makes it *declared*. The gap exists because an agent that
        thinks for four minutes between tool calls is working, not dead, and a reaper with a
        single tight threshold would keep killing the slow-but-healthy runs — after which
        nobody would leave it switched on.

        The recovery is the part that matters. Closing the ghost run alone would leave a task
        sitting in *in_progress* with nothing behind it; what makes the project actually
        continue is pulling it back to *todo* and waking **the same assignee** pointed at the
        stored next action, so the work resumes where it stopped instead of starting over.
        """
        now = now or self._clock()
        cutoff = now - timedelta(seconds=self._suspect + self._grace)
        async with self._uow() as uow:
            stale = list(await uow.runs.list_silent_active(cutoff))

        reaped = 0
        for run in stale:
            try:
                if await self._declare_hung(run.id, now=now):
                    reaped += 1
            except Exception:  # pragma: no cover - one bad run must not stop the rest
                logger.exception("could not reap hung run %s", run.id)
        return reaped

    async def _declare_hung(self, run_id: UUID, now: datetime) -> bool:
        task_id: UUID | None = None
        assignee: UUID | None = None
        next_action: str | None = None
        async with self._uow() as uow:
            run = await uow.runs.get(run_id)
            # Re-read inside the transaction: the run may have produced output between the
            # scan and here, and reaping a run that just came back to life would kill work
            # in progress — the one mistake this watchdog must never make.
            if run is None or run.status not in (RunStatus.QUEUED, RunStatus.RUNNING):
                return False
            last = as_utc(run.last_output_at or run.started_at or run.created_at)
            if last is not None and last > now - timedelta(
                seconds=self._suspect + self._grace
            ):
                return False

            run.status = RunStatus.TIMED_OUT
            run.error = "lượt chạy im quá ngưỡng nghi treo và cả cửa sổ ân hạn"
            run.finished_at = now
            await uow.runs.update(run)

            task_id = run.task_id
            if task_id is not None:
                task = await uow.tasks.get(task_id)
                if task is not None and task.status is TaskStatus.IN_PROGRESS:
                    # Back to *todo* rather than *blocked*: nothing is wrong with the work,
                    # the runtime died. It is ready to be picked up again the moment somebody
                    # is woken for it.
                    task.transition_to(TaskStatus.TODO, now)
                    task.updated_at = now
                    await uow.tasks.update(task)
                    assignee = task.assigned_marius_id
                    next_action = task.next_action
            marius = (
                await uow.mariuses.get(run.marius_id)
                if run.marius_id is not None
                else None
            )
            await uow.commit()

        if task_id is not None and self._log is not None:
            await self._log.record(
                task_id,
                TaskLogKind.STATUS_CHANGED,
                actor_kind=ActorKind.SYSTEM,
                before=str(TaskStatus.IN_PROGRESS),
                after=str(TaskStatus.TODO),
                reason="lượt chạy bị tuyên treo, kéo đầu việc về chờ làm",
            )
        if assignee is not None and task_id is not None and self._wakes is not None:
            await self._wakes.enqueue(
                marius_id=assignee,
                task_id=task_id,
                source=WakeSource.CONTINUATION,
                reason=(
                    "lượt chạy trước bị treo — làm tiếp từ: "
                    + (next_action or "chỗ đang dở")
                ),
            )
        if task_id is not None and self._drives is not None:
            await self._drives.refresh(task_id, now=now)

        # Last, and deliberately so. This is the one run transition nobody asked for — the
        # server is up, the browser is connected, and the run went from *running* to *timed
        # out* with no request behind it, so a screen with no event here shows it spinning
        # until reload (FR-080). But telling a screen matters less than saving the task, and
        # anything raised in here would otherwise skip the recovery above.
        if marius is not None:
            await announce_run_state(self._workspace_trace, run, marius)
        return True

    # ── background lifecycle ─────────────────────────────────────────────────────
    def start(self) -> None:
        """Spawn the background loop (idempotent)."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Cancel the background loop and await its unwind."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self.tick_all()
            except Exception:  # pragma: no cover - a bad tick must not kill the loop
                logger.exception("liveness watchdog tick failed")
            await asyncio.sleep(self._interval)
