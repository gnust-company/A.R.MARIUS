"""Task change log — the single entry point for writing a task's history (spec 001 §10).

Every part of the system that changes a task writes here and nowhere else. Four separate
requirements read this trail (FR-021, FR-039, FR-061, FR-079); if writes were scattered,
each of them would see a different, partial history.

Two ways in, on purpose:

- :meth:`record` opens its own transaction. Use it when the log entry is the whole point
  (a watchdog noting a stall) or from a caller that has no transaction of its own.
- :meth:`record_in` appends inside a transaction the caller already owns, so the change
  and its log line commit or roll back together. Use it from any use case that is already
  mutating the task — a status change that commits without its log line is a lie.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from armarius.application.ports.unit_of_work import UnitOfWork
from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.task_log import ActorKind, TaskLogEntry, TaskLogKind
from armarius.shared.clock import utcnow


class TaskLogService:
    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow = uow_factory

    async def record(
        self,
        task_id: UUID,
        kind: TaskLogKind,
        *,
        actor_kind: ActorKind = ActorKind.SYSTEM,
        actor_marius_id: UUID | None = None,
        actor_user_id: str | None = None,
        before: str | None = None,
        after: str | None = None,
        reason: str | None = None,
        detail: dict[str, object] | None = None,
    ) -> TaskLogEntry:
        """Append one entry in its own transaction."""
        async with self._uow() as uow:
            entry = await self.record_in(
                uow,
                task_id,
                kind,
                actor_kind=actor_kind,
                actor_marius_id=actor_marius_id,
                actor_user_id=actor_user_id,
                before=before,
                after=after,
                reason=reason,
                detail=detail,
            )
            await uow.commit()
            return entry

    async def record_in(
        self,
        uow: UnitOfWork,
        task_id: UUID,
        kind: TaskLogKind,
        *,
        actor_kind: ActorKind = ActorKind.SYSTEM,
        actor_marius_id: UUID | None = None,
        actor_user_id: str | None = None,
        before: str | None = None,
        after: str | None = None,
        reason: str | None = None,
        detail: dict[str, object] | None = None,
    ) -> TaskLogEntry:
        """Append one entry inside the caller's transaction — caller commits."""
        entry = TaskLogEntry(
            task_id=task_id,
            seq=await uow.task_logs.next_seq(task_id),
            kind=kind,
            actor_kind=actor_kind,
            actor_marius_id=actor_marius_id,
            actor_user_id=actor_user_id,
            before=before,
            after=after,
            reason=reason,
            detail=dict(detail or {}),
            created_at=utcnow(),
        )
        return await uow.task_logs.append(entry)

    async def list_for_task(self, task_id: UUID) -> Sequence[TaskLogEntry]:
        """The task's whole history, oldest first."""
        async with self._uow() as uow:
            return await uow.task_logs.list_by_task(task_id)
