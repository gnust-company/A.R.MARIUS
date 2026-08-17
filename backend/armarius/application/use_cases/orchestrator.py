"""The orchestration loop — the Leader's controlled heartbeat (spec 001 FR-052 → FR-055).

A Leader is a manager, and a manager needs a rhythm. But a rhythm that wakes it every
fifteen minutes to look at a board where nothing changed is a rhythm that spends the
Leader's turns on discovering that nothing changed — and an agent turn is the most
expensive thing this system does.

So the loop separates the two halves that a naive timer conflates:

  * **the looking** happens on the clock, every project on its own rhythm, and costs a
    handful of queries;
  * **the waking** happens only when the looking found something (FR-053).

Built to the same shape as ``LivenessWatchdog``: one background task, cancelled on
shutdown, with the loop body callable on its own so tests can drive it off a fixed clock
instead of waiting for real seconds to pass.

Every pass writes a row, including — especially — the passes that found nothing. A quiet
project and a broken loop produce the same silence otherwise, and the whole feature would
be unfalsifiable on a running service.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from uuid import UUID

from armarius.application.ports.unit_of_work import UnitOfWork
from armarius.application.use_cases.projects import ProjectService

# The same narrow port the task use cases wake the Leader through: "tell the Leader this
# about this project". One protocol, so a second way to reach a Leader never grows here.
from armarius.application.use_cases.tasks import LeaderNotifier
from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.approval import Approval, SignerKind
from armarius.domain.entities.orchestration_sweep import OrchestrationSweep
from armarius.domain.entities.project import ProjectStatus, ProjectThresholds
from armarius.domain.entities.run import WakeSource
from armarius.domain.entities.task import TaskStatus
from armarius.domain.services.approval_rules import missing_signatures
from armarius.domain.services.orchestration_cadence import (
    CadenceState,
    Snag,
    TaskSnapshot,
    find_snags,
    next_interval_seconds,
    quiet_streak,
    within_hourly_cap,
)
from armarius.domain.services.wake_prompt import cadence_detail
from armarius.domain.services.wake_reason import reason as wake_reason
from armarius.infrastructure.events.topic_bus import TopicEventBus, project_topic
from armarius.shared.clock import as_utc, utcnow
from armarius.shared.logging import get_logger

logger = get_logger(__name__)

# Phases in which a project is actually being run. *Setup* and *planning* have no board to
# sweep yet, and *closed* is read-only history (FR-005) — waking a Leader about either
# would be asking it to manage something that is not being managed.
_LIVE_PHASES: frozenset[ProjectStatus] = frozenset(
    {ProjectStatus.OPERATING, ProjectStatus.MAINTAINING}
)

# How far back the loop reads its own history for the two questions counted in *sweeps*:
# the quiet streak (which saturates once it reaches the project's stretch cap) and the
# deadline marks already announced. Nothing counted in *time* may be answered from this
# slice — the hourly ceiling asks the store directly, because a row limit cannot bound a
# duration.
_HISTORY_WINDOW = 32

_CAP_REACHED = "chạm trần số lần đánh thức trong một giờ"
_LEADER_UNREACHABLE = "không gửi được tới Trưởng dự án (ngoại tuyến hoặc đang bận lượt)"

# Announced on the project channel after every pass, including the quiet ones. The board
# shows "last swept / next sweep / snags found", and without this event the only way to
# keep that block current is for the browser to ask again on a timer — which Constitution
# IV forbids and FR-080 spells out. A quiet pass has to be announced too: silence is
# exactly what the block exists to distinguish from a dead loop.
EVENT_CADENCE_SWEPT = "orchestration.swept"


class OrchestrationLoop:
    def __init__(
        self,
        uow_factory: UowFactory,
        projects: ProjectService,
        *,
        leader_notifier: LeaderNotifier | None = None,
        control_bus: TopicEventBus | None = None,
        interval_seconds: float = 60.0,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._uow = uow_factory
        self._projects = projects
        self._notifier = leader_notifier
        self._bus = control_bus
        self._interval = interval_seconds
        self._clock = clock
        self._task: asyncio.Task[None] | None = None

    # ── the loop body ────────────────────────────────────────────────────────────
    async def sweep_all(self, now: datetime | None = None) -> int:
        """Sweep every project whose own rhythm says it is due. Returns how many.

        The loop ticks often; a project is swept on *its* interval. Sweeping everything on
        every tick would make the per-project rhythm decorative and would leave the hourly
        ceiling doing the pacing — the wrong job for a ceiling.
        """
        now = now or self._clock()
        swept = 0
        for project_id in await self._live_projects():
            try:
                if await self._is_due(project_id, now):
                    await self.sweep_project(project_id, now=now)
                    swept += 1
            except Exception:  # pragma: no cover - one bad project must not stop the rest
                logger.exception("orchestration sweep failed for project %s", project_id)
        return swept

    async def sweep_project(
        self, project_id: UUID, *, now: datetime | None = None
    ) -> OrchestrationSweep:
        """One pass over one project's board. Always leaves a row behind."""
        now = now or self._clock()
        thresholds = await self._projects.get_thresholds(project_id)

        async with self._uow() as uow:
            history = list(
                await uow.orchestration_sweeps.list_recent(project_id, limit=_HISTORY_WINDOW)
            )
            snapshots = await self._snapshot_board(uow, project_id)
            # Counted in the store, over an hour of wall clock — never by filtering the
            # rows above, whose bound is a row count and not a duration (FR-055).
            wakes_this_hour = await uow.orchestration_sweeps.count_wakes_since(
                project_id, now - timedelta(hours=1)
            )

        carried = _carry_marks(history)
        snags = find_snags(
            snapshots,
            now=now,
            due_soon_hours=thresholds.due_soon_hours,
            reported_marks=carried,
        )

        woke, skipped_reason = await self._maybe_wake(
            project_id, snags, wakes_this_hour=wakes_this_hour, thresholds=thresholds
        )

        sweep = OrchestrationSweep(
            project_id=project_id,
            swept_at=now,
            snags=snags,
            woke_leader=woke,
            skipped_reason=skipped_reason,
            next_interval_seconds=next_interval_seconds(
                thresholds.orchestration_cadence_seconds,
                state=CadenceState(
                    quiet_streak=quiet_streak([s.snag_count for s in history]),
                    found_snags=bool(snags),
                ),
                max_stretch=thresholds.orchestration_max_stretch,
                max_interval_seconds=thresholds.orchestration_max_interval_seconds,
                min_interval_seconds=thresholds.orchestration_min_interval_seconds,
            ),
            # Spent is not delivered: `woke` alone counts a wake the Leader never got.
            reported_marks=_next_marks(
                carried, snags, announced=woke and skipped_reason is None
            ),
        )
        async with self._uow() as uow:
            await uow.orchestration_sweeps.add(sweep)
            await uow.commit()
        # After the row is durable, never before: an event is a signal to go re-read, and
        # a board that re-read on a pass that then rolled back would show a sweep that
        # never happened (contracts/push-events §Nguyên tắc 1).
        await self._announce(sweep)
        return sweep

    async def _announce(self, sweep: OrchestrationSweep) -> None:
        """Tell the project channel a pass just finished. Counts only — the board reads
        the row itself, so nothing here needs to carry the snags."""
        if self._bus is None:
            return
        await self._bus.publish(
            project_topic(sweep.project_id),
            EVENT_CADENCE_SWEPT,
            {
                "project_id": str(sweep.project_id),
                "swept_at": sweep.swept_at.isoformat(),
                "snag_count": len(sweep.snags),
                "woke_leader": sweep.woke_leader,
            },
        )

    # ── deciding whether to spend a wake ─────────────────────────────────────────
    async def _maybe_wake(
        self,
        project_id: UUID,
        snags: list[Snag],
        *,
        wakes_this_hour: int,
        thresholds: ProjectThresholds,
    ) -> tuple[bool, str | None]:
        if not snags:
            return False, None  # FR-053 — the sweep passes in silence
        if not within_hourly_cap(
            wakes_in_last_hour=wakes_this_hour,
            cap=thresholds.orchestration_wakes_per_hour,
        ):
            # Not an error: the ceiling did its job. The snags stay on the record and the
            # next sweep past the hour will carry them, so nothing is forgotten — only
            # delayed (FR-055).
            return False, _CAP_REACHED
        if self._notifier is None:  # pragma: no cover - only in narrow unit wiring
            return False, "không có kênh gửi tới Trưởng dự án"

        delivered = await self._notifier.notify(
            project_id=project_id,
            source=WakeSource.IDLE_REMINDER,
            reason=wake_reason("cadence_snags", count=len(snags)),
            detail=cadence_detail(snags),
        )
        # A wake that could not be delivered is still a wake spent against the ceiling —
        # it is on the record as a pending cause, and the Leader will read it when it comes
        # back. Counting it keeps an offline Leader from being handed the same backlog four
        # times over the same hour.
        return True, None if delivered else _LEADER_UNREACHABLE

    # ── reading the board ────────────────────────────────────────────────────────
    async def _snapshot_board(
        self, uow: UnitOfWork, project_id: UUID
    ) -> list[TaskSnapshot]:
        """Everything the rules need about every open task, in one place.

        One field is an answer about another table — is the Leader's signature the thing
        this task is waiting on — and it is gathered here rather than inside the rule so
        the rule stays a pure function. It is asked **once for the whole board**, not once
        per task. This runs on a loop that never stops: a per-task lookup would turn a
        two-hundred-task project into hundreds of round trips every pass, on every
        project, forever.

        The rest is read straight off the board, which is all FR-052 lets this cadence
        look at. It used to also ask which tasks had a live run, to decide whether a quiet
        task was quiet for a reason; that question went with the *silent* snag.
        """
        tasks = [
            t
            for t in await uow.tasks.list_by_project(project_id)
            if t.status not in (TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.DRAFT)
        ]
        in_review = [t.id for t in tasks if t.status is TaskStatus.IN_REVIEW]
        awaiting = self._awaiting_leader(
            in_review, await uow.approvals.list_for_tasks(in_review)
        )
        return [
            TaskSnapshot(
                task_id=task.id,
                identifier=task.identifier or str(task.id),
                title=task.title,
                status=task.status,
                due_date=as_utc(task.due_date),
                awaiting_leader_decision=task.id in awaiting,
            )
            for task in tasks
        ]

    @staticmethod
    def _awaiting_leader(
        in_review: Sequence[UUID], approvals: Sequence[Approval]
    ) -> set[UUID]:
        """Which tasks in review are waiting on the Leader's signature (FR-033).

        Asked through the same door the closing gate uses, and answered by the same rule.
        This method used to work it out for itself, and the arithmetic it invented said a
        task the Leader had *rejected* was a task the Leader had signed — so the reworked
        deliverable sat in review and nobody was ever woken to look at it.
        """
        current: dict[UUID, list[Approval]] = {task_id: [] for task_id in in_review}
        for approval in approvals:
            if approval.task_id in current and not approval.superseded:
                current[approval.task_id].append(approval)
        return {
            task_id
            for task_id, signatures in current.items()
            if SignerKind.LEADER in missing_signatures(signatures)
        }

    async def _live_projects(self) -> list[UUID]:
        async with self._uow() as uow:
            workspaces = list(await uow.workspaces.list())
            live: list[UUID] = []
            for ws in workspaces:
                for project in await uow.projects.list_by_workspace(ws.id):
                    if project.status in _LIVE_PHASES:
                        live.append(project.id)
        return live

    async def _is_due(self, project_id: UUID, now: datetime) -> bool:
        async with self._uow() as uow:
            recent = await uow.orchestration_sweeps.list_recent(project_id, limit=1)
        if not recent:
            return True  # never swept — look now
        last = recent[0]
        if last.swept_at is None:  # pragma: no cover - defensive
            return True
        swept_at = as_utc(last.swept_at)
        assert swept_at is not None
        return now >= swept_at + timedelta(seconds=last.next_interval_seconds)

    # ── background lifecycle ─────────────────────────────────────────────────────
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
                await self.sweep_all()
            except Exception:  # pragma: no cover - a bad tick must not kill the loop
                logger.exception("orchestration tick failed")
            await asyncio.sleep(self._interval)


