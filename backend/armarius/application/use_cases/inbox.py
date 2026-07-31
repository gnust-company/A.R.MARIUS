"""Patron inbox use cases (spec 001 §11).

Every way in and out publishes on the patron's own event channel. That is not a nicety:
without the push, the Inbox page has to poll to notice a new item, which Constitution IV
forbids outright. If you add another entry point here, publish from it too.

Routing is by recipient, never by broadcast (FR-035) — a patron sees their own items and
nothing else, and an item addressed to someone else reads as *not found*, not
*forbidden*, so its existence does not leak (Constitution I).
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.inbox_item import InboxItem, InboxItemKind, InboxItemStatus
from armarius.infrastructure.events.topic_bus import TopicEventBus, patron_topic
from armarius.shared.clock import utcnow

EVENT_ITEM_PLACED = "hop-thu.muc-moi"
EVENT_ITEM_RESOLVED = "hop-thu.da-giai-quyet"


class InboxService:
    def __init__(self, uow_factory: UowFactory, control_bus: TopicEventBus) -> None:
        self._uow = uow_factory
        self._bus = control_bus

    async def place(
        self,
        *,
        workspace_id: UUID,
        recipient_user_id: str,
        kind: InboxItemKind,
        title: str,
        body: str | None = None,
        project_id: UUID | None = None,
        task_id: UUID | None = None,
        attempt_dossier: dict[str, object] | None = None,
    ) -> InboxItem:
        """Park a decision on one patron and tell their browser about it."""
        item = InboxItem(
            workspace_id=workspace_id,
            recipient_user_id=recipient_user_id,
            project_id=project_id,
            task_id=task_id,
            kind=kind,
            status=InboxItemStatus.PENDING,
            title=title,
            body=body,
            attempt_dossier=dict(attempt_dossier or {}),
            created_at=utcnow(),
        )
        async with self._uow() as uow:
            created = await uow.inbox.add(item)
            await uow.commit()

        await self._publish(EVENT_ITEM_PLACED, created)
        return created

    async def list_for(
        self,
        recipient_user_id: str,
        *,
        status: InboxItemStatus | None = InboxItemStatus.PENDING,
        project_id: UUID | None = None,
    ) -> Sequence[InboxItem]:
        async with self._uow() as uow:
            return await uow.inbox.list_for_recipient(
                recipient_user_id, status=status, project_id=project_id
            )

    async def resolve(
        self, item_id: UUID, *, recipient_user_id: str | None = None
    ) -> InboxItem:
        """Mark an item handled.

        ``recipient_user_id`` is the caller's identity when a human resolves it through
        the API; leave it out for system-initiated resolution (the approve action closing
        its own waiting item). A mismatch raises ``LookupError`` — same answer as a
        missing item, so a patron cannot probe for other people's items.
        """
        async with self._uow() as uow:
            item = await uow.inbox.get(item_id)
            if item is None:
                raise LookupError("inbox item not found")
            if recipient_user_id is not None and item.recipient_user_id != recipient_user_id:
                raise LookupError("inbox item not found")
            if item.status is InboxItemStatus.RESOLVED:
                return item
            item.status = InboxItemStatus.RESOLVED
            item.resolved_at = utcnow()
            await uow.inbox.update(item)
            await uow.commit()

        await self._publish(EVENT_ITEM_RESOLVED, item)
        return item

    async def resolve_pending_for_task(self, task_id: UUID) -> int:
        """Close every item still waiting on a task. Returns how many were closed.

        Used when the thing the patron was asked about stops being a question — the task
        was cancelled, or someone else answered it first.
        """
        async with self._uow() as uow:
            pending = list(await uow.inbox.list_pending_for_task(task_id))
        for item in pending:
            await self.resolve(item.id)
        return len(pending)

    async def _publish(self, event: str, item: InboxItem) -> None:
        """Push to the recipient's channel. Identifiers and labels only — never the body
        (contracts/su-kien-day.md §4: events carry no sensitive content)."""
        await self._bus.publish(
            patron_topic(item.recipient_user_id),
            event,
            {
                "item_id": str(item.id),
                "kind": str(item.kind),
                "status": str(item.status),
                "workspace_id": str(item.workspace_id) if item.workspace_id else None,
                "project_id": str(item.project_id) if item.project_id else None,
                "task_id": str(item.task_id) if item.task_id else None,
                "reminder_tier": item.reminder_tier,
            },
        )
