"""The two-signature rule, as pure functions (spec 001 FR-033, FR-037, FR-041).

No I/O: the caller hands over the signatures already recorded for the **current round**
and gets back whether the task may close and who is still missing. Persisting, routing the
inbox item, waking the worker and stepping the round belong to the application layer.

Why a task cannot close on one signature: the Leader chose the criteria and the worker met
them — both sit on the same side of the work. The patron is the only party outside it. And
why a rejection is not undone by a later approval in the same round: the deliverable that
was rejected is the same deliverable; it has to be reworked and re-signed, not re-voted.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from armarius.domain.entities.approval import Approval, ApprovalResult, SignerKind

# Both, in the order a task normally collects them: the Leader checks the work, then the
# patron accepts it.
REQUIRED_SIGNERS: tuple[SignerKind, ...] = (SignerKind.LEADER, SignerKind.PATRON)

# After this many rejections on one task, the fault is more likely in the brief than in
# the worker — pull the Leader back to the brief instead of looping forever (FR-041).
REJECTION_ROUND_CEILING = 3


class ProjectDecision(StrEnum):
    """The three decisions that stay with the patron no matter what (FR-037)."""

    PLAN_APPROVAL = "plan_approval"
    MAJOR_CHANGE = "major_change"
    PHASE_CHANGE = "phase_change"


# Frozen on purpose: adding a project-level decision to the auto-approval surface should
# make a test go red, not slip through.
PROJECT_DECISIONS_OUTSIDE_AUTO_APPROVAL: frozenset[ProjectDecision] = frozenset(
    {
        ProjectDecision.PLAN_APPROVAL,
        ProjectDecision.MAJOR_CHANGE,
        ProjectDecision.PHASE_CHANGE,
    }
)


def is_closable(approvals: Iterable[Approval]) -> bool:
    """True only when both sides have approved and nobody has rejected this round."""
    signed = list(approvals)
    if any(a.result is ApprovalResult.REJECT for a in signed):
        return False
    return not missing_signatures(signed)


def missing_signatures(approvals: Iterable[Approval]) -> tuple[SignerKind, ...]:
    """Which of the two signatures is still outstanding, in collection order."""
    approved = {
        a.signer_kind for a in approvals if a.result is ApprovalResult.APPROVE
    }
    return tuple(kind for kind in REQUIRED_SIGNERS if kind not in approved)


def rejection_rounds(approvals: Iterable[Approval]) -> int:
    """How many times this task has been sent back, by either side."""
    return sum(1 for a in approvals if a.result is ApprovalResult.REJECT)


def brief_needs_review(approvals: Iterable[Approval]) -> bool:
    """Has the rework loop hit the ceiling that pulls the Leader back in (FR-041)?"""
    return rejection_rounds(approvals) >= REJECTION_ROUND_CEILING


def covered_by_auto_approval(decision: ProjectDecision | None) -> bool:
    """The switch covers task-level acceptance only. `None` means a task signature."""
    if decision is None:
        return True
    return decision not in PROJECT_DECISIONS_OUTSIDE_AUTO_APPROVAL
