"""The plan approval gate, as pure rules (spec 001 FR-011 → FR-014).

This is where "the system never decides for you" stops being a slogan. Three choices
belong to the patron and only the patron; the Leader that wrote the plan cannot wave its
own plan through; and asking for changes is not a rejection — the project stays exactly
where it is, waiting.

No I/O here: the caller supplies the current plan status and who is deciding, and gets
back what should change. Persisting it, waking the Leader and closing the inbox item are
the application layer's job.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from armarius.domain.entities.plan import PlanStatus
from armarius.domain.entities.project import ProjectStatus


class PlanDecision(StrEnum):
    """The patron's three choices (FR-013). Values are the wire vocabulary."""

    APPROVE = "duyet"
    REQUEST_CHANGES = "yeu_cau_chinh"
    ASK_BACK = "hoi_lai"


class PlanGateError(Exception):
    """Raised when a decision cannot be applied as asked."""


class SelfApprovalError(PlanGateError):
    """Raised when the Leader tries to decide on its own plan (FR-014)."""


# Decisions that are not verdicts: they must say why, or the Leader has nothing to act on.
_DECISIONS_NEEDING_A_NOTE = frozenset(
    {PlanDecision.REQUEST_CHANGES, PlanDecision.ASK_BACK}
)


@dataclass(frozen=True)
class PlanOutcome:
    """What the decision changes. `next_phase` is None when the project stays put."""

    plan_status: PlanStatus
    next_phase: ProjectStatus | None
    wake_leader: bool
    # What the Leader is told to do next. English: it goes into the wake packet and
    # nowhere else, so the agent is its only reader (Constitution VII).
    next_action: str
    note: str | None = None


def decide(
    plan_status: PlanStatus,
    decision: PlanDecision,
    *,
    decider_is_leader: bool,
    note: str | None = None,
) -> PlanOutcome:
    """Apply one patron decision to a submitted plan.

    Raises `SelfApprovalError` if the Leader is the one deciding, and `PlanGateError` if
    the plan is not on the table or a note-requiring decision came without one.
    """
    if decider_is_leader:
        raise SelfApprovalError(
            "The Leader cannot decide on its own plan — this is the patron's call."
        )
    if plan_status is not PlanStatus.SUBMITTED:
        raise PlanGateError(
            f"There is no plan awaiting a decision (plan is '{plan_status}')."
        )

    cleaned = (note or "").strip()
    if decision in _DECISIONS_NEEDING_A_NOTE and not cleaned:
        raise PlanGateError(
            "Asking for changes or asking a question must say why — "
            "the Leader has nothing to act on otherwise."
        )

    if decision is PlanDecision.APPROVE:
        return PlanOutcome(
            plan_status=PlanStatus.APPROVED,
            next_phase=ProjectStatus.OPERATING,
            wake_leader=True,
            next_action="Break the approved plan into tasks and assign them.",
            note=None,
        )

    if decision is PlanDecision.REQUEST_CHANGES:
        return PlanOutcome(
            plan_status=PlanStatus.CHANGES_REQUESTED,
            next_phase=None,
            wake_leader=True,
            next_action="Revise the plan along the patron's notes and submit it again.",
            note=cleaned,
        )

    # ASK_BACK — a question is not a verdict: the plan is still on the table.
    return PlanOutcome(
        plan_status=PlanStatus.SUBMITTED,
        next_phase=None,
        wake_leader=True,
        next_action="Answer the patron's question about the plan on the table.",
        note=cleaned,
    )


def can_leave_planning(context_approved: bool, plan_status: PlanStatus | None) -> bool:
    """FR-011 — a project leaves *planning* only with both an approved context and an
    approved plan. Either one alone is half a decision."""
    return context_approved and plan_status is PlanStatus.APPROVED
