"""Role — a seat definition inside a project's roster (LLD §2.3).

A role names a function ("Backend", "Leader") and how many seats it has. Exactly one
role per project is the leader (`is_leader`), and the leader role ALWAYS has `seats == 1`
(enforced by `domain.services.project_rules.validate_plan`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4


@dataclass
class Role:
    id: UUID = field(default_factory=uuid4)
    project_id: UUID | None = None
    key: str = ""  # stable slug, e.g. "backend", "leader"
    title: str = ""  # human label, e.g. "Backend"
    seats: int = 1  # seat count — the leader role is ALWAYS seats == 1
    is_leader: bool = False
    description: str = ""
    responsibilities: str = ""  # leader-only extra duties
    skill_ids: list[str] = field(default_factory=list)  # optional skills this role carries
    created_at: datetime | None = None
