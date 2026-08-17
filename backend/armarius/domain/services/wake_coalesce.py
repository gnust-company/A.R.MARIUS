"""Coalescing rules, as pure functions (spec 001 FR-050).

When several causes land on the same *(agent, task)* pair at once, the agent must be woken
**once**. Two things decide what that one wake looks like:

  * **which cause it is filed under** — the strongest one, not whichever arrived first.
    Order of arrival is an accident of timing; a patron's decision that lands a
    millisecond after an idle reminder must not be filed as an idle reminder, because the
    agent reads the cause to decide how urgently to treat the wake.
  * **what it says** — *every* cause, kept as data (a code plus its parameters, see
    ``wake_reason``) so each reader can word it in its own language. Keeping only the
    strongest would silently drop the question a teammate asked; the agent would wake, act
    on the strong cause, and never learn there was a second thing waiting.

No I/O here: the caller hands over what is already recorded and gets back what the merged
wake should become.
"""

from __future__ import annotations

from collections.abc import Sequence

from armarius.domain.entities.run import WakeSource
from armarius.domain.services.wake_reason import WakeReason, merge

# How loudly each cause speaks, low to high. The ordering is about *who is waiting on the
# answer*: a person blocked on a decision outranks a teammate's comment, which outranks the
# system's own housekeeping. Anything not listed sits at the bottom — an unknown cause must
# never be able to outrank a patron by accident.
_STRENGTH: dict[WakeSource, int] = {
    WakeSource.IDLE_REMINDER: 10,
    WakeSource.NUDGE: 20,
    WakeSource.CONTINUATION: 30,
    WakeSource.ON_DEMAND: 40,
    WakeSource.COMMENT: 50,
    WakeSource.MENTION: 60,
    WakeSource.TASK_IN_REVIEW: 65,
    WakeSource.TASK_DONE: 65,
    WakeSource.WORKER_HANDBACK: 70,
    WakeSource.ASSIGNMENT: 80,
    # Tied with assignment on purpose: both say "this is yours and you can start now", and
    # to the worker being handed a task and having its task unblocked are the same call.
    WakeSource.DEPENDENCY_CLEARED: 80,
    # Ranked with assignment for the same reason: to the worker this is the sentence
    # "the job you are holding is not the job any more", which outranks a comment.
    WakeSource.REQUIREMENT_CHANGED: 80,
    WakeSource.PROJECT_READY: 80,
    WakeSource.APPROVAL_REJECTED: 90,
    WakeSource.BRIEF_REVIEW: 90,
    WakeSource.LEADER_CHAT: 95,
    WakeSource.PATRON_DECISION: 100,
}


def strength(source: WakeSource) -> int:
    return _STRENGTH.get(source, 0)


def stronger_source(current: WakeSource, incoming: WakeSource) -> WakeSource:
    """Which cause the merged wake is filed under.

    Ties keep the cause already recorded, and several pairs above are deliberately tied —
    a task reaching review and a task closing are equally urgent to a Leader, and pretending
    otherwise would be inventing a distinction. So for those pairs the order of arrival does
    settle it. That is fine: the ranking exists to stop a loud cause being filed under a
    quiet one, not to impose a total order on causes that are genuinely the same weight.
    Either way the merged wake still names every cause.
    """
    return incoming if strength(incoming) > strength(current) else current


def merge_reasons(
    existing: Sequence[WakeReason], source: WakeSource, incoming: WakeReason | None
) -> list[WakeReason]:
    """Fold one more cause into the list this wake already owes.

    Every cause is kept, not just the strongest. Keeping only the strongest would silently
    drop the question a teammate asked: the agent would wake, act on the loud cause, and
    never learn there was a second thing waiting.

    A caller with nothing to say still leaves a mark — the wake source itself, worded by
    the same table. Better a thin sentence than a wake that says nothing at all about why
    it happened, which is what FR-046 forbids.
    """
    cause = incoming if incoming is not None else WakeReason(code=str(source))
    return merge(existing, cause)
