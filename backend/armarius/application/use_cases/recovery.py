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


class NotOnTheLeadersRung(Exception):
    """Raised when the give-up door is used from anywhere but Mức 2 (FR-059).

    The door means *I have been asked about this and it is beyond me*. From lower down it
    would mean something else entirely — handing the patron a task the system has not
    finished trying, which is the one thing FR-059 forbids outright. No skipping, and that
    holds for a Leader in a hurry as much as for a sweep.
    """

# Fallback for the first gap between Level-1 re-wakes when the composition root does not
# supply one. Doubles from here (`backoff_seconds`); see `Settings.level1_backoff_seconds`
# for why it is minutes and not seconds.
_BACKOFF_BASE_SECONDS = 300

# How many times an undelivered Mức 2 handover is retried before the patron is told the
# Leader could not be reached. Deliberately *not* the Level-1 budget, even though three is
# the same number today: that budget answers "how long do we let an agent keep trying",
# which a project may reasonably raise to ten for agents that sleep a lot, and raising it
# must not silently make a patron wait through ten failed calls to a Leader before hearing
# that their Leader is gone. Different question, different knob.
_HANDOVER_ATTEMPTS = 3

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
                ladder.state(),
                cap=cap,
                handover_cap=_HANDOVER_ATTEMPTS,
                progressed=False,
                cause=cause,
            )
            ladder.apply(state, now=now)
            ladder.last_attempt_at = now
            # Both budgets are paced, so both get a clock. Level 2 used to get none, on the
            # reasoning that a rung waiting for a decision should not nag — which quietly
            # meant *no wait at all*: the next sweep, sixty seconds later, found no clock to
            # respect and walked straight past the Leader to the patron. Only Level 3 has
            # nothing left to pace, because there is nothing above the patron.
            paced = (
                state.handovers
                if state.level is EscalationLevel.LEVEL_2
                else state.attempts
            )
            ladder.next_retry_at = (
                now + timedelta(seconds=backoff_seconds(paced, base_seconds=self._backoff_base))
                if state.level in (EscalationLevel.LEVEL_1, EscalationLevel.LEVEL_2)
                else None
            )
            await uow.push_reasons.upsert(ladder)
            await uow.commit()

        await self._act(task, ladder, cause=cause, now=now, climbed=before != state.level)

    async def leader_decided(
        self, task_id: UUID, *, action: str, now: datetime | None = None
    ) -> None:
        """The Leader says what it is doing about a Level-2 task (FR-059).

        This **records** a decision; it does not end the rung. What ends the rung is the
        task getting a drive again, and that is checked against the task row on the next
        sweep. The difference is not pedantry: the ladder used to clear itself here, on the
        strength of the sentence alone, so a Leader could answer *reassigned it to Bob*
        without reassigning anything and the ladder would stand down on a task that nobody
        was going to touch. Then the sweep re-flagged it a minute later and the whole thing
        started again at Level 1 — round and round, and the patron never heard a word.

        So the decision goes into the record, where it belongs, and the clock keeps
        running. A real action gives the task a real drive within the window and the ladder
        stands down on its own; an empty one does not, and the patron is told.

        Any escalation already sitting in the patron's inbox is resolved, because the
        Leader is now on it and an inbox that keeps asking about something being handled
        stops being read.
        """
        now = now or self._clock()
        await self._inbox.resolve_pending_for_task(task_id)
        await self._log.record(
            task_id,
            TaskLogKind.ESCALATED,
            actor_kind=ActorKind.AGENT,
            after=f"mức {int(EscalationLevel.LEVEL_2)}",
            reason=f"Trưởng dự án quyết hành động phục hồi: {action}",
        )

    async def leader_gave_up(
        self, task_id: UUID, *, reason: str, now: datetime | None = None
    ) -> None:
        """The Leader says this one is beyond it — go to the patron now (FR-059).

        Without this door, a Leader that knows within seconds it cannot help has only two
        moves: sit out the full three asks and half an hour of the project's time, or
        invent an action to look busy. Both are worse than letting it say so.

        Straight to Level 3, no waiting out the clock — the budget exists to find out
        whether the Leader can fix it, and that question has just been answered.
        """
        now = now or self._clock()
        async with self._uow() as uow:
            ladder = await uow.push_reasons.get_for_task(task_id)
            task = await uow.tasks.get(task_id)
            if task is None:
                raise LookupError("task not found")
            if ladder is not None and ladder.level >= EscalationLevel.LEVEL_3:
                return  # already with the patron; asking twice is how an inbox dies
            if ladder is None or ladder.level is not EscalationLevel.LEVEL_2:
                raise NotOnTheLeadersRung(
                    "Đầu việc này chưa tới lượt Trưởng dự án quyết, nên chưa chuyển lên "
                    "người chủ được. Hệ thống vẫn đang tự thử."
                )
            ladder.level = EscalationLevel.LEVEL_3
            ladder.next_retry_at = None
            ladder.updated_at = now
            await uow.push_reasons.upsert(ladder)
            await uow.commit()

        await self._log.record(
            task_id,
            TaskLogKind.ESCALATED,
            actor_kind=ActorKind.AGENT,
            before=f"mức {int(EscalationLevel.LEVEL_2)}",
            after=f"mức {int(EscalationLevel.LEVEL_3)}",
            reason=f"Trưởng dự án báo ngoài tầm xử lý: {reason}",
        )
        await self._ask_patron(task, ladder, cause=ladder.cause or reason, now=now)

    async def stand_down(self, task_id: UUID, *, now: datetime | None = None) -> None:
        """The task has a drive again — clear the ladder, budgets and all (FR-060).

        Called by the sweep the moment a flagged task turns out to be moving. This is the
        only door back to a clean slate, and it is deliberately not a declaration anybody
        can make: it fires on the fact the whole ladder measures.

        Without it the ladder outlives the problem. A task that recovered on its own would
        keep last month's rung, and the next stall — even one with the same cause months
        later — would start halfway up, handing the patron a dossier about attempts that
        belong to a problem already solved.
        """
        now = now or self._clock()
        async with self._uow() as uow:
            ladder = await uow.push_reasons.get_for_task(task_id)
            if ladder is None or ladder.level is EscalationLevel.NONE:
                return
            ladder.apply(EscalationState(level=EscalationLevel.NONE, cause=""), now=now)
            ladder.next_retry_at = None
            await uow.push_reasons.upsert(ladder)
            await uow.commit()

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
        elif ladder.level is EscalationLevel.LEVEL_2:
            # Asked on *every* sweep that gets past the clock, not only the one that
            # climbed. Level 2 is a series of spaced asks, exactly like Level 1 — the ask is
            # the attempt, and one attempt is not a rung.
            await self._ask_leader(task, ladder, cause=cause, now=now)
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

    async def _ask_leader(
        self, task: Task, ladder: TaskPushReason, *, cause: str, now: datetime
    ) -> None:
        """Mức 2 — tell the Leader exactly what is wrong and let it act.

        This rung sends a question and then waits for **the task**, not for an answer. A
        Leader can reply *reassigned it to Bob* and leave the task as dead as it was; what
        ends this rung is the drive coming back — somebody scheduled to touch the task —
        and the sweep checks that against the row rather than taking anyone's word.

        Which means an unreachable Leader and a silent one need no separate handling, and
        get none. Both are *asked, and the task did not move*, so both spend one of the
        three spaced asks and then hand on to the patron. Whether the question was
        **delivered** is still worth knowing, but only for the record: it decides whether
        the patron is told the Leader was asked or told nobody could reach them, and those
        two send the patron to do different things.
        """
        if self._notifier is None or task.project_id is None:  # pragma: no cover
            return
        delivered = await self._notifier.notify(
            project_id=task.project_id,
            text=(
                f"Đầu việc {task.identifier or task.id} — {task.title} đang đình trệ.\n\n"
                f"Vì sao: {cause}.\n\n"
                f"Hệ thống đã tự gọi lại {ladder.attempts} lần mà đầu việc không nhúc "
                "nhích, nên giờ cần bạn. Hai đường:\n"
                "  1. Bạn xử lý — giao lại cho người khác, tách nhỏ, đổi yêu cầu, hay dừng "
                "hẳn — rồi làm thật, vì hệ đợi đầu việc có người chạm vào chứ không đợi "
                "lời hứa.\n"
                "  2. Ngoài tầm bạn — báo lại để hệ đưa thẳng người chủ, đừng ngồi thử "
                "cho có.\n\n"
                f"Đây là lần hỏi thứ {ladder.handover_attempts}/{_HANDOVER_ATTEMPTS}. "
                "Hết lượt mà đầu việc vẫn đứng im thì người chủ được hỏi."
            ),
            source=WakeSource.NUDGE,
            reason=f"leo thang Mức 2: {cause}",
        )
        if not delivered:
            logger.warning(
                "level-2 question for task %s did not reach the Leader of project %s "
                "(ask %s/%s)",
                task.id,
                task.project_id,
                ladder.handover_attempts,
                _HANDOVER_ATTEMPTS,
            )
            return
        if ladder.leader_reached_at is not None:
            return
        async with self._uow() as uow:
            fresh = await uow.push_reasons.get_for_task(task.id)
            if fresh is None:  # pragma: no cover - defensive
                return
            fresh.leader_reached_at = now
            fresh.updated_at = now
            await uow.push_reasons.upsert(fresh)
            await uow.commit()

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

        # Read, not assumed. If no Level-2 question ever landed, the patron is told *that*
        # instead — the more useful sentence of the two, because a Leader nobody can reach
        # is a problem only the patron can fix, and it wants a different action from them.
        leader_asked = ladder.leader_reached_at is not None
        dossier: dict[str, object] = {
            "cause": cause,
            "level1_attempts": ladder.attempts,
            "last_attempt_at": ladder.last_attempt_at.isoformat()
            if ladder.last_attempt_at
            else None,
            "leader_asked": leader_asked,
            "leader_asks": ladder.handover_attempts,
            "question": (
                "Đầu việc này đã qua cả hai mức phục hồi mà vẫn không đi tiếp. "
                "Bạn muốn giao lại cho ai khác, thu hẹp yêu cầu, hay huỷ nó?"
                if leader_asked
                else "Đầu việc này kẹt và không gọi được Trưởng dự án. Bạn muốn dựng lại "
                "Trưởng dự án, giao đầu việc cho ai khác, hay huỷ nó?"
            ),
        }
        item = await self._inbox.place(
            workspace_id=workspace_id,
            recipient_user_id=recipient,
            kind=InboxItemKind.ESCALATION,
            title=f"{task.identifier or task.id} đình trệ, cần bạn quyết",
            body=(
                f"{task.title}\n\nVì sao: {cause}\n"
                + (
                    f"Hệ thống đã tự gọi lại {ladder.attempts} lần, rồi hỏi Trưởng dự "
                    f"án {ladder.handover_attempts} lần. Trưởng dự án đã đọc nhưng đầu "
                    "việc vẫn không có ai chạm vào."
                    if leader_asked
                    else f"Hệ thống đã tự gọi lại {ladder.attempts} lần, rồi thử hỏi "
                    f"Trưởng dự án {ladder.handover_attempts} lần mà không gọi được "
                    "— nên việc này chưa từng có ai quyết."
                )
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
