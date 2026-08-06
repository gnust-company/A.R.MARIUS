"""The recovery ladder — what actually happens to a task the watchdog dropped (FR-059 → FR-061).

The watchdog decides a task has been dropped. This decides who gets asked about it, and it
climbs one rung at a time because the three rungs cost wildly different things:

  * **Mức 1** — the system re-wakes the same assignee, nothing new is decided. Costs an
    agent turn. Budgeted (FR-060) and spaced by a growing gap, because a task that is stuck
    for a real reason does not become unstuck by being asked faster.
  * **Mức 2** — the Leader is told, and decides an explicit recovery action. Costs a Leader
    turn and a judgement.
  * **Mức 3** — the patron is asked, with the record of everything already tried (FR-061).
    Costs a person's attention, which is the one resource this system cannot make more of.

The dossier at Mức 3 is not decoration. A patron asked "this is stuck, what now?" has to go
and reconstruct what was already attempted before they can answer; a patron told "woken
three times over forty minutes, Leader decided X, still stuck, here is the exact question"
can answer in one read. That difference is what decides whether the escalation gets
answered today or next week.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from armarius.application.ports.unit_of_work import UnitOfWork
from armarius.application.use_cases.inbox import InboxService
from armarius.application.use_cases.projects import ProjectService
from armarius.application.use_cases.task_log import TaskLogService
from armarius.application.use_cases.tasks import LeaderNotifier
from armarius.application.use_cases.types import UowFactory
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.domain.entities.inbox_item import InboxItemKind
from armarius.domain.entities.push_reason import TaskPushReason
from armarius.domain.entities.run import WakeSource
from armarius.domain.entities.task import Task
from armarius.domain.entities.task_log import ActorKind, TaskLogKind
from armarius.domain.services.escalation import (
    EscalationLevel,
    advance,
    backoff_seconds,
)
from armarius.infrastructure.events.topic_bus import TopicEventBus, patron_topic
from armarius.shared.clock import as_utc, utcnow
from armarius.shared.logging import get_logger

logger = get_logger(__name__)

EVENT_LEVEL_3 = "leo-thang.muc-3"

# The first gap between Level-1 re-wakes. Doubles from here (`backoff_seconds`).
_BACKOFF_BASE_SECONDS = 60


class RecoveryEscalator:
    """Climbs the ladder for one task at a time. Injected into the stall watchdog."""

    def __init__(
        self,
        uow_factory: UowFactory,
        projects: ProjectService,
        *,
        wakes: WakeEngine,
        inbox: InboxService,
        task_log: TaskLogService,
        control_bus: TopicEventBus,
        leader_notifier: LeaderNotifier | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._uow = uow_factory
        self._projects = projects
        self._wakes = wakes
        self._inbox = inbox
        self._log = task_log
        self._bus = control_bus
        self._notifier = leader_notifier
        self._clock = clock

    async def climb(self, task: Task, *, cause: str, now: datetime | None = None) -> None:
        """One step up the ladder for this task, if a step is due.

        Called on every sweep over a stalled task. Most calls do nothing: Level 1 is a
        series of *spaced* attempts, and the spacing is what makes a budget of three cover
        an hour rather than three seconds.
        """
        now = now or self._clock()
        thresholds = (
            await self._projects.get_thresholds(task.project_id)
            if task.project_id
            else None
        )
        cap = thresholds.level1_recovery_attempts if thresholds else 3

        async with self._uow() as uow:
            ladder = await uow.push_reasons.get_for_task(task.id) or TaskPushReason(
                task_id=task.id, created_at=now
            )
            # Not yet time for the next attempt. A new cause overrides the wait: whatever
            # the ladder was pacing itself about is no longer the problem.
            due = as_utc(ladder.next_retry_at)
            if due is not None and now < due and (ladder.cause or "") == cause:
                return

            before = ladder.level
            state = advance(
                ladder.state(), cap=cap, progressed=False, leader_acted=False, cause=cause
            )
            ladder.apply(state, now=now)
            ladder.last_attempt_at = now
            gap = backoff_seconds(state.attempts, base_seconds=_BACKOFF_BASE_SECONDS)
            ladder.next_retry_at = (
                now + timedelta(seconds=gap)
                if state.level is EscalationLevel.LEVEL_1
                # Above Level 1 nothing is on a timer: the ladder is waiting on a decision,
                # and a clock there would keep re-asking someone who already has the
                # question in front of them.
                else None
            )
            await uow.push_reasons.upsert(ladder)
            await uow.commit()

        await self._act(task, ladder, cause=cause, now=now, climbed=before != state.level)

    # ── the three rungs ──────────────────────────────────────────────────────────
    async def _act(
        self,
        task: Task,
        ladder: TaskPushReason,
        *,
        cause: str,
        now: datetime,
        climbed: bool,
    ) -> None:
        if climbed:
            await self._log.record(
                task.id,
                TaskLogKind.ESCALATED,
                actor_kind=ActorKind.SYSTEM,
                before=f"mức {int(ladder.level) - 1}",
                after=f"mức {int(ladder.level)}",
                reason=cause,
                detail={"attempts": ladder.attempts},
            )

        if ladder.level is EscalationLevel.LEVEL_1:
            await self._rewake_assignee(task, cause=cause)
        elif ladder.level is EscalationLevel.LEVEL_2 and climbed:
            await self._ask_leader(task, ladder, cause=cause)
        elif ladder.level is EscalationLevel.LEVEL_3 and climbed:
            await self._ask_patron(task, ladder, cause=cause, now=now)

    async def _rewake_assignee(self, task: Task, *, cause: str) -> None:
        """Mức 1 — poke the same assignee, decide nothing new.

        A task with nobody on it cannot be re-woken, and that is not a failure to log
        loudly: it is a task that needs the Leader, which the next rung is for.
        """
        if task.assigned_marius_id is None:
            return
        try:
            await self._wakes.enqueue(
                marius_id=task.assigned_marius_id,
                task_id=task.id,
                source=WakeSource.CONTINUATION,
                reason=f"lưới an toàn gọi lại: {cause}",
            )
        except Exception:  # pragma: no cover - a failed wake is itself a stall cause
            logger.exception("level-1 re-wake failed for task %s", task.id)

    async def _ask_leader(self, task: Task, ladder: TaskPushReason, *, cause: str) -> None:
        """Mức 2 — the Leader decides an explicit recovery action."""
        if self._notifier is None or task.project_id is None:  # pragma: no cover
            return
        await self._notifier.notify(
            project_id=task.project_id,
            text=(
                f"Đầu việc {task.identifier or task.id} — {task.title} đang đình trệ: "
                f"{cause}.\n\n"
                f"Hệ thống đã tự gọi lại {ladder.attempts} lần mà đầu việc không nhúc "
                "nhích, nên giờ cần bạn quyết một hành động phục hồi tường minh: giao lại "
                "cho người khác, tách nhỏ, đổi yêu cầu, hay dừng hẳn.\n\n"
                "Đây là quyết định của bạn — hệ thống sẽ không tự thử thêm nữa."
            ),
            source=WakeSource.NUDGE,
            reason=f"leo thang Mức 2: {cause}",
        )

    async def _ask_patron(
        self, task: Task, ladder: TaskPushReason, *, cause: str, now: datetime
    ) -> None:
        """Mức 3 — ask the patron, and hand over everything already tried (FR-061)."""
        async with self._uow() as uow:
            recipient = await self._route_to_patron(uow, task)
            workspace_id = await self._workspace_of(uow, task)
        if not recipient or workspace_id is None:
            logger.warning(
                "task %s reached level 3 with nobody to ask; the flag stands", task.id
            )
            return

        dossier: dict[str, object] = {
            "cause": cause,
            "level1_attempts": ladder.attempts,
            "last_attempt_at": ladder.last_attempt_at.isoformat()
            if ladder.last_attempt_at
            else None,
            "leader_asked": True,
            "question": (
                "Đầu việc này đã qua cả hai mức phục hồi mà vẫn không đi tiếp. "
                "Bạn muốn giao lại cho ai khác, thu hẹp yêu cầu, hay huỷ nó?"
            ),
        }
        item = await self._inbox.place(
            workspace_id=workspace_id,
            recipient_user_id=recipient,
            kind=InboxItemKind.ESCALATION,
            title=f"{task.identifier or task.id} đình trệ, cần bạn quyết",
            body=(
                f"{task.title}\n\nVì sao: {cause}\n"
                f"Hệ thống đã tự gọi lại {ladder.attempts} lần, Trưởng dự án đã được hỏi "
                "và vẫn chưa gỡ được."
            ),
            project_id=task.project_id,
            task_id=task.id,
            attempt_dossier=dossier,
        )
        await self._bus.publish(
            patron_topic(recipient),
            EVENT_LEVEL_3,
            {
                "item_id": str(item.id),
                "task_id": str(task.id),
                "identifier": task.identifier,
                "level1_attempts": ladder.attempts,
            },
        )

    # ── routing ──────────────────────────────────────────────────────────────────
    async def _route_to_patron(self, uow: UnitOfWork, task: Task) -> str:
        """Who to ask, in order of how directly they are responsible (FR-035).

        The seat's granter first — they put this agent on this work. Falling back to the
        project's creator and then the workspace owner is not sloppiness: a Level-3
        escalation that cannot find a recipient is an alarm that rings into an empty room,
        which is worse than asking someone slightly too senior.
        """
        if task.project_id is None:  # pragma: no cover - defensive
            return ""
        if task.assigned_marius_id is not None:
            for grant in await uow.seat_grants.list_by_project(task.project_id):
                if grant.marius_id == task.assigned_marius_id and grant.is_active:
                    if (grant.granted_by_user_id or "").strip():
                        return grant.granted_by_user_id or ""
        project = await uow.projects.get(task.project_id)
        if project is not None and (project.created_by_user_id or "").strip():
            return project.created_by_user_id or ""
        workspace = (
            await uow.workspaces.get(project.workspace_id)
            if project is not None and project.workspace_id
            else None
        )
        return (workspace.owner_user_id or "") if workspace else ""

    @staticmethod
    async def _workspace_of(uow: UnitOfWork, task: Task) -> UUID | None:
        if task.project_id is None:  # pragma: no cover - defensive
            return None
        project = await uow.projects.get(task.project_id)
        return project.workspace_id if project else None
