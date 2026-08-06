"""Approval — one signature on one task (spec 001 FR-033, FR-039).

A task closes on **two** signatures: the Leader, who checks the work against the
acceptance criteria, and the patron responsible for the agent that did the work. One
signature is never enough, and the two cannot be the same party — that is the whole
anti-"fake done" mechanism, and it is why this is a row rather than a boolean.

Rows are **append-only**. A rejection is not overwritten by a later approval: it stands in
the record, and the task goes back to *in_progress*. What changes is `superseded` — every
signature on a task that goes back to being worked on is marked as belonging to a review
that is over. Carrying a signature across that line would mean a reworked deliverable
closing on a signature given for the old one.

`is_auto` marks a signature the auto-approval switch supplied on the patron's behalf
(FR-036). It is still a real signature with a real row — the switch spends fewer of the
patron's keystrokes, not less of the record (FR-039).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class SignerKind(StrEnum):
    """Which of the two required signatures this row is."""

    LEADER = "leader"
    PATRON = "patron"


class ApprovalResult(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class ApprovalError(Exception):
    """Raised when a signature cannot be recorded as asked."""


class RejectionNeedsReasonError(ApprovalError):
    """A rejection with no reason leaves the worker nothing to fix (FR-040)."""


@dataclass
class Approval:
    id: UUID = field(default_factory=uuid4)
    task_id: UUID | None = None
    # Set when the task went back to being worked on: this signature was given for a
    # deliverable that no longer exists, so it no longer answers "has the current one been
    # signed?". The row itself stays — who, when, why and the verdict are all still here.
    #
    # A flag rather than an attempt number on purpose. A number has to be *derived* by
    # whoever reads it, and every reader that derives it is a reader that can derive it
    # differently; this is read, not computed.
    superseded: bool = False
    signer_kind: SignerKind = SignerKind.LEADER
    signer_marius_id: UUID | None = None
    signer_user_id: str | None = None
    result: ApprovalResult = ApprovalResult.APPROVE
    reason: str | None = None
    is_auto: bool = False
    signed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.result is ApprovalResult.REJECT and not (self.reason or "").strip():
            raise RejectionNeedsReasonError(
                "Từ chối công nhận thì phải nêu lý do — thợ cần biết sửa gì."
            )
