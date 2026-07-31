"""Project context — the five-part brief every wake packet carries (spec 001 §2).

This is the "why" an agent needs before it can judge anything: the ultimate objective,
the background, the hard constraints, the scope, and the shared principles. It is
*versioned and approved* rather than free-form, because agents act on it: an edit that
changes the objective or the scope must not silently take effect (FR-010). Editing
produces a new **submitted** version alongside the approved one; only the approved
version is attached to wake packets (FR-009).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class ContextApprovalStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"


@dataclass
class ProjectContext:
    """One version of a project's brief."""

    id: UUID = field(default_factory=uuid4)
    project_id: UUID | None = None
    # Monotonic per project. Version 1 is the first thing the Leader submits.
    version: int = 1
    # The five parts. Empty is allowed and rendered as "không có" in the wake packet
    # (FR-045) — an absent part must read as absent, never as an invisible gap.
    objective: str = ""
    background: str = ""
    constraints: str = ""
    scope: str = ""
    principles: str = ""
    approval_status: ContextApprovalStatus = ContextApprovalStatus.DRAFT
    approved_at: datetime | None = None
    approved_by_user_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def is_approved(self) -> bool:
        return self.approval_status is ContextApprovalStatus.APPROVED
