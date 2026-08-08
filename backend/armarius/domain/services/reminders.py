"""The three-tier reminder ladder, as a pure function (FR-065).

A decision parked on a person needs chasing, and chasing badly is worse than not chasing.
Two failures sit either side of this rule: a reminder every hour, which teaches the reader
that the inbox is noise — after which the *first* reminder stops working too — and no
reminder at all, which leaves a project parked for a fortnight because one question went
unread on a Friday.

So: three tiers, thinning out. The gaps grow because the second time someone has not
answered, they did not miss it — they are deciding, or they are away, and neither of those
is helped by asking faster.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime


def due_reminder_tier(
    *,
    created_at: datetime | None,
    sent_tier: int,
    now: datetime,
    tier_hours: Sequence[int],
) -> int | None:
    """The tier to send now, or None when nothing is due.

    ``sent_tier`` is how many tiers this item has already had (0 for none). Returning the
    *highest* tier the wait has passed rather than merely the next one is what stops a
    service that was down for three days from delivering all three reminders in the same
    second — it has one thing to say, and it says it once.

    An item with no creation time is never chased. That is deliberate: without a start
    there is no wait to measure, and guessing one would mean inventing the very number the
    whole ladder is made of.
    """
    if created_at is None or not tier_hours:
        return None
    waited_hours = (now - created_at).total_seconds() / 3600.0
    passed = sum(1 for hours in sorted(tier_hours) if waited_hours >= hours)
    reached = min(passed, len(tier_hours))
    return reached if reached > sent_tier else None
