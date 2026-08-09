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
from armarius.application.use_cases.push_reason import PushReasonService
from armarius.application.use_cases.task_log import TaskLogService
from armarius.application.use_cases.tasks import LeaderNotifier
from armarius.application.use_cases.types import UowFactory
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.domain.entities.inbox_item import InboxItemKind, InboxItemStatus
from armarius.domain.entities.push_reason import TaskPushReason
from armarius.domain.entities.run import WakeSource
from armarius.domain.entities.task import Task, TaskDrive, TaskStatus
from armarius.domain.entities.task_log import ActorKind, TaskLogKind
from armarius.domain.services.escalation import (
    EscalationLevel,
    EscalationState,
    advance,
    backoff_seconds,
)
from armarius.domain.services.push_reason_rules import watches
from armarius.infrastructure.events.topic_bus import TopicEventBus, patron_topic
from armarius.shared.clock import as_utc, utcnow
from armarius.shared.logging import get_logger

logger = get_logger(__name__)

EVENT_LEVEL_3 = "leo-thang.muc-3"

# Fallback for the first gap between Level-1 re-wakes when the composition root does not
# supply one. Doubles from here (`backoff_seconds`); see `Settings.level1_backoff_seconds`
# for why it is minutes and not seconds.
_BACKOFF_BASE_SECONDS = 300

