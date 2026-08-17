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
from enum import StrEnum
from uuid import UUID

from armarius.application.ports.unit_of_work import UnitOfWork
from armarius.application.use_cases.inbox import InboxService
from armarius.application.use_cases.projects import ProjectService
from armarius.application.use_cases.push_reason import PushReasonService
from armarius.application.use_cases.seats import holds_the_leader_seat
from armarius.application.use_cases.task_log import TaskLogService
from armarius.application.use_cases.tasks import (
    AssignEffects,
    LeaderNotifier,
    TaskService,
    TransitionEffects,
)
from armarius.application.use_cases.types import UowFactory
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.domain.entities.inbox_item import InboxItem, InboxItemKind, InboxItemStatus
from armarius.domain.entities.push_reason import TaskPushReason
from armarius.domain.entities.run import WakeSource
from armarius.domain.entities.task import Task, TaskDrive, TaskStatus
from armarius.domain.entities.task_log import ActorKind, TaskLogKind
from armarius.domain.services import project_rules
from armarius.domain.services.escalation import (
    EscalationLevel,
    EscalationState,
    advance,
    backoff_seconds,
)
from armarius.domain.services.project_rules import ProjectClosed
from armarius.domain.services.push_reason_rules import watches
from armarius.domain.services.wake_reason import reason as wake_reason
from armarius.infrastructure.events.topic_bus import TopicEventBus, patron_topic
from armarius.shared.clock import as_utc, utcnow
from armarius.shared.logging import get_logger

logger = get_logger(__name__)

EVENT_LEVEL_3 = "escalation.level_3"


class EscalationAnswer(StrEnum):
    """The ways a patron can answer a Mức 3 letter (FR-061a).

    The first three ask the system to do something. `HANDLED` is a different kind of
    statement — *I sorted it outside, carry on* — and asks for nothing but the recompute
    every answer gets.
    """

    REASSIGN = "reassign"
    NEXT_ACTION = "next_action"
    CANCEL = "cancel"
    HANDLED = "handled"


class EscalationAnswerInvalid(Exception):
    """Raised when an answer is missing what it needs, or asks for the impossible."""


class NotOnTheLeadersRung(Exception):
    """Raised when either Leader door is used from anywhere but Mức 2 (FR-059).

    The door means *I have been asked about this and it is beyond me*. From lower down it
    would mean something else entirely — handing the patron a task the system has not
    finished trying, which is the one thing FR-059 forbids outright. No skipping, and that
    holds for a Leader in a hurry as much as for a sweep.
    """

# Fallback for the first gap between Level-1 re-wakes when the composition root does not
# supply one. Doubles from here (`backoff_seconds`); see `Settings.level1_backoff_seconds`
# for why it is minutes and not seconds.
_BACKOFF_BASE_SECONDS = 300

