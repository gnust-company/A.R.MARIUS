"""TaskParticipant — a Marius seated on a task (LLD §2.7).

Supersedes the legacy `Task.assigned_marius_id`. Exactly one participant per task is
`is_primary` (the owner); the rest are collaborators. Unique on (task_id, marius_id).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4


@dataclass
class TaskParticipant:
    id: UUID = field(default_factory=uuid4)
    task_id: UUID | None = None
    marius_id: UUID | None = None
    is_primary: bool = False
    joined_at: datetime | None = None
