"""Workspace & Project entities — pure domain objects (no ORM)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4


@dataclass
class Workspace:
    """A shared cross-team collaboration space."""

    id: UUID = field(default_factory=uuid4)
    name: str = ""
    slug: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class Project:
    """A single initiative inside a workspace; owns tasks, roster and a shared store."""

    id: UUID = field(default_factory=uuid4)
    workspace_id: UUID | None = None
    name: str = ""
    slug: str = ""
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
