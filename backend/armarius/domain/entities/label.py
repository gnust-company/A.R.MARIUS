"""Label — a workspace-scoped tag applied to tasks (LLD §2.5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4


@dataclass
class Label:
    id: UUID = field(default_factory=uuid4)
    workspace_id: UUID | None = None
    name: str = ""
    color: str = ""  # hex, e.g. "#8a6d3b"
    created_at: datetime | None = None
