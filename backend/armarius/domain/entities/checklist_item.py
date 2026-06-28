"""ChecklistItem — a single tick-box on a task (LLD §2.8)."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass
class ChecklistItem:
    id: UUID = field(default_factory=uuid4)
    task_id: UUID | None = None
    text: str = ""
    done: bool = False
    order: int = 0
