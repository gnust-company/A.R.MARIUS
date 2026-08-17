"""Acceptance criterion — one line of the yardstick a task is measured against.

Spec 001 FR-019 promotes the old free-text *definition of done* into a list of true/false
statements. The difference is not cosmetic: prose cannot be scored, so in practice it
gated nothing. A criterion can be scored, and each score can point at the artifact that
proves it — which is what makes the two-signature approval of Story 3 mean something.

Two rules ride with it:
  - the list is written **before** the worker starts (a yardstick handed out afterwards is
    just an opinion), and
  - changing it later is a scope-level change, so it goes to the patron (FR-075) rather
    than being edited in place.

The entity keeps its old name and file so the existing checklist UI keeps working; the
legacy `done` tick is now a shadow of `result`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import NamedTuple
from uuid import UUID, uuid4

from armarius.shared.errors import CodedError


class AcceptanceResult(StrEnum):
    UNRATED = "unrated"
    PASSED = "passed"
    FAILED = "failed"


class ChecklistTally(NamedTuple):
    """How many criteria a task has and how many are passed — the ``n/m`` a board card
    draws, without loading the criteria themselves for every card on the board."""

    total: int = 0
    passed: int = 0


class CriteriaLockedError(CodedError):
    """Raised when the yardstick is rewritten after the work has begun (FR-019/FR-075)."""


class CriterionNotRatableError(CodedError):
    """Raised when a criterion is scored outside review (Story 3 scenario 1)."""


class EvidenceRequiredError(CodedError):
    """Raised when a criterion is marked *passed* with nothing that proves it.

    A pass nobody can trace back to an output is the "fake done" this whole story exists
    to stop — the same hole as a signature on a deliverable that is not there (FR-069),
    one level down.
    """


# Statuses in which the criteria may still be written or reworded. Once a worker has
# picked the task up, the bar it is being judged against stops moving.
CRITERIA_EDITABLE_STATUSES: frozenset[str] = frozenset({"draft", "backlog", "todo"})

# The status in which criteria may be scored. Story 3 scenario 1 places the scoring at
# review — *"cho một đầu việc chờ rà soát, khi Trưởng dự án chấm đạt hết tiêu chí"* — and
# it could not be anywhere else: a pass awarded before there is an output to judge says
# nothing about the output, and it would still be sitting there when the output arrives.
CRITERIA_RATABLE_STATUSES: frozenset[str] = frozenset({"in_review"})


def assert_criteria_editable(task: object) -> None:
    """Guard the "set it before they start" rule.

    Takes the task loosely (only its `status` is read) so the criteria entity does not
    have to import the task entity and create a cycle between two peers.
    """
    status = str(getattr(task, "status", ""))
    if status not in CRITERIA_EDITABLE_STATUSES:
        raise CriteriaLockedError("criteria_locked", status=status)


def assert_criteria_ratable(task: object) -> None:
    """Guard the "score it while judging it" rule (Story 3 scenario 1).

    Takes the task loosely for the same reason `assert_criteria_editable` does.
    """
    status = str(getattr(task, "status", ""))
    if status not in CRITERIA_RATABLE_STATUSES:
        raise CriterionNotRatableError("criterion_not_ratable", status=status)


@dataclass
class ChecklistItem:
    id: UUID = field(default_factory=uuid4)
    task_id: UUID | None = None
    text: str = ""
    done: bool = False
    order: int = 0
    result: AcceptanceResult = AcceptanceResult.UNRATED
    # Which published artifact proves this criterion. Empty is normal while unrated.
    evidence_artifact_id: UUID | None = None

    def rate(
        self,
        result: AcceptanceResult,
        *,
        evidence_artifact_id: UUID | None = None,
    ) -> None:
        """Score one criterion, pointing at the output that proves it.

        A pass must name its evidence; a fail need not, because there is nothing to point
        at. The evidence is demanded on **every** pass rather than only the first: the
        criterion is being re-scored against whatever is on the table now, and carrying
        the old artifact id forward would quietly let a pass keep pointing at a draft that
        has since been replaced.
        """
        if result is AcceptanceResult.PASSED and evidence_artifact_id is None:
            raise EvidenceRequiredError("evidence_required", criterion=self.text)
        self.result = result
        self.done = result is AcceptanceResult.PASSED
        self.evidence_artifact_id = evidence_artifact_id


def criteria_not_passed(items: Iterable[ChecklistItem]) -> tuple[str, ...]:
    """The criteria standing between this task and a signature, named.

    Both the unrated and the failed ones, because from the closing side they mean the same
    thing — this yardstick does not yet say the work is done. Names rather than a count:
    *"còn 2 tiêu chí"* leaves the reader hunting for which two.
    """
    return tuple(
        item.text or str(item.id)
        for item in items
        if item.result is not AcceptanceResult.PASSED
    )
