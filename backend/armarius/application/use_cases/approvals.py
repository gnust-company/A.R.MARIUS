"""Output acceptance — the two signatures that close a task (spec 001 Story 3).

A task closes when the Leader has checked the work against the acceptance criteria **and**
the patron responsible for the agent that did the work has accepted it (FR-033). One
signature is never enough: the Leader chose the criteria and the worker met them, so both
sit on the same side of the work. The patron is the only party outside it.

Who that patron is comes from **who put the agent in its seat** (FR-034), read from the
seat grant. It is deliberately not derived from "who owns the workspace": today the two
always agree, and the day they stop agreeing, code that guessed would keep answering
confidently and wrongly. A seat with no recorded granter is broken data, and this module
says so out loud rather than falling back.

Rejection is not cancellation (FR-040). The task goes back to *in_progress* with the
feedback as its next action and the **same worker** is woken — the one who has the context.
After three rounds the fault is more likely in the brief than in the worker, so the Leader
is pulled back to the brief instead of the loop running forever (FR-041).

The auto-approval switch (FR-036) supplies the patron's signature without asking, but it
still writes a real signature row and a real log line (FR-039): it spends fewer of the
patron's keystrokes, not less of the record.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from armarius.application.ports.unit_of_work import UnitOfWork
from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.approval import Approval, ApprovalResult, SignerKind
from armarius.domain.entities.inbox_item import (
    InboxItem,
    InboxItemKind,
    InboxItemStatus,
)
from armarius.domain.entities.run import WakeSource
from armarius.domain.entities.task import Task, TaskDrive, TaskStatus
from armarius.domain.entities.task_log import ActorKind, TaskLogKind
from armarius.domain.services.approval_rules import (
    REJECTION_ROUND_CEILING,
    brief_needs_review,
    is_closable,
    missing_signatures,
    rejection_rounds,
)
from armarius.infrastructure.events.topic_bus import (
    TopicEventBus,
    patron_topic,
    project_topic,
)
from armarius.shared.clock import utcnow

if TYPE_CHECKING:  # pragma: no cover — typing only, keeps the import graph acyclic
    from armarius.application.use_cases.task_log import TaskLogService
    from armarius.application.use_cases.tasks import TaskService
    from armarius.application.use_cases.wake_engine import WakeEngine

EVENT_APPROVAL_SIGNED = "cong-nhan.ky"
EVENT_INBOX_ITEM_PLACED = "hop-thu.muc-moi"


class ApprovalError(Exception):
    """Raised when a signature cannot be applied as asked."""


class ResponsiblePatronUnknown(ApprovalError):
    """No seat grant says who is responsible for this task's agent (FR-034).

    Broken data, not a case to paper over: guessing the workspace owner would be right
    today and silently wrong the day a project has more than one patron.
    """


class NotReadyForSignatureError(ApprovalError):
    """Raised when a task is signed before it is up for review."""


class ApprovalService:
    """Signatures, routing, rejection and the auto-approval switch.

    Every collaborator except the unit of work is optional so the rules can be exercised
    without standing up the whole application. What is *not* optional is the record: the
    signature row and its log line are written inside the caller's transaction, so a
    signature that commits always has its trail with it.
    """

    def __init__(
        self,
        uow_factory: UowFactory,
        *,
        tasks: TaskService | None = None,
        wake: WakeEngine | None = None,
        task_logs: TaskLogService | None = None,
        control_bus: TopicEventBus | None = None,
    ) -> None:
        self._uow = uow_factory
        self._tasks = tasks
        self._wake = wake
        self._logs = task_logs
        self._bus = control_bus

    # ── who has to sign (FR-034) ─────────────────────────────────────────────

    async def responsible_patron(self, task_id: UUID) -> str:
        """The patron who granted the seat of the agent doing this task."""
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise LookupError("task not found")
            return await self._responsible_patron_in(uow, task)

    async def _responsible_patron_in(self, uow: UnitOfWork, task: Task) -> str:
        if task.assigned_marius_id is None or task.project_id is None:
            raise ResponsiblePatronUnknown(
                "Đầu việc chưa có người phụ trách nên chưa biết ai phải ký."
            )
        grants = await uow.seat_grants.list_by_project(task.project_id)
        for grant in grants:
            if grant.marius_id == task.assigned_marius_id and grant.is_active:
                if not (grant.granted_by_user_id or "").strip():
                    raise ResponsiblePatronUnknown(
                        "Ghế của agent này không ghi ai đã cấp — không suy đoán được "
                        "ai phải ký (FR-034)."
                    )
                return grant.granted_by_user_id or ""
        raise ResponsiblePatronUnknown(
            "Agent đang làm đầu việc này không ngồi ghế nào trong dự án."
        )

    # ── the switch (FR-036 → FR-038) ─────────────────────────────────────────

    async def auto_approval(self, project_id: UUID, user_id: str) -> bool:
        """Off until the patron says otherwise (FR-038)."""
        async with self._uow() as uow:
            row = await uow.auto_approvals.get(project_id, user_id)
        return bool(row and row.enabled)

    async def set_auto_approval(
        self, project_id: UUID, user_id: str, *, enabled: bool
    ) -> bool:
        async with self._uow() as uow:
            row = await uow.auto_approvals.set_enabled(
                project_id, user_id, enabled=enabled
            )
            await uow.commit()
        return row.enabled

    # ── signing ──────────────────────────────────────────────────────────────

    async def sign_as_leader(
        self,
        task_id: UUID,
        *,
        marius_id: UUID,
        approve: bool,
        reason: str | None = None,
    ) -> Task:
        return await self._sign(
            task_id,
            signer_kind=SignerKind.LEADER,
            approve=approve,
            reason=reason,
            marius_id=marius_id,
        )

    async def sign_as_patron(
        self,
        task_id: UUID,
        *,
        user_id: str,
        approve: bool,
        reason: str | None = None,
    ) -> Task:
        return await self._sign(
            task_id,
            signer_kind=SignerKind.PATRON,
            approve=approve,
            reason=reason,
            user_id=user_id,
        )

    async def list_for_task(self, task_id: UUID) -> Sequence[Approval]:
        async with self._uow() as uow:
            return await uow.approvals.list_for_task(task_id)

    async def _sign(
        self,
        task_id: UUID,
        *,
        signer_kind: SignerKind,
        approve: bool,
        reason: str | None,
        marius_id: UUID | None = None,
        user_id: str | None = None,
    ) -> Task:
        now = utcnow()
        close_it = False
        rejected_worker: UUID | None = None
        pull_in_leader = False
        project_id: UUID | None = None
        placed: InboxItem | None = None

        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise LookupError("task not found")
            if task.status is not TaskStatus.IN_REVIEW:
                raise NotReadyForSignatureError(
                    f"Đầu việc đang ở '{task.status}' — chỉ ký khi đang *chờ rà soát*."
                )
            project_id = task.project_id

            history = list(await uow.approvals.list_for_task(task_id))
            round_no = rejection_rounds(history) + 1
            signature = Approval(
                task_id=task_id,
                round=round_no,
                signer_kind=signer_kind,
                signer_marius_id=marius_id,
                signer_user_id=user_id,
                result=ApprovalResult.APPROVE if approve else ApprovalResult.REJECT,
                reason=reason,
                signed_at=now,
            )
            await uow.approvals.add(signature)
            await self._log_signature(uow, signature, task_id)
            this_round = [signature]

            if signer_kind is SignerKind.PATRON:
                # The patron just answered the question their inbox was holding. Leaving
                # the item pending would keep asking for a decision already made — and an
                # inbox that lies about what is outstanding stops being read.
                await self._resolve_pending_acceptance(uow, task_id)

            if approve and signer_kind is SignerKind.LEADER and project_id is not None:
                patron_id = await self._responsible_patron_in(uow, task)
                auto = await uow.auto_approvals.get(project_id, patron_id)
                if auto is not None and auto.enabled:
                    stand_in = Approval(
                        task_id=task_id,
                        round=round_no,
                        signer_kind=SignerKind.PATRON,
                        signer_user_id=patron_id,
                        result=ApprovalResult.APPROVE,
                        is_auto=True,
                        signed_at=now,
                    )
                    await uow.approvals.add(stand_in)
                    await self._log_signature(uow, stand_in, task_id)
                    this_round.append(stand_in)
                else:
                    placed = await self._ask_patron_to_accept(
                        uow, task, patron_id=patron_id, now=now
                    )

            current = [a for a in history if a.round == round_no] + this_round
            if not approve:
                rejected_worker = task.assigned_marius_id
                pull_in_leader = brief_needs_review(history + this_round)
                await self._send_back(uow, task, reason=reason or "", now=now)
                if pull_in_leader:
                    await self._log_brief_escalation(uow, task_id, history + this_round)
            else:
                close_it = is_closable(current)

            await uow.commit()

        if placed is not None:
            await self._publish_inbox(placed)
        await self._publish_signature(project_id, task_id, signer_kind, approve)

        if close_it:
            await self._close(task_id)
        if rejected_worker is not None:
            await self._wake_for_rework(task_id, rejected_worker, reason or "")
        if pull_in_leader:
            await self._wake_leader_to_review_the_brief(task_id, project_id)

        async with self._uow() as uow:
            refreshed = await uow.tasks.get(task_id)
        assert refreshed is not None
        return refreshed

    # ── consequences ─────────────────────────────────────────────────────────

    async def _close(self, task_id: UUID) -> None:
        """Hand the close to the task use cases so *done* keeps all its consequences —
        completion mark, unlocked dependents, the Leader told (FR-031)."""
        if self._tasks is None:
            return
        await self._tasks.transition(task_id, TaskStatus.DONE)

    async def _send_back(
        self, uow: UnitOfWork, task: Task, *, reason: str, now: datetime
    ) -> None:
        """Back to *in_progress* with the feedback as the next action (FR-040)."""
        task.transition_to(TaskStatus.IN_PROGRESS, now, reason=reason)
        task.next_action = f"Sửa theo phản hồi: {reason}".strip()
        task.drive = TaskDrive.WAKE_SCHEDULED
        task.updated_at = now
        await uow.tasks.update(task)
        await self._resolve_pending_acceptance(uow, task.id)

    async def _ask_patron_to_accept(
        self, uow: UnitOfWork, task: Task, *, patron_id: str, now: datetime
    ) -> InboxItem:
        """Park the decision on the responsible patron (FR-035).

        Written through the caller's transaction on purpose: an item that promises a
        decision is waiting must commit together with the signature that made it wait.
        """
        project = await uow.projects.get(task.project_id) if task.project_id else None
        item = InboxItem(
            workspace_id=project.workspace_id if project else None,
            recipient_user_id=patron_id,
            project_id=task.project_id,
            task_id=task.id,
            kind=InboxItemKind.OUTPUT_ACCEPTANCE,
            status=InboxItemStatus.PENDING,
            title=f"Công nhận đầu ra: {task.title}",
            body="Trưởng dự án đã chấm đạt. Đầu việc chờ chữ ký của bạn để đóng.",
            created_at=now,
        )
        return await uow.inbox.add(item)

    async def _resolve_pending_acceptance(self, uow: UnitOfWork, task_id: UUID) -> None:
        for item in await uow.inbox.list_pending_for_task(task_id):
            if item.kind is not InboxItemKind.OUTPUT_ACCEPTANCE:
                continue
            item.status = InboxItemStatus.RESOLVED
            item.resolved_at = utcnow()
            await uow.inbox.update(item)

    async def _wake_for_rework(
        self, task_id: UUID, marius_id: UUID, reason: str
    ) -> None:
        if self._wake is None:
            return
        await self._wake.enqueue(
            marius_id=marius_id,
            task_id=task_id,
            source=WakeSource.APPROVAL_REJECTED,
            reason=f"đầu ra bị trả lại: {reason}".strip(),
        )

    async def _wake_leader_to_review_the_brief(
        self, task_id: UUID, project_id: UUID | None
    ) -> None:
        """FR-041: after three rounds, look at the brief, not at the worker."""
        if self._wake is None or project_id is None:
            return
        leader_id = await self._leader_marius(project_id)
        if leader_id is None:
            return
        await self._wake.enqueue(
            marius_id=leader_id,
            task_id=task_id,
            source=WakeSource.BRIEF_REVIEW,
            reason=(
                f"đầu việc đã bị trả lại {REJECTION_ROUND_CEILING} vòng — "
                "soát lại đề bài và bộ tiêu chí"
            ),
        )

    async def _leader_marius(self, project_id: UUID) -> UUID | None:
        async with self._uow() as uow:
            roles = await uow.roles.list_by_project(project_id)
            leader_keys = {r.key for r in roles if r.is_leader}
            for grant in await uow.seat_grants.list_by_project(project_id):
                if grant.role_key in leader_keys and grant.is_active:
                    return grant.marius_id
        return None

    # ── the record (FR-039) ──────────────────────────────────────────────────

    async def _log_signature(
        self, uow: UnitOfWork, signature: Approval, task_id: UUID
    ) -> None:
        if self._logs is None:
            return
        await self._logs.record_in(
            uow,
            task_id,
            TaskLogKind.APPROVAL_SIGNED,
            actor_kind=(
                ActorKind.SYSTEM
                if signature.is_auto
                else ActorKind.AGENT
                if signature.signer_kind is SignerKind.LEADER
                else ActorKind.USER
            ),
            actor_marius_id=signature.signer_marius_id,
            actor_user_id=signature.signer_user_id,
            after=str(signature.result),
            reason=signature.reason,
            detail={
                "signer_kind": str(signature.signer_kind),
                "result": str(signature.result),
                "is_auto": signature.is_auto,
                "round": signature.round,
            },
        )

    async def _log_brief_escalation(
        self, uow: UnitOfWork, task_id: UUID, history: list[Approval]
    ) -> None:
        if self._logs is None:
            return
        await self._logs.record_in(
            uow,
            task_id,
            TaskLogKind.ESCALATED,
            actor_kind=ActorKind.SYSTEM,
            reason=(
                f"bị trả lại {rejection_rounds(history)} vòng — "
                "kéo Trưởng dự án soát lại đề bài (FR-041)"
            ),
            detail={"rejection_rounds": rejection_rounds(history)},
        )

    async def _publish_signature(
        self,
        project_id: UUID | None,
        task_id: UUID,
        signer_kind: SignerKind,
        approve: bool,
    ) -> None:
        if self._bus is None or project_id is None:
            return
        await self._bus.publish(
            project_topic(project_id),
            EVENT_APPROVAL_SIGNED,
            {
                "task_id": str(task_id),
                "signer_kind": str(signer_kind),
                "result": "approve" if approve else "reject",
            },
        )

    async def _publish_inbox(self, item: InboxItem) -> None:
        if self._bus is None:
            return
        await self._bus.publish(
            patron_topic(item.recipient_user_id),
            EVENT_INBOX_ITEM_PLACED,
            {
                "item_id": str(item.id),
                "kind": str(item.kind),
                "project_id": str(item.project_id) if item.project_id else None,
                "task_id": str(item.task_id) if item.task_id else None,
            },
        )


__all__ = [
    "ApprovalError",
    "ApprovalService",
    "NotReadyForSignatureError",
    "ResponsiblePatronUnknown",
    "missing_signatures",
]
