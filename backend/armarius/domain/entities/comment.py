"""Comment entity — a message in a task thread (human ↔ agent ↔ agent)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class AuthorKind(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    SYSTEM = "system"


@dataclass
class Comment:
    """A thread message. `mentions` holds Marius ids that should be woken (§3.2)."""

    id: UUID = field(default_factory=uuid4)
    task_id: UUID | None = None
    author_kind: AuthorKind = AuthorKind.SYSTEM
    author_marius_id: UUID | None = None
    author_user_id: str | None = None
    body: str = ""
    mentions: list[UUID] = field(default_factory=list)
    created_at: datetime | None = None
