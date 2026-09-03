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

from armarius.shared.errors import CodedError


class OnboardingStatus(StrEnum):
    OPEN = "open"
    FINALIZED = "finalized"
    ABANDONED = "abandoned"


class OnboardingError(CodedError):
    """Raised on an illegal onboarding-session transition."""


@dataclass
class OnboardingSession:
    id: UUID = field(default_factory=uuid4)
    workspace_id: UUID | None = None
    status: OnboardingStatus = OnboardingStatus.OPEN
    transcript: list[dict] = field(default_factory=list)  # [{role, text, ts}]
    collected: dict = field(default_factory=dict)  # accumulating plan
    created_project_id: UUID | None = None
    # The run that is taking the current turn of this interview (FR-040c). The chat is
    # driven one turn at a time by a workspace-level run, and the turn happens somewhere
    # this process cannot watch: it is put on a shelf, a machine takes it, and the only
    # word of it ending arrives later and names the run.
    #
    # So the session has to be findable *from* that run. Going the other way — asking
    # which chat is open in this workspace — answers the wrong question the moment a
    # patron cancels and starts again: the turn of the chat they left would be read as the
    # turn of the chat they are now in, and one silent agent would close the other's chat.
    driving_run_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def add_turn(self, role: str, text: str, ts: datetime | None = None) -> None:
        """Append one chat turn to the transcript (only while the session is open).

        The Workspace Agent runs a scripted playbook (Sprint 7): it greets the Patron,
        proposes a roster from the objective, and on confirmation the service materialises
        the plan. Both sides of that conversation land here as ``{role, text, ts}`` turns.
        """
        if self.status != OnboardingStatus.OPEN:
            raise OnboardingError("onboarding_cannot_message", status=self.status)
        self.transcript = [
            *self.transcript,
            {"role": role, "text": text, "ts": ts.isoformat() if ts else None},
        ]

    def finalize(self, project_id: UUID) -> None:
        """Mark the chat resolved into a real project (Sprint 7 wires the build)."""
        if self.status != OnboardingStatus.OPEN:
            raise OnboardingError("onboarding_cannot_finalize", status=self.status)
        self.status = OnboardingStatus.FINALIZED
        self.created_project_id = project_id

    def abandon(self) -> None:
        if self.status != OnboardingStatus.OPEN:
            raise OnboardingError("onboarding_cannot_abandon", status=self.status)
        self.status = OnboardingStatus.ABANDONED
