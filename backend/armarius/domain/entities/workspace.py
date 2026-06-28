"""Workspace entity — pure domain object (no ORM).

`Project` now lives in `project.py` (LLD §2.2 split it out) and is re-exported here
for backward-compatible imports (`from ...entities.workspace import Project`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

# Re-export so existing `from armarius.domain.entities.workspace import Project` keeps working.
from armarius.domain.entities.project import (  # noqa: F401
    Project,
    ProjectStatus,
    default_project_settings,
)


@dataclass
class Workspace:
    """A shared cross-team collaboration space, owned by a user."""

    id: UUID = field(default_factory=uuid4)
    name: str = ""
    slug: str = ""
    owner_user_id: str | None = None
    # Designated Workspace Agent (FK Marius) that runs agent-assisted onboarding (LLD §2.1).
    workspace_agent_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
