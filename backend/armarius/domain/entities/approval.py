"""Approval — one signature on one task (spec 001 FR-033, FR-039).

A task closes on **two** signatures: the Leader, who checks the work against the
acceptance criteria, and the patron responsible for the agent that did the work. One
signature is never enough, and the two cannot be the same party — that is the whole
anti-"fake done" mechanism, and it is why this is a row rather than a boolean.

Rows are **append-only**. A rejection is not overwritten by a later approval: it stands in
the record, the task goes back to *in_progress*, and the next attempt signs a **new
round**. Carrying a signature across rounds would mean a reworked deliverable closing on a
signature given for the old one.

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
    # Which attempt this signature belongs to. Starts at 1 and steps on every rejection,
    # so signatures never leak from a rejected round into the next one.
    round: int = 1
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
