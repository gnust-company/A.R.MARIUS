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
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from armarius.application.ports.unit_of_work import UnitOfWork
from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.inbox_item import InboxItem, InboxItemKind, InboxItemStatus
from armarius.domain.services.reminders import due_reminder_tier
from armarius.infrastructure.events.topic_bus import TopicEventBus, patron_topic
from armarius.shared.clock import as_utc, utcnow
from armarius.shared.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover — typing only, keeps the import graph acyclic
    from armarius.application.use_cases.projects import ProjectService

logger = get_logger(__name__)

EVENT_ITEM_PLACED = "inbox.item_added"
EVENT_ITEM_RESOLVED = "inbox.item_resolved"
EVENT_ITEM_REMINDED = "inbox.reminded"

# The system floor, used when an item has no project or the project is gone.
_DEFAULT_REMINDER_HOURS: tuple[int, ...] = (8, 24, 72)


class InboxService:
    def __init__(
        self,
        uow_factory: UowFactory,
        control_bus: TopicEventBus,
        *,
        projects: ProjectService | None = None,
    ) -> None:
        self._uow = uow_factory
        self._bus = control_bus
        # Only the reminder ladder needs this, and only to read per-project tiers.
        self._projects = projects

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

    async def get(self, item_id: UUID) -> InboxItem | None:
        """One item, unscoped. For callers that already know who is asking.

        Deliberately does no recipient check: the freeze guard needs to know which project
        an item belongs to *before* the route runs, and the route itself is what hides
        another patron's item behind a 404.
        """
        async with self._uow() as uow:
            return await uow.inbox.get(item_id)

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
            item, changed = await self.resolve_within(
                uow, item_id, recipient_user_id=recipient_user_id
            )
            if not changed:
                return item
            await uow.commit()

        await self._publish(EVENT_ITEM_RESOLVED, item)
        return item

    async def resolve_within(
        self, uow: UnitOfWork, item_id: UUID, *, recipient_user_id: str | None = None
    ) -> tuple[InboxItem, bool]:
        """The write half of `resolve`. **The caller owns the transaction.**

        Returns the item and whether this call is what closed it. A caller that has to
        change something else in the same breath — the patron answering an escalation
        both acts on the task and closes the letter — needs both writes behind one commit,
        and needs to know whether the answer had already been recorded so a retry does not
        act twice. `False` means somebody got here first.
        """
        item = await uow.inbox.get(item_id)
        if item is None:
            raise LookupError("inbox item not found")
        if recipient_user_id is not None and item.recipient_user_id != recipient_user_id:
            raise LookupError("inbox item not found")
        if item.status is not InboxItemStatus.PENDING:
            # Already off the waiting list, whichever way it left. Asked rather than
            # "is it RESOLVED" so that a voided letter cannot be turned into a resolved
            # one — that would record an answer the patron never gave.
            return item, False
        item.status = InboxItemStatus.RESOLVED
        item.resolved_at = utcnow()
        await uow.inbox.update(item)
        return item, True

    async def publish_resolved(self, item: InboxItem) -> None:
        """Announce a resolution whose write landed under somebody else's transaction."""
        await self._publish(EVENT_ITEM_RESOLVED, item)

    async def void_for_project(self, project_id: UUID) -> int:
        """Retire every letter still waiting on this project. Returns how many.

        Called when the project closes (FR-005). A closed project answers nothing and is
        answered by nobody, so a question about it is a question that will never be
        answered — and one that would otherwise sit in the patron's waiting list and be
        chased by the reminder ladder for ever.

        Voided, not resolved: the patron never answered these, and the record should not
        say they did. The letters stay where they are and stay readable, which is the
        whole point of keeping a closed project.
        """
        now = utcnow()
        async with self._uow() as uow:
            waiting = list(await uow.inbox.list_pending_for_project(project_id))
            for item in waiting:
                item.status = InboxItemStatus.VOID
                item.resolved_at = now
                await uow.inbox.update(item)
            if waiting:
                await uow.commit()

        for item in waiting:
            await self._publish(EVENT_ITEM_RESOLVED, item)
        return len(waiting)

    # ── the three-tier reminder ladder (FR-065) ──────────────────────────────
    async def send_due_reminders(self, now: datetime | None = None) -> int:
        """Nudge every item whose wait has crossed a tier. Returns how many were nudged.

        Three tiers, thinning out (8h, 24h, 72h by default). The thinning is the design:
        a reminder every hour teaches the reader that the inbox is noise, and once they
        believe that, the *first* reminder stops working too.

        Two rules this must never break, both from FR-065. The project **parks** on the
        decision — no reminder resolves anything, and nothing here marks work done or
        failed on the patron's behalf. And a tier fires **once**: the stored tier is what
        makes that true across restarts, so a service that comes back up after two days
        does not deliver all three at once.
        """
        now = now or utcnow()
        async with self._uow() as uow:
            pending = list(await uow.inbox.list_pending())

        # One threshold lookup per *project*, not per item. Each lookup opens its own
        # transaction, and this loop runs every sweep, forever — with two hundred items
        # waiting that was two hundred transactions a minute, and it showed: on a real
        # service the stall sweep this ladder rides slowed from about a minute to about
        # three, so a dropped task took three times as long to be noticed. The cost now
        # scales with projects, which is bounded by something a person created, rather
        # than with items, which is bounded by how far behind the patron has fallen —
        # exactly the moment it must not get slower.
        by_project: dict[UUID | None, tuple[int, ...]] = {}

        nudged = 0
        for item in pending:
            if item.project_id not in by_project:
                by_project[item.project_id] = await self._thresholds_for(item)
            thresholds = by_project[item.project_id]
            tier = due_reminder_tier(
                created_at=as_utc(item.created_at),
                sent_tier=item.reminder_tier,
                now=now,
                tier_hours=thresholds,
            )
            if tier is None:
                continue
            async with self._uow() as uow:
                fresh = await uow.inbox.get(item.id)
                # Re-read: the patron may have answered between the scan and here, and
                # nudging someone about something they just handled is how an inbox loses
                # its credibility.
                if fresh is None or fresh.status is not InboxItemStatus.PENDING:
                    continue
                fresh.reminder_tier = tier
                fresh.last_reminded_at = now
                await uow.inbox.update(fresh)
                await uow.commit()
            try:
                await self._publish(EVENT_ITEM_REMINDED, fresh)
            except Exception:  # pragma: no cover - a dead channel must not stop the rest
                # The tier is already committed, so a failed push costs this item its
                # real-time nudge and nothing more — it stays pending and still shows on
                # the next page load. Letting the exception out would be the worse trade:
                # every item queued behind this one would lose its nudge too.
                logger.exception("could not push the reminder for inbox item %s", fresh.id)
            nudged += 1
        return nudged

    async def _thresholds_for(self, item: InboxItem) -> tuple[int, ...]:
        """The reminder tiers for this item's project, falling back to the system floor.

        A project that runs on a different clock than the rest of the workspace should be
        chased on its own clock too — nagging a two-week research project on the same
        rhythm as a same-day fix is how the ladder becomes noise.
        """
        if self._projects is None or item.project_id is None:
            return _DEFAULT_REMINDER_HOURS
        try:
            return (await self._projects.get_thresholds(item.project_id)).patron_reminder_hours
        except LookupError:  # pragma: no cover - project deleted under a live item
            return _DEFAULT_REMINDER_HOURS

    async def resolve_pending_for_task(
        self, task_id: UUID, *, kind: InboxItemKind | None = None
    ) -> int:
        """Close items still waiting on a task. Returns how many were closed.

        Used when the thing the patron was asked about stops being a question — the task
        was cancelled, or someone else answered it first.

        ``kind`` narrows it to one sort of question. Pass it whenever the caller only knows
        that *its own* question is answered: a task can be holding a stalled-escalation and
        a waiting-for-acceptance item at the same time, and closing both because one of them
        was settled tells the patron a decision was made that nobody made.
        """
        async with self._uow() as uow:
            pending = [
                item
                for item in await uow.inbox.list_pending_for_task(task_id)
                if kind is None or item.kind is kind
            ]
        for item in pending:
            await self.resolve(item.id)
        return len(pending)

    async def _publish(self, event: str, item: InboxItem) -> None:
        """Push to the recipient's channel. Identifiers and labels only — never the body
        (contracts/push-events.md §4: events carry no sensitive content)."""
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
