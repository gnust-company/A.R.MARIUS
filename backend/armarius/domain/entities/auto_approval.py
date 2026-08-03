"""AutoApproval — one patron's "stop asking me" switch on one project (spec 001 FR-036 → FR-039).

Keyed by the pair *(project, patron)*, not by project alone. Today every project has
exactly one patron (chốt 2026-08-03), so the pair looks like waste — but collapsing it to
a project-level flag throws away *whose* switch it was, and that is not recoverable later.

Three things the switch must not do:

  - start on (FR-038): silently signing for a patron who never asked is the failure the
    two-signature rule exists to prevent;
  - be reachable by the Leader (FR-038): an agent that can waive its own second signature
    has reduced two signatures to one;
  - reach the three project-level decisions (FR-037) — approving the plan, approving a
    major change, moving the project between phases. Those always need a real hand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4


@dataclass
class AutoApproval:
    id: UUID = field(default_factory=uuid4)
    project_id: UUID | None = None
    # The patron this switch belongs to. Nobody else may flip it.
    user_id: str = ""
    enabled: bool = False
    updated_at: datetime | None = None
    created_at: datetime | None = None
