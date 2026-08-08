"""Nhắc ba bậc thưa dần (FR-065).

Chasing a person badly is worse than not chasing them. A reminder every hour teaches the
reader that the inbox is noise — and once they believe that, the *first* reminder stops
working too. So the tiers thin out, each fires once, and none of them ever decides anything
on the patron's behalf.

That last clause is the one with teeth: the project **parks** on the decision. A reminder
loop that quietly marked an unanswered item done or failed would be the system deciding for
the person it was supposed to be asking.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from armarius.application.use_cases.inbox import InboxService
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.domain.entities.inbox_item import InboxItemKind, InboxItemStatus
from armarius.domain.services.reminders import due_reminder_tier
from armarius.infrastructure.events.topic_bus import TopicEventBus, patron_topic
from armarius.shared.clock import as_utc

T0 = datetime(2026, 8, 6, 9, 0, 0, tzinfo=UTC)
TIERS = (8, 24, 72)


# ── luật thuần ──────────────────────────────────────────────────────────────────


def test_nothing_is_due_before_the_first_tier() -> None:
    assert due_reminder_tier(
        created_at=T0, sent_tier=0, now=T0 + timedelta(hours=7), tier_hours=TIERS
    ) is None


def test_each_tier_fires_once() -> None:
    at_8 = due_reminder_tier(
        created_at=T0, sent_tier=0, now=T0 + timedelta(hours=8), tier_hours=TIERS
    )
    assert at_8 == 1
    assert due_reminder_tier(
        created_at=T0, sent_tier=1, now=T0 + timedelta(hours=20), tier_hours=TIERS
    ) is None, "bậc 1 đã gửi rồi mà vẫn đòi gửi lại"
    assert due_reminder_tier(
        created_at=T0, sent_tier=1, now=T0 + timedelta(hours=24), tier_hours=TIERS
    ) == 2


def test_a_long_outage_does_not_deliver_all_three_at_once() -> None:
    """The service was down for four days. It has one thing to say, and it says it once —
    three notifications landing in the same second would be the loop shouting about its own
    downtime rather than about the decision."""
    assert due_reminder_tier(
        created_at=T0, sent_tier=0, now=T0 + timedelta(days=4), tier_hours=TIERS
    ) == 3


def test_the_ladder_stops_at_the_top() -> None:
    assert due_reminder_tier(
        created_at=T0, sent_tier=3, now=T0 + timedelta(days=30), tier_hours=TIERS
    ) is None


def test_an_item_with_no_start_is_never_chased() -> None:
    """Without a start there is no wait to measure, and guessing one would mean inventing
    the very number the whole ladder is made of."""
    assert due_reminder_tier(
        created_at=None, sent_tier=0, now=T0, tier_hours=TIERS
    ) is None


# ── qua kho lưu trữ thật ────────────────────────────────────────────────────────


async def _item(uow_factory, *, recipient: str = "patron-1"):
    """A real pending item, plus the moment it was created.

    The wait is measured forward from that moment rather than by backdating the row: the
    inbox repository deliberately never rewrites `created_at`, and a test that reached
    around it to do so would be proving something about a write path that does not exist.
    """
    workspaces = WorkspaceService(uow_factory)
    ws = await workspaces.create_workspace("WS")
    bus = TopicEventBus()
    service = InboxService(uow_factory, bus)
    item = await service.place(
        workspace_id=ws.id,
        recipient_user_id=recipient,
        kind=InboxItemKind.QUESTION,
        title="Cần bạn quyết",
    )
    async with uow_factory() as uow:
        stored = await uow.inbox.get(item.id)
    assert stored is not None and stored.created_at is not None
    return service, bus, item, as_utc(stored.created_at)


@pytest.mark.asyncio
async def test_a_waiting_item_is_nudged_and_the_tier_is_remembered(uow_factory) -> None:
    service, bus, item, born = await _item(uow_factory)

    assert await service.send_due_reminders(now=born + timedelta(hours=9)) == 1

    async with uow_factory() as uow:
        stored = await uow.inbox.get(item.id)
    assert stored is not None and stored.reminder_tier == 1
    assert stored.last_reminded_at is not None
    types = [e.type for e in bus.backlog(patron_topic("patron-1"))]
    assert types[-1] == "hop-thu.nhac", "nhắc mà hộp thư của người chủ không hay biết"


@pytest.mark.asyncio
async def test_the_same_tier_is_not_sent_twice(uow_factory) -> None:
    """The stored tier is what makes this true across a restart — a counter in memory
    would deliver tier one again every time the service came back up."""
    service, _, item, born = await _item(uow_factory)

    first = await service.send_due_reminders(now=born + timedelta(hours=9))
    second = await service.send_due_reminders(now=born + timedelta(hours=11))

    assert (first, second) == (1, 0)
    async with uow_factory() as uow:
        assert (await uow.inbox.get(item.id)).reminder_tier == 1


@pytest.mark.asyncio
async def test_the_item_is_never_resolved_by_a_reminder(uow_factory) -> None:
    """FR-065's hard edge: the project parks on the decision. A loop that marked an
    unanswered item done or failed would be the system deciding for the very person it was
    supposed to be asking."""
    service, _, item, born = await _item(uow_factory)

    for day in range(1, 6):
        await service.send_due_reminders(now=born + timedelta(days=day))

    async with uow_factory() as uow:
        stored = await uow.inbox.get(item.id)
    assert stored is not None
    assert stored.status is InboxItemStatus.PENDING
    assert stored.resolved_at is None


@pytest.mark.asyncio
async def test_an_item_answered_between_the_scan_and_the_nudge_is_left_alone(
    uow_factory,
) -> None:
    """Nudging somebody about something they just handled is how an inbox loses its
    credibility, so the status is re-read inside the write."""
    service, bus, item, born = await _item(uow_factory)
    await service.resolve(item.id)
    before = len(bus.backlog(patron_topic("patron-1")))

    assert await service.send_due_reminders(now=born + timedelta(hours=9)) == 0
    assert len(bus.backlog(patron_topic("patron-1"))) == before
