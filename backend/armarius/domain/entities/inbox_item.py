"""Patron inbox item — one thing waiting on a specific human's decision (spec 001 §11).

The inbox is how the system asks without guessing: whenever a decision belongs to a
patron, an item lands here addressed to exactly that patron (FR-035) and the project
parks on it rather than deciding on their behalf. Items are resolved by the very action
they were waiting for, not dismissed by hand.

Tenant-scoped by `workspace_id` (Constitution I) — a patron never sees an item from a
workspace they are not in, and cross-workspace reads must not leak that one exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class InboxItemKind(StrEnum):
    """Why the patron is being asked. Drives grouping and urgency in the UI."""

    PLAN_APPROVAL = "plan_approval"
    MAJOR_CHANGE_APPROVAL = "major_change_approval"
    QUESTION = "question"
    OUTPUT_ACCEPTANCE = "output_acceptance"
    ESCALATION = "escalation"
    PHASE_DECISION = "phase_decision"


class InboxItemStatus(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    #: The question stopped mattering before anyone answered it — today only because the
    #: project it belonged to was closed (FR-005). Distinct from RESOLVED on purpose: the
    #: patron never answered, and a record that says they did is a false record. It also
    #: keeps the reminder ladder honest, which chases everything still PENDING.
    VOID = "void"


@dataclass
class InboxItem:
    """One pending decision addressed to one patron."""

    id: UUID = field(default_factory=uuid4)
    workspace_id: UUID | None = None
    # The patron who must decide. Routed per FR-035 — never broadcast to everyone.
    recipient_user_id: str = ""
    project_id: UUID | None = None
    # Empty for project-level items (plan approval, phase decision).
    task_id: UUID | None = None
    kind: InboxItemKind = InboxItemKind.QUESTION
    status: InboxItemStatus = InboxItemStatus.PENDING
    title: str = ""
    body: str | None = None
    # 0 → 1 → 2 → 3, driven by the three thinning reminder tiers (FR-065).
    reminder_tier: int = 0
    # Only for escalations (FR-061): what level 1 tried and how often, what level 2
    # decided, and the exact question the patron must answer.
    attempt_dossier: dict[str, object] = field(default_factory=dict)
    created_at: datetime | None = None
    last_reminded_at: datetime | None = None
    #: When it left the waiting list, whichever way it left — answered or voided.
    resolved_at: datetime | None = None
