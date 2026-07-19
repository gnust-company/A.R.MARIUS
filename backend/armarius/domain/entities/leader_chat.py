"""ProjectLeaderConversation — the project-level 1-1 chat with the Leader agent (#82).

This conversation is **project-scoped**: there is at most one per project, it is about
*everything* in the project, and it resumes a dedicated Leader session
``armarius:project:{project_id}:leader`` on every turn (it is not pinned to a single task
the way the old task-shaping chat was).

The Leader is an agent, so every turn is asynchronous. The patron's message and the
Leader's reply (reconstructed from the streamed ``assistant.delta`` events) are both
appended to ``transcript`` for durable history; the live typing streams on the
``leader-chat:{project_id}`` SSE channel. ``state`` drives turn-taking: while a turn is
running the box is ``thinking`` (input locked); it returns to ``idle`` when the Leader
answers. Whether the Leader is reachable at all (offline ⇒ box disabled, no queue) is a
*live* property derived from the Leader's liveness at read time — never persisted here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class ChatState(StrEnum):
    """Turn-taking state of the conversation (offline-ness is derived live, not stored)."""

    IDLE = "idle"  # ready for the patron's next message
    THINKING = "thinking"  # a Leader turn is running → input locked
    FAILED = "failed"  # last Leader turn errored; the patron may retry (treated as idle)


class LeaderChatError(Exception):
    """Raised on an illegal leader-chat operation (no Leader seated, offline, or busy)."""


@dataclass
class ProjectLeaderConversation:
    id: UUID = field(default_factory=uuid4)
    project_id: UUID | None = None
    leader_marius_id: UUID | None = None
    session_params: dict = field(default_factory=dict)  # native Leader handle (resume)
    transcript: list[dict] = field(default_factory=list)  # [{role: patron|leader, text, ts}]
    state: ChatState = ChatState.IDLE
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def append(self, role: str, text: str, ts: datetime) -> None:
        self.transcript = [
            *self.transcript,
            {"role": role, "text": text, "ts": ts.isoformat()},
        ]
