"""OnboardingSession — agent-assisted project setup chat (LLD §2.10).

The Workspace Agent interviews the Patron; the running plan accumulates in `collected`
until `finalize` builds a real Project (Sprint 7 / Phase G). Pure here: just the small
status FSM `open → finalized | abandoned`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class OnboardingStatus(StrEnum):
    OPEN = "open"
    FINALIZED = "finalized"
    ABANDONED = "abandoned"


class OnboardingError(Exception):
    """Raised on an illegal onboarding-session transition."""


@dataclass
class OnboardingSession:
    id: UUID = field(default_factory=uuid4)
    workspace_id: UUID | None = None
    status: OnboardingStatus = OnboardingStatus.OPEN
    transcript: list[dict] = field(default_factory=list)  # [{role, text, ts}]
    collected: dict = field(default_factory=dict)  # accumulating plan
    created_project_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def add_turn(self, role: str, text: str, ts: datetime | None = None) -> None:
        """Append one chat turn to the transcript (only while the session is open).

        The Workspace Agent runs a scripted playbook (Sprint 7): it greets the Patron,
        proposes a roster from the objective, and on confirmation the service materialises
        the plan. Both sides of that conversation land here as ``{role, text, ts}`` turns.
        """
        if self.status != OnboardingStatus.OPEN:
            raise OnboardingError(f"Cannot message a '{self.status}' onboarding session.")
        self.transcript = [
            *self.transcript,
            {"role": role, "text": text, "ts": ts.isoformat() if ts else None},
        ]

    def finalize(self, project_id: UUID) -> None:
        """Mark the chat resolved into a real project (Sprint 7 wires the build)."""
        if self.status != OnboardingStatus.OPEN:
            raise OnboardingError(f"Cannot finalize a '{self.status}' onboarding session.")
        self.status = OnboardingStatus.FINALIZED
        self.created_project_id = project_id

    def abandon(self) -> None:
        if self.status != OnboardingStatus.OPEN:
            raise OnboardingError(f"Cannot abandon a '{self.status}' onboarding session.")
        self.status = OnboardingStatus.ABANDONED