# Said once, here, so the task record and the notification cannot drift apart.
_ASSIGNEE_OFFLINE = "người phụ trách ngoại tuyến"


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
        backoff_base_seconds: int = _BACKOFF_BASE_SECONDS,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._uow = uow_factory
        self._projects = projects
        self._wakes = wakes
        self._inbox = inbox
        self._log = task_log
        self._bus = control_bus
        self._notifier = leader_notifier
        self._backoff_base = backoff_base_seconds
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
            gap = backoff_seconds(state.attempts, base_seconds=self._backoff_base)
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

    async def leader_decided(
        self, task_id: UUID, *, action: str, now: datetime | None = None
    ) -> None:
        """The Leader named an explicit recovery action — Level 2 is answered (FR-059).

        Without this door Level 2 is a rung with no way off it: the ladder waits for a
        decision that has nowhere to be recorded, and the next sweep climbs to the patron
        regardless. That would tell the patron a decision was never made while the Leader
        was in the middle of making it.

        The ladder is cleared outright rather than walked back a step, and from *any* rung
        — including Level 3. `advance` deliberately freezes at the top, because a sweep
        arriving there must not churn; this is not a sweep. It is somebody stating that the
        problem has been addressed, and the ladder measures an unaddressed problem.

        Clearing means the budget comes back whole. Whatever the action turns out to be, it
        is a *new* attempt, and charging it for the tries that came before would leave the
        next stall out of budget before it began.

        Any escalation already sitting in the patron's inbox is resolved with it. An inbox
        that keeps asking about something already handled stops being read, and then the
        next escalation goes unread too.
        """
        now = now or self._clock()
        async with self._uow() as uow:
            ladder = await uow.push_reasons.get_for_task(task_id)
            if ladder is None:
                return
            ladder.apply(
                EscalationState(level=EscalationLevel.NONE, attempts=0, cause=""),
                now=now,
            )
            ladder.next_retry_at = None
            await uow.push_reasons.upsert(ladder)
            await uow.commit()
        await self._inbox.resolve_pending_for_task(task_id)
        await self._log.record(
            task_id,
            TaskLogKind.ESCALATED,
            actor_kind=ActorKind.AGENT,
            after="mức 0",
            reason=f"Trưởng dự án quyết hành động phục hồi: {action}",
        )

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
            await self._rewake_assignee(task, cause=cause, retry_at=ladder.next_retry_at)
        elif ladder.level is EscalationLevel.LEVEL_2 and climbed:
            if not await self._ask_leader(task, ladder, cause=cause):
                await self._hold_below_level_2(task, ladder, cause=cause, now=now)
        elif ladder.level is EscalationLevel.LEVEL_3 and climbed:
            await self._ask_patron(task, ladder, cause=cause, now=now)

    async def _mark_waiting_on_recovery(self, task_id: UUID, *, until: datetime | None) -> None:
        """Say on the task that a delivery is being retried (FR-063)."""
        if until is None:
            return
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:  # pragma: no cover - defensive
                return
            task.drive = TaskDrive.WAITING_RECOVERY
            task.drive_expires_at = until
            await uow.tasks.update(task)
            await uow.commit()

    async def _rewake_assignee(
        self, task: Task, *, cause: str, retry_at: datetime | None = None
    ) -> None:
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
        except Exception:
            # FR-063: the wake did not reach the agent. The work is fine and the transport
            # is not, so the task is marked *waiting on recovery* until the next attempt is
            # due — explicitly not counted as stalled, because something is being done
            # about it. The mark carries a clock, so a retry that never lands stops
            # excusing the task the moment that clock runs out.
            logger.exception("level-1 re-wake failed for task %s", task.id)
            await self._mark_waiting_on_recovery(task.id, until=retry_at)

    async def _ask_leader(self, task: Task, ladder: TaskPushReason, *, cause: str) -> bool:
        """Mức 2 — the Leader decides an explicit recovery action.

        Returns whether the question actually reached them. The notifier answers False for
        a Leader that is offline or mid-turn; it does not raise, so a caller that ignores
        the answer cannot tell "asked" from "tried to ask" — and this rung is climbed
        **once**, so that difference is the whole rung.
        """
        if self._notifier is None or task.project_id is None:  # pragma: no cover
            return False
        return await self._notifier.notify(
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

    async def _hold_below_level_2(
        self, task: Task, ladder: TaskPushReason, *, cause: str, now: datetime
    ) -> None:
        """The Mức 2 question did not reach the Leader — so Mức 2 has not happened yet.

        The rung was already written and committed before anyone tried to deliver it, and
        `_ask_leader` only runs on the sweep that *climbs* — so leaving the rung standing on
        an undelivered question spends the whole of Level 2 on one failed call. Every later
        sweep finds the ladder already at Level 2, climbs it straight to Level 3, and the
        patron is handed a dossier saying the Leader was asked and could not fix it. The
        Leader was never asked. That is the one thing an escalation record must not do:
        report a step that did not happen, to the person whose attention it is spending.

        So the rung is put back down — to Level 1 with its budget still spent, which is not
        a retreat but the truthful position: the system has run out of its own attempts and
        has not yet handed over. The next sweep past the backoff climbs to Level 2 again and
        asks again, because `advance` sends a spent Level 1 straight up.

        The bound this accepts, stated plainly: while the Leader stays unreachable, the task
        never reaches the patron *through this ladder*. It is not silence — the task keeps
        its stall flag and its reason on the board, and a Leader that is genuinely gone is
        reported to the patron by FR-064 on its own path. The alternative is climbing on a
        lie, and a dossier that lies once is a dossier nobody trusts afterwards.
        """
        gap = backoff_seconds(ladder.attempts, base_seconds=self._backoff_base)
        async with self._uow() as uow:
            fresh = await uow.push_reasons.get_for_task(task.id)
            if fresh is None:  # pragma: no cover - defensive
                return
            fresh.level = EscalationLevel.LEVEL_1
            fresh.next_retry_at = now + timedelta(seconds=gap)
            fresh.updated_at = now
            await uow.push_reasons.upsert(fresh)
            await uow.commit()
        logger.warning(
            "level-2 handover to the Leader of project %s was not delivered; "
            "task %s stays below the rung and will ask again",
            task.project_id,
            task.id,
        )
        await self._log.record(
            task.id,
            TaskLogKind.ESCALATED,
            actor_kind=ActorKind.SYSTEM,
            before=f"mức {int(EscalationLevel.LEVEL_2)}",
            after=f"mức {int(EscalationLevel.LEVEL_1)}",
            reason="không gọi được Trưởng dự án — sẽ hỏi lại, chưa tính là đã hỏi",
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
            # True by construction, not by assumption: an undelivered Level-2 question puts
            # the rung back down (`_hold_below_level_2`), so Level 3 is only reachable once
            # the Leader has actually been asked and has not resolved it.
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


class OfflineFalloutService:
    """What an agent going offline costs the board (FR-064).

    Two different answers depending on who vanished, and the difference is the point:

      * a **worker** gone means its tasks are not being worked on. They go to *blocked* with
        the reason said out loud, and the Leader — who allocates work — is told, because
        reassigning is its decision to make.
      * the **Leader** gone means the thing that would normally decide is the thing that is
        missing. Telling it would be talking into an empty room, so this goes straight to the
        patron.

    Both write the reason into the record rather than only into a notification. A task that
    reads *blocked* with no stated cause is a task somebody has to go and investigate, and
    the system already knows the answer at the moment it makes the change.
    """

    def __init__(
        self,
        uow_factory: UowFactory,
        *,
        inbox: InboxService,
        task_log: TaskLogService,
        push_reasons: PushReasonService | None = None,
        leader_notifier: LeaderNotifier | None = None,
    ) -> None:
        self._uow = uow_factory
        self._inbox = inbox
        self._log = task_log
        self._drives = push_reasons
        self._notifier = leader_notifier

    async def agent_went_offline(self, marius_id: UUID, *, now: datetime) -> None:
        blocked: list[Task] = []
        leader_projects: list[UUID] = []
        async with self._uow() as uow:
            marius = await uow.mariuses.get(marius_id)
            if marius is None or marius.workspace_id is None:  # pragma: no cover
                return
            for project in await uow.projects.list_by_workspace(marius.workspace_id):
                is_leader = await self._holds_the_leader_seat(uow, project.id, marius_id)
                if is_leader:
                    leader_projects.append(project.id)
                for task in await uow.tasks.list_by_project(project.id):
                    if task.assigned_marius_id != marius_id or not watches(task.status):
                        continue
                    if task.status is TaskStatus.BLOCKED:
                        continue  # already parked; re-blocking would churn the log
                    task.transition_to(
                        TaskStatus.BLOCKED, now, reason=_ASSIGNEE_OFFLINE
                    )
                    task.updated_at = now
                    await uow.tasks.update(task)
                    blocked.append(task)
            await uow.commit()

        for task in blocked:
            await self._log.record(
                task.id,
                TaskLogKind.STATUS_CHANGED,
                actor_kind=ActorKind.SYSTEM,
                after=str(TaskStatus.BLOCKED),
                reason=_ASSIGNEE_OFFLINE,
            )
            if self._drives is not None:
                await self._drives.refresh(task.id, now=now)
            if self._notifier is not None and task.project_id is not None:
                await self._notifier.notify(
                    project_id=task.project_id,
                    text=(
                        f"{task.identifier or task.id} — {task.title}: người phụ trách "
                        "vừa bị tuyên ngoại tuyến, đầu việc đã chuyển sang *bị chặn*. "
                        "Giao lại cho ai, hay chờ họ quay lại?"
                    ),
                    source=WakeSource.NUDGE,
                    reason=_ASSIGNEE_OFFLINE,
                )

        for project_id in leader_projects:
            await self._tell_the_patron_the_leader_is_gone(project_id, now=now)

    async def _tell_the_patron_the_leader_is_gone(
        self, project_id: UUID, *, now: datetime
    ) -> None:
        """Tell the patron once per outage, not once per re-probe.

        The liveness FSM does not sit still in OFFLINE — it climbs out to CHECKING on a
        doubling backoff, fails the probe, and drops back. Every one of those cycles is a
        genuine *edge* into offline, so an edge check alone is not enough: a Leader that
        stays down would post a fresh escalation every backoff period, forever. Found on
        the running service, where it produced two identical items two minutes apart.

        So the question asked here is the one that actually matters — *is this patron
        already looking at this?* — and it is asked of the inbox, which is where the answer
        lives. When they resolve it and the Leader is still gone, the next cycle tells them
        again, which is correct: that is new information by then.
        """
        async with self._uow() as uow:
            project = await uow.projects.get(project_id)
            if project is None:  # pragma: no cover - defensive
                return
            workspace_id = project.workspace_id
            recipient = (project.created_by_user_id or "").strip()
            if not recipient and workspace_id is not None:
                workspace = await uow.workspaces.get(workspace_id)
                recipient = (workspace.owner_user_id or "").strip() if workspace else ""
            name = project.name
            already_asking = bool(recipient) and any(
                item.kind is InboxItemKind.ESCALATION and item.task_id is None
                for item in await uow.inbox.list_for_recipient(
                    recipient, status=InboxItemStatus.PENDING, project_id=project_id
                )
            )
        if already_asking:
            return
        if not recipient or workspace_id is None:
            logger.warning(
                "project %s lost its Leader with nobody to tell", project_id
            )
            return
        await self._inbox.place(
            workspace_id=workspace_id,
            recipient_user_id=recipient,
            kind=InboxItemKind.ESCALATION,
            title=f"Trưởng dự án của {name} đang ngoại tuyến",
            body=(
                "Trưởng dự án vừa bị tuyên ngoại tuyến, nên không còn ai điều phối dự án "
                "này. Dự án sẽ đậu lại cho tới khi Trưởng dự án trở lại hoặc bạn chỉ định "
                "người khác."
            ),
            project_id=project_id,
        )

    @staticmethod
    async def _holds_the_leader_seat(
        uow: UnitOfWork, project_id: UUID, marius_id: UUID
    ) -> bool:
        leader_keys = {
            role.key for role in await uow.roles.list_by_project(project_id) if role.is_leader
        }
        return any(
            grant.marius_id == marius_id
            and grant.is_active
            and grant.role_key in leader_keys
            for grant in await uow.seat_grants.list_by_project(project_id)
        )