def _carry_marks(history: list[OrchestrationSweep]) -> dict[UUID, int]:
    """The deadline marks already announced, from the most recent sweep that has any.

    Skipping past empty maps is only sound because this map never shrinks — see
    `_next_marks`. If a later change lets an entry be dropped, taking "the most recent
    sweep that has any" would silently read a stale picture and re-announce a mark; the
    reader would have to become "the most recent sweep, full stop".
    """
    for sweep in history:
        if sweep.reported_marks:
            return {UUID(k): int(v) for k, v in sweep.reported_marks.items()}
    return {}


def _next_marks(
    carried: dict[UUID, int], snags: list[Snag], *, announced: bool
) -> dict[str, int]:
    """Carried marks plus whatever this sweep actually announced.

    `announced` is not a refinement, it is the rule: a mark is spent only when it reached
    the Leader. Three of the four predicaments are recomputed from the board every sweep,
    so a sweep the hourly ceiling stopped costs them nothing. *Due soon* is the one with a
    memory, and writing that memory on a sweep that woke nobody retires a warning nobody
    received — the mark never comes round again, and no row anywhere says it went missing.

    A wake that was *spent* but not *delivered* does not count. It leaves a durable row,
    but that row is write-only: both reads over the wakeup table demand a task id, and a
    cadence wake is project-level — no task, no run. No endpoint returns it, no screen
    shows it. Nobody will ever be told, so the mark has to survive to the next sweep. This
    is why the question is `woke and skipped_reason is None` rather than `woke`: the
    ceiling and an unreachable Leader are two different failures, but a mark is lost the
    same way in both.

    The unreachable case is common, not exotic: the notifier refuses while the Leader is
    mid-turn, and it is this very wake that puts it mid-turn.

    Nothing is ever dropped from this map while the sweep history is being read: a task
    that closes stops producing snags, so its entry simply stops mattering. Rebuilding it
    from the live board instead would re-announce every mark after any gap in sweeps.
    """
    merged = {str(k): v for k, v in carried.items()}
    if not announced:
        return merged
    for snag in snags:
        if snag.mark_hours is not None:
            merged[str(snag.task_id)] = snag.mark_hours
    return merged


def _wake_reason(snags: list[Snag]) -> str:
    """One line for the wake record. The detail lives in the packet (FR-054)."""
    return f"nhịp điều phối: {len(snags)} điểm treo trên bảng việc"
