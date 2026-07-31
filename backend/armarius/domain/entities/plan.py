"""Project plan and its items (spec 001 §3).

The plan is what the patron actually approves, and its **items are the definition of
"in scope"** (FR-027): a task attached to an approved item is created and assigned
straight away; a task attached to nothing has to wait for a decision. That is why items
are first-class rows rather than prose — a paragraph cannot be pointed at by a task.

The plan carries its own approval state so a rejected plan keeps its history: the note
the patron wrote is on the plan the Leader has to fix, not lost in a chat log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class PlanStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"


@dataclass
class PlanItem:
    """One piece of the plan — the unit a task can point at to prove it is in scope."""

    id: UUID = field(default_factory=uuid4)
    plan_id: UUID | None = None
    title: str = ""
    description: str = ""
    order: int = 0
    # Other items this one waits on. Item-level ordering, not task-level dependency.
    depends_on: list[UUID] = field(default_factory=list)
    # What "done" means for the whole item, above any individual task's criteria.
    definition_of_done: str = ""
    created_at: datetime | None = None


@dataclass
class Plan:
    """One version of a project's plan."""

    id: UUID = field(default_factory=uuid4)
    project_id: UUID | None = None
    version: int = 1
    summary: str = ""
    risks: str = ""
    milestones: str = ""
    status: PlanStatus = PlanStatus.DRAFT
    # Set when the patron asks for changes or asks a question — the Leader reads it and
    # resubmits. Cleared on approval.
    patron_note: str | None = None
    submitted_at: datetime | None = None
    decided_at: datetime | None = None
    decided_by_user_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Loaded alongside the plan; persisted as its own table.
    items: list[PlanItem] = field(default_factory=list)

    def is_approved(self) -> bool:
        return self.status is PlanStatus.APPROVED
