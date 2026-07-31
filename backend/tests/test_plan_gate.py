"""The plan approval gate, as pure rules (spec 001 FR-011 → FR-014).

The gate is where "the system never decides for you" becomes code. Three choices belong
to the patron and only the patron; the Leader who wrote the plan cannot wave its own plan
through, and asking for changes leaves the project exactly where it was.
"""

from __future__ import annotations

import pytest

from armarius.domain.entities.plan import PlanStatus
from armarius.domain.entities.project import ProjectStatus
from armarius.domain.services.plan_gate import (
    PlanDecision,
    PlanGateError,
    SelfApprovalError,
    can_leave_planning,
    decide,
)


# ── the three choices (FR-013) ────────────────────────────────────────────────────
def test_approve_moves_plan_and_project_forward() -> None:
    outcome = decide(PlanStatus.SUBMITTED, PlanDecision.APPROVE, decider_is_leader=False)

    assert outcome.plan_status is PlanStatus.APPROVED
    assert outcome.next_phase is ProjectStatus.OPERATING
    assert outcome.wake_leader is True
    assert outcome.next_action  # the Leader is told what to do next, in words


def test_request_changes_keeps_the_project_in_planning() -> None:
    outcome = decide(
        PlanStatus.SUBMITTED,
        PlanDecision.REQUEST_CHANGES,
        decider_is_leader=False,
        note="Chia nhỏ hạng mục 2 ra.",
    )

    assert outcome.plan_status is PlanStatus.CHANGES_REQUESTED
    assert outcome.next_phase is None  # stays put — nothing was approved
    assert outcome.wake_leader is True
    assert "Chia nhỏ" in (outcome.note or "")


def test_ask_back_leaves_the_plan_submitted() -> None:
    """A question is not a verdict: the plan is still on the table, still awaiting one."""
    outcome = decide(
        PlanStatus.SUBMITTED,
        PlanDecision.ASK_BACK,
        decider_is_leader=False,
        note="Sao hạng mục 3 lại cần hai người?",
    )

    assert outcome.plan_status is PlanStatus.SUBMITTED
    assert outcome.next_phase is None
    assert outcome.wake_leader is True


@pytest.mark.parametrize(
    "decision", [PlanDecision.REQUEST_CHANGES, PlanDecision.ASK_BACK]
)
def test_changes_and_questions_must_say_why(decision: PlanDecision) -> None:
    with pytest.raises(PlanGateError):
        decide(PlanStatus.SUBMITTED, decision, decider_is_leader=False, note="   ")


# ── the Leader cannot approve its own plan (FR-014) ───────────────────────────────
@pytest.mark.parametrize("decision", list(PlanDecision))
def test_leader_cannot_decide_on_its_own_plan(decision: PlanDecision) -> None:
    with pytest.raises(SelfApprovalError):
        decide(PlanStatus.SUBMITTED, decision, decider_is_leader=True, note="ok")


# ── you can only decide on a plan that is actually on the table ───────────────────
@pytest.mark.parametrize(
    "plan_status", [PlanStatus.DRAFT, PlanStatus.APPROVED, PlanStatus.CHANGES_REQUESTED]
)
def test_cannot_decide_on_a_plan_that_is_not_submitted(plan_status: PlanStatus) -> None:
    with pytest.raises(PlanGateError):
        decide(plan_status, PlanDecision.APPROVE, decider_is_leader=False)


# ── leaving PLANNING needs both an approved context and an approved plan ──────────
@pytest.mark.parametrize(
    ("context_approved", "plan_status", "expected"),
    [
        (True, PlanStatus.APPROVED, True),
        (False, PlanStatus.APPROVED, False),
        (True, PlanStatus.SUBMITTED, False),
        (True, PlanStatus.CHANGES_REQUESTED, False),
        (False, PlanStatus.DRAFT, False),
        (True, None, False),  # no plan at all
    ],
)
def test_can_leave_planning(
    context_approved: bool, plan_status: PlanStatus | None, expected: bool
) -> None:
    assert can_leave_planning(context_approved, plan_status) is expected
