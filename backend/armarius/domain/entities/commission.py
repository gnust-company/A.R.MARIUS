"""CommissionSession — leader-mediated task shaping (LLD §2.13).

A commission chat targets exactly ONE Task: a fresh `draft` (new task) or an existing
confirmed task (an edit). Refine turns resume `session_params`; `confirm` flips a draft
`draft → todo`. Because the Leader is an agent every turn is async — `leader_state`
surfaces progress to the Patron between SSE updates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class CommissionStatus(StrEnum):
    OPEN = "open"
    CONFIRMED = "confirmed"
    ABANDONED = "abandoned"


class LeaderState(StrEnum):
    """Async progress of the Leader's current turn, shown to the Patron."""

    THINKING = "thinking"
    WAITING = "waiting"
    LEADER_OFFLINE = "leader_offline"


class CommissionError(Exception):
    """Raised on an illegal commission-session transition."""


@dataclass
class CommissionSession:
    id: UUID = field(default_factory=uuid4)
    project_id: UUID | None = None
    leader_marius_id: UUID | None = None
    task_id: UUID | None = None  # the draft (new) or confirmed task (edit) being shaped
    session_params: dict = field(default_factory=dict)  # native Leader handle (resume)
    transcript: list[dict] = field(default_factory=list)  # [{role, text, ts}]
    status: CommissionStatus = CommissionStatus.OPEN
    leader_state: LeaderState = LeaderState.THINKING
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def confirm(self) -> None:
        """Lock the proposal (the draft→todo flip happens in the task, via the service)."""
        if self.status != CommissionStatus.OPEN:
            raise CommissionError(f"Cannot confirm a '{self.status}' commission.")
        self.status = CommissionStatus.CONFIRMED

    def abandon(self) -> None:
        if self.status != CommissionStatus.OPEN:
            raise CommissionError(f"Cannot abandon a '{self.status}' commission.")
        self.status = CommissionStatus.ABANDONED
