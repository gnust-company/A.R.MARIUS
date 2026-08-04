"""Coalescing rules, as pure functions (spec 001 FR-050).

When several causes land on the same *(agent, task)* pair at once, the agent must be woken
**once**. Two things decide what that one wake looks like:

  * **which cause it is filed under** — the strongest one, not whichever arrived first.
    Order of arrival is an accident of timing; a patron's decision that lands a
    millisecond after an idle reminder must not be filed as an idle reminder, because the
    agent reads the cause to decide how urgently to treat the wake.
  * **what it says** — *every* cause, listed. Keeping only the strongest would silently
    drop the question a teammate asked; the agent would wake, act on the strong cause, and
    never learn there was a second thing waiting.

No I/O here: the caller hands over what is already recorded and gets back what the merged
wake should become.
"""

from __future__ import annotations

from armarius.domain.entities.run import WakeSource

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
    WakeSource.PROJECT_READY: 80,
    WakeSource.APPROVAL_REJECTED: 90,
    WakeSource.BRIEF_REVIEW: 90,
    WakeSource.LEADER_CHAT: 95,
    WakeSource.PATRON_DECISION: 100,
}

# What one cause looks like in the merged reason. Kept here so the parser and the writer
# can never drift apart.
_BULLET = "• "


def strength(source: WakeSource) -> int:
    return _STRENGTH.get(source, 0)


def stronger_source(current: WakeSource, incoming: WakeSource) -> WakeSource:
    """Which cause the merged wake is filed under.

    Ties keep the cause already recorded, and several pairs above are deliberately tied —
    a task reaching review and a task closing are equally urgent to a Leader, and pretending
    otherwise would be inventing a distinction. So for those pairs the order of arrival does
    settle it. That is fine: the ranking exists to stop a loud cause being filed under a
    quiet one, not to impose a total order on causes that are genuinely the same weight.
    Either way the merged reason still names both.
    """
    return incoming if strength(incoming) > strength(current) else current


def merge_causes(existing: str | None, source: WakeSource, reason: str | None) -> str:
    """Fold one more cause into a merged reason, preserving every cause exactly once.

    The first cause is stored plainly (an un-merged wake reads like an ordinary sentence);
    the moment a second arrives the whole thing becomes a list, so the agent can see it was
    woken for more than one thing.

    Duplicates are dropped by comparing the text, so two causes of different kinds that
    happen to be worded identically collapse into one line. That is the right trade here:
    repeating the same sentence twice tells the agent nothing, and each cause still has its
    own row in ``wakeup_requests`` — the merged reason is a summary, not the record.
    """
    incoming = (reason or "").strip() or str(source)
    causes = split_causes(existing)
    if incoming in causes:
        return existing or incoming
    causes.append(incoming)
    if len(causes) == 1:
        return causes[0]
    return "\n".join(f"{_BULLET}{c}" for c in causes)


def split_causes(merged: str | None) -> list[str]:
    """Read a merged reason back out as the list of causes that went into it."""
    text = (merged or "").strip()
    if not text:
        return []
    if _BULLET not in text:
        return [text]
    return [
        line.strip().removeprefix(_BULLET).strip()
        for line in text.splitlines()
        if line.strip()
    ]