# Both ladder budgets now come from the project's thresholds (`level1_recovery_attempts`
# and `level2_handover_attempts`). This is what a task with **no project** falls back to —
# it has nowhere to read a threshold from, and refusing to climb at all would leave it
# outside the safety net entirely. Not a tuning knob: the knobs are in config.
_NO_PROJECT_ATTEMPTS = 3

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
        push_reasons: PushReasonService | None = None,
        tasks: TaskService | None = None,
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
        # Only `answer_escalation` needs this, and only to put the task back under the net.
        self._drives = push_reasons
        # Also only `answer_escalation`: the patron's answer changes the task itself, and
        # it has to change under the same transaction that closes the letter.
        self._tasks = tasks
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
        cap = thresholds.level1_recovery_attempts if thresholds else _NO_PROJECT_ATTEMPTS
        handover_cap = (
            thresholds.level2_handover_attempts if thresholds else _NO_PROJECT_ATTEMPTS
        )

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
                handover_cap=handover_cap,
                progressed=False,
                cause=cause,
                # FR-059a — Level 1 is *re-wake the assignee*, so an unassigned task has
                # no rung to enter and goes straight to the Leader. Read here, from the
                # task row, because the ladder itself must not know about assignees.
                level1_available=task.assigned_marius_id is not None,
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

        await self._act(
            task, ladder, cause=cause, now=now, before=before, handover_cap=handover_cap
        )

    async def leader_decided(
        self, task_id: UUID, *, action: str, now: datetime | None = None
    ) -> None:
        """The Leader says what it is doing about a Mức 2 task (FR-059).

        **Only open at Mức 2**, the same window as the give-up door beside it. Below that
        the system is still spending its own attempts and the Leader has not been asked
        anything; above it the question belongs to the patron and the Leader is out of it.
        One rung, two doors, one window — a door that answers a question nobody asked is a
        door somebody walks through by accident.

        The Level-3 case is the one that cost something. This used to be open there, and
        the call closed the patron's escalation on its way through. The ladder freezes at
        the top on purpose, so nothing ever climbed again and nothing ever placed that item
        a second time: the patron was asked, then had the question quietly taken back while
        the task stayed dead — and it *paid* the Leader for talking, since one sentence with
        no action behind it removed the last person watching.

        What this records is a decision, not an outcome. It does not end the rung and it
        does not touch the inbox at all: the rung ends when the task has a drive again,
        which the sweep checks against the row, and `stand_down` closes the patron's
        question then — on the fact, not on the claim.
        """
        now = now or self._clock()
        async with self._uow() as uow:
            ladder = await uow.push_reasons.get_for_task(task_id)
        if ladder is None or ladder.level is not EscalationLevel.LEVEL_2:
            raise NotOnTheLeadersRung(
                "Đầu việc này không đang chờ Trưởng dự án quyết, nên chưa ghi nhận được "
                "hành động phục hồi."
            )
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
                # Already with the patron. Not an error — a Leader asking twice is asking
                # for the right thing — but the second call must not place a second item,
                # because an inbox that repeats itself stops being read.
                return
            if ladder is None or ladder.level is not EscalationLevel.LEVEL_2:
                raise NotOnTheLeadersRung(
                    "Đầu việc này chưa tới lượt Trưởng dự án quyết, nên chưa chuyển lên "
                    "người chủ được. Hệ thống vẫn đang tự thử."
                )
            ladder.level = EscalationLevel.LEVEL_3
            ladder.next_retry_at = None
            ladder.updated_at = now
            cause = ladder.cause or reason
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
        await self._ask_patron(task, ladder, cause=cause, now=now)

    async def stand_down(self, task_id: UUID, *, now: datetime | None = None) -> None:
        """The task stopped being stalled — clear the rung, budgets and all (FR-060).

        One rule, no exceptions and no conditions: not stalled any more, so the rung goes.
        *Why* it stopped is none of this method's business — a retry landed, the Leader
        moved it, the patron picked it up, someone renamed a file. The ladder only ever
        measured the one thing, and that thing is over.

        Without it the ladder outlives the problem. A task that recovered on its own would
        keep last month's rung, and the next stall — even one with the same cause months
        later — would start halfway up, handing the patron a dossier about attempts that
        belong to a problem already solved.

        **It touches the rung and nothing else.** In particular it does not close the
        patron's escalation letter. That was tried and it is circular: a pending letter is
        itself one of the answers to *is anything going to touch this task*, so writing the
        letter un-stalls the task, which closed the letter, which stalled it again — while
        the stored answer said otherwise and carried no deadline, so no sweep ever looked at
        the task again. The letter belongs to the patron; only `patron_answered` closes it.
        """
        now = now or self._clock()
        async with self._uow() as uow:
            if await self.stand_down_within(uow, task_id, now=now):
                await uow.commit()

    async def stand_down_within(
        self, uow: UnitOfWork, task_id: UUID, *, now: datetime
    ) -> bool:
        """The write half of `stand_down`. **The caller owns the transaction.**

        Returns whether anything was actually cleared, so a caller that owns the commit
        knows whether it has writes to land.
        """
        ladder = await uow.push_reasons.get_for_task(task_id)
        if ladder is None or ladder.level is EscalationLevel.NONE:
            return False
        ladder.apply(
            EscalationState(level=EscalationLevel.NONE, attempts=0, handovers=0, cause=""),
            now=now,
        )
        ladder.next_retry_at = None
        await uow.push_reasons.upsert(ladder)
        return True

    async def patron_answered(
        self,
        item_id: UUID,
        *,
        recipient_user_id: str | None = None,
        now: datetime | None = None,
    ) -> InboxItem:
        """The patron handled a Mức 3 letter — recompute, and put the task back in view.

        A pending letter is one of the answers to *is anything going to touch this task*, and
        an answer with no deadline: while it stands the task counts as not stalled and drops
        out of the sweep entirely, which is right — a named human has it.

        The moment they hand it back, that stops being true, and nothing else would ever
        notice. The stored answer still says *waiting on the patron* and still carries no
        deadline, so the task matches no stall-candidate clause and no sweep looks at it
        again — the exact hole this whole feature exists to close, reached by the patron
        doing the reasonable thing. So the answer is recomputed here: either their action
        gave the task something real, or it did not and it becomes a fresh stall from Mức 1.

        Every kind of item comes through here — this is the patron's own resolve door — and
        anything that is not a task escalation simply resolves and returns.
        """
        return await self.answer_escalation(
            item_id,
            answer=EscalationAnswer.HANDLED,
            recipient_user_id=recipient_user_id,
            now=now,
        )

    async def answer_escalation(
        self,
        item_id: UUID,
        *,
        answer: EscalationAnswer,
        marius_id: UUID | None = None,
        text: str | None = None,
        recipient_user_id: str | None = None,
        now: datetime | None = None,
    ) -> InboxItem:
        """The patron answers a Mức 3 letter: act on the task **and** close the letter.

        One transaction, on purpose. The answer is a single decision the patron made, so it
        has to land as a single fact. Doing it in two — act, then close — leaves a moment
        where the task moved and the letter still stands, and a patron who sees the failure
        and presses again quite reasonably runs the action a second time: a second assign
        wakes the new owner twice for one incident, and a second cancel throws, because
        *cancelled* has nowhere left to go. Under one commit there is no such moment; a
        failure anywhere rolls back both halves and the screen still shows the question.

        Closing the letter comes **first**, and that is what makes a repeat harmless: the
        already-resolved answer means somebody got here first, so this call does nothing at
        all rather than acting again. The letter is the record of the decision, so the
        letter is the thing worth checking.

        Afterwards, outside the transaction, come the parts that talk to the world — waking
        the new owner, publishing to the board — and the recompute FR-061c demands: while
        the letter stood the task counted as not stalled and left the sweep entirely, and
        the moment it is answered nothing else would ever notice. Either their action gave
        the task something real, or it did not and it becomes a fresh stall from Mức 1.
        """
        now = now or self._clock()
        assigned: AssignEffects | None = None
        moved: TransitionEffects | None = None

        async with self._uow() as uow:
            item, ours = await self._inbox.resolve_within(
                uow, item_id, recipient_user_id=recipient_user_id
            )
            if not ours:
                return item
            task_id = item.task_id
            acts_on_task = (
                answer is not EscalationAnswer.HANDLED
                and item.kind is InboxItemKind.ESCALATION
                and task_id is not None
            )
            if answer is not EscalationAnswer.HANDLED and not acts_on_task:
                raise EscalationAnswerInvalid(
                    "Chỉ mục leo thang gắn với một đầu việc mới nhận được hành động này."
                )
            if acts_on_task and self._tasks is None:  # pragma: no cover - always wired
                raise EscalationAnswerInvalid("không có dịch vụ đầu việc để thi hành")
            if acts_on_task:
                await self._refuse_if_closed(uow, item)
                assert task_id is not None and self._tasks is not None
                if answer is EscalationAnswer.REASSIGN:
                    if marius_id is None:
                        raise EscalationAnswerInvalid("giao lại thì phải nói giao cho ai")
                    assigned = await self._tasks.assign_within(
                        uow,
                        task_id,
                        marius_id,
                        transfer_reason=text,
                        user_id=recipient_user_id,
                    )
                elif answer is EscalationAnswer.NEXT_ACTION:
                    await self._tasks.set_next_action_within(uow, task_id, text)
                elif answer is EscalationAnswer.CANCEL:
                    moved = await self._tasks.transition_within(
                        uow,
                        task_id,
                        TaskStatus.CANCELLED,
                        reason=text,
                        user_id=recipient_user_id,
                    )
            if item.kind is InboxItemKind.ESCALATION and task_id is not None:
                await self.stand_down_within(uow, task_id, now=now)
            await uow.commit()

        await self._inbox.publish_resolved(item)
        if assigned is not None and self._tasks is not None:
            await self._tasks.after_assign(assigned)
        if moved is not None and self._tasks is not None:
            await self._tasks.after_transition(moved)

        if item.kind is not InboxItemKind.ESCALATION or item.task_id is None:
            return item
        if self._drives is None:  # pragma: no cover - composition root always wires it
            # Half the job: the rung is down but the task keeps the stale *waiting on the
            # patron* answer and stays outside the sweep. Say so loudly rather than let it
            # look like it worked.
            logger.warning(
                "task %s left the ladder without a drive refresh; nothing is watching it",
                item.task_id,
            )
            return item
        # Runs even when the action above already settled a drive: that settle answered
        # "what did the assignment leave behind", this one answers FR-061c's question about
        # the letter. Recomputing twice costs a read and lands on the same answer; skipping
        # it on the paths that look settled is how the task leaves the net for good.
        await self._drives.refresh(item.task_id, now=now)
        return item

    # ── the three rungs ──────────────────────────────────────────────────────────
    async def _act(
        self,
        task: Task,
        ladder: TaskPushReason,
        *,
        cause: str,
        now: datetime,
        before: EscalationLevel,
        handover_cap: int,
    ) -> None:
        # The rung it came from, not "the one below where it is now": those two stopped
        # being the same answer once an unassigned task could enter at Level 2 (FR-059a),
        # and the log would have claimed a Level-1 attempt that never happened.
        climbed = before is not ladder.level
        if climbed:
            await self._log.record(
                task.id,
                TaskLogKind.ESCALATED,
                actor_kind=ActorKind.SYSTEM,
                before=f"mức {int(before)}",
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
            await self._ask_leader(
                task, ladder, cause=cause, now=now, handover_cap=handover_cap
            )
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

        A task with nobody on it never reaches this rung: having an assignee is Level 1's
        entry condition and it is checked before the ladder steps in (FR-059a), so such a
        task is already at Level 2 being handed to the Leader. The guard below is what is
        left of the old behaviour — it used to be where an unassigned task quietly landed
        after burning its whole budget on nobody.
        """
        if task.assigned_marius_id is None:  # pragma: no cover - unreachable via advance
            return
        try:
            await self._wakes.enqueue(
                marius_id=task.assigned_marius_id,
                task_id=task.id,
                source=WakeSource.CONTINUATION,
                reason=wake_reason(_recovery_code(task)),
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
        self,
        task: Task,
        ladder: TaskPushReason,
        *,
        cause: str,
        now: datetime,
        handover_cap: int,
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

        The two roads *into* this rung do need separate wording (FR-059a). A task whose
        assignee was called and never came wants the Leader to reassign, split or unblock
        it; a task nobody was ever given wants one thing, and it is not any of those.
        Handing both the same paragraph would tell the Leader the system had tried three
        times to wake somebody who does not exist.
        """
        if self._notifier is None or task.project_id is None:  # pragma: no cover
            return
        if task.assigned_marius_id is None:
            situation = (
                "Đầu việc này chưa có người phụ trách, nên không có ai để hệ tự gọi lại: "
                "Mức 1 không có đối tượng để tác động và hệ không tiêu lần thử nào vào "
                "đó. Hai đường:\n"
                "  1. Bạn giao đầu việc cho một người — giao xong là hệ tự gọi người đó "
                "dậy, không cần bạn làm gì thêm.\n"
                "  2. Không có ai để giao — báo lại để hệ đưa thẳng người chủ.\n\n"
            )
        else:
            situation = (
                f"Hệ thống đã tự gọi lại {ladder.attempts} lần mà đầu việc không nhúc "
                "nhích, nên giờ cần bạn. Hai đường:\n"
                "  1. Bạn xử lý — giao lại cho người khác, tách nhỏ, đổi yêu cầu, hay dừng "
                "hẳn — rồi làm thật, vì hệ đợi đầu việc có người chạm vào chứ không đợi "
                "lời hứa.\n"
                "  2. Ngoài tầm bạn — báo lại để hệ đưa thẳng người chủ, đừng ngồi thử "
                "cho có.\n\n"
            )
        delivered = await self._notifier.notify(
            project_id=task.project_id,
            text=(
                f"Đầu việc {task.identifier or task.id} — {task.title} đang đình trệ.\n\n"
                f"Vì sao: {cause}.\n\n"
                f"{situation}"
                f"Đây là lần hỏi thứ {ladder.handover_attempts}/{handover_cap}. "
                "Hết lượt mà đầu việc vẫn đứng im thì người chủ được hỏi."
            ),
            source=WakeSource.NUDGE,
            reason=wake_reason(
                "escalated_to_leader",
                task=task.identifier or task.id,
                attempt=ladder.handover_attempts,
                ceiling=handover_cap,
            ),
        )
        if not delivered:
            logger.warning(
                "level-2 question for task %s did not reach the Leader of project %s "
                "(ask %s/%s)",
                task.id,
                task.project_id,
                ladder.handover_attempts,
                handover_cap,
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
            # Are they already looking at this task? Asked of the inbox, because that is
            # where the answer lives — the rung cannot be trusted for it, since a changed
            # cause sends the ladder back to Level 1 and it climbs up here a second time
            # under the new wording. Two letters, same task, same title, and the reminder
            # ladder chasing both is how an inbox teaches its reader to skip it. The
            # Leader-is-gone path asks this same question before it writes.
            already_asking = any(
                i.kind is InboxItemKind.ESCALATION
                for i in await uow.inbox.list_pending_for_task(task.id)
            )
        if already_asking:
            logger.info(
                "task %s reached level 3 again; the patron already has that question",
                task.id,
            )
            return
        if not recipient or workspace_id is None:
            logger.warning(
                "task %s reached level 3 with nobody to ask; the flag stands", task.id
            )
            return

        # Read, not assumed. If no Level-2 question ever landed, the patron is told *that*
        # instead — the more useful sentence of the two, because a Leader nobody can reach
        # is a problem only the patron can fix, and it wants a different action from them.
        leader_asked = ladder.leader_reached_at is not None
        # FR-059a — the dossier keeps the same distinction the Level-2 question made, for
        # the same reason: a task nobody was ever given asks the patron for one thing, and
        # it is not the thing an exhausted Level 1 asks for. Reported as a flag rather than
        # inferred from `level1_attempts == 0`, so a reader never has to guess whether a
        # zero means *not applicable* or *not yet tried*.
        level1_applicable = task.assigned_marius_id is not None
        dossier: dict[str, object] = {
            "cause": cause,
            "level1_applicable": level1_applicable,
            "level1_attempts": ladder.attempts,
            "last_attempt_at": ladder.last_attempt_at.isoformat()
            if ladder.last_attempt_at
            else None,
            "leader_asked": leader_asked,
            "leader_asks": ladder.handover_attempts,
            "question": (
                "Đầu việc này chưa được giao cho ai, và Trưởng dự án cũng không giao. "
                "Bạn muốn giao cho ai, hay huỷ nó?"
                if not level1_applicable
                else "Đầu việc này đã qua cả hai mức phục hồi mà vẫn không đi tiếp. "
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
                    "Đầu việc chưa có người phụ trách nên hệ không tự gọi lại lần nào "
                    f"— đã hỏi Trưởng dự án {ladder.handover_attempts} lần"
                    if not level1_applicable
                    else f"Hệ thống đã tự gọi lại {ladder.attempts} lần, rồi hỏi Trưởng "
                    f"dự án {ladder.handover_attempts} lần"
                )
                + (
                    ". Trưởng dự án đã đọc nhưng đầu việc vẫn không có ai chạm vào."
                    if leader_asked
                    else " mà không gọi được — nên việc này chưa từng có ai quyết."
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
    async def _refuse_if_closed(uow: UnitOfWork, item: InboxItem) -> None:
        """Refuse an answer that would write into a closed project (FR-005).

        Only the three answers that *act on the task* come through here. Closing the letter
        is not one of them: it writes nothing into the project, only into the patron's own
        inbox, and freezing it once left letters that could never be cleared and a waiting
        count that could never come down.

        Checked here rather than at the door because the door cannot tell these cases
        apart — the answer is in the body, and routing happens before the body is read.
        """
        project_id = item.project_id
        if project_id is None and item.task_id is not None:
            task = await uow.tasks.get(item.task_id)
            project_id = task.project_id if task is not None else None
        if project_id is None:
            return
        project = await uow.projects.get(project_id)
        if project is not None and project_rules.is_closed(project.status):
            raise ProjectClosed("This project is closed — its history is read-only.")

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
                    reason=wake_reason(
                        "assignee_offline", task=task.identifier or task.id
                    ),
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
        return await holds_the_leader_seat(uow, project_id, marius_id)


# Which stall the safety net is calling back about. Read off the task's own drive — the
# same field the sweep's verdict was derived from — so the agent is told *which* stall,
# not merely that there was one. A code rather than that verdict's sentence: the verdict
# is itself system prose, and system prose sent to an agent has to be English
# (Constitution VII), which a sentence built for the board is not.
_RECOVERY_CODES: dict[TaskDrive, str] = {
    TaskDrive.RUN_ACTIVE: "recovery_run_active",
    TaskDrive.WAKE_SCHEDULED: "recovery_wake_scheduled",
    TaskDrive.WAITING_RECOVERY: "recovery_waiting_recovery",
    TaskDrive.WAITING_EXTERNAL: "recovery_waiting_external",
}


def _recovery_code(task: Task) -> str:
    """A task with no drive at all is the orphan case — nobody on it, nothing booked."""
    if task.drive is None:
        return "recovery_orphaned"
    return _RECOVERY_CODES.get(task.drive, "recovery_unknown")
