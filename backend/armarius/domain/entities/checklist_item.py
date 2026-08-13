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

from dataclasses import dataclass, field
from enum import StrEnum
from typing import NamedTuple
from uuid import UUID, uuid4


class AcceptanceResult(StrEnum):
    UNRATED = "unrated"
    PASSED = "passed"
    FAILED = "failed"


class ChecklistTally(NamedTuple):
    """How many criteria a task has and how many are passed — the ``n/m`` a board card
    draws, without loading the criteria themselves for every card on the board."""

    total: int = 0
    passed: int = 0


class CriteriaLockedError(Exception):
    """Raised when the yardstick is rewritten after the work has begun (FR-019/FR-075)."""


# Statuses in which the criteria may still be written or reworded. Once a worker has
# picked the task up, the bar it is being judged against stops moving.
CRITERIA_EDITABLE_STATUSES: frozenset[str] = frozenset({"draft", "backlog", "todo"})


def assert_criteria_editable(task: object) -> None:
    """Guard the "set it before they start" rule.

    Takes the task loosely (only its `status` is read) so the criteria entity does not
    have to import the task entity and create a cycle between two peers.
    """
    status = str(getattr(task, "status", ""))
    if status not in CRITERIA_EDITABLE_STATUSES:
        raise CriteriaLockedError(
            "Bộ tiêu chí công nhận phải đặt trước khi người phụ trách bắt tay; "
            f"đầu việc đang ở '{status}'. Sửa lúc này là một thay đổi lớn, "
            "phải treo chờ người chủ duyệt."
        )


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
        """Score one criterion, optionally pointing at the evidence."""
        self.result = result
        self.done = result is AcceptanceResult.PASSED
        if evidence_artifact_id is not None:
            self.evidence_artifact_id = evidence_artifact_id
