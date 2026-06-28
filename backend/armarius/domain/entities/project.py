"""Project entity — a single initiative inside a workspace (LLD §2.2).

A project owns its roster (Roles + SeatGrants), tasks and a shared artifact folder.
Its `status` is a small lifecycle (LLD §3.1): `setup → active → archived`. Activation
is reached ONCE — every seat granted AND every seated agent ONLINE — and never rolls
back. The only behavioral gate keyed off `active` is task commission.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class ProjectStatus(StrEnum):
    SETUP = "setup"
    ACTIVE = "active"
    ARCHIVED = "archived"


def default_project_settings() -> dict:
    """Patron-tunable gates (LLD §2.2). Conservative defaults: review before done."""
    return {
        "require_review_before_done": True,
        "require_approval_for_done": False,
        "comment_required_for_review": False,
    }


@dataclass
class Project:
    """A single initiative inside a workspace; owns tasks, roster and a shared store."""

    id: UUID = field(default_factory=uuid4)
    workspace_id: UUID | None = None
    name: str = ""
    slug: str = ""
    description: str | None = None
    # Commission/brief context (Patron-supplied, all optional).
    objective: str | None = None
    success_metrics: dict | None = None
    target_date: datetime | None = None
    github_url: str | None = None
    context: str | None = None
    settings: dict = field(default_factory=default_project_settings)
    status: ProjectStatus = ProjectStatus.SETUP
    created_by_user_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
