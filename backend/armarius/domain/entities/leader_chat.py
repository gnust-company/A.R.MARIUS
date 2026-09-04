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

from armarius.shared.errors import CodedError


class ChatState(StrEnum):
    """Turn-taking state of the conversation (offline-ness is derived live, not stored)."""

    IDLE = "idle"  # ready for the patron's next message
    THINKING = "thinking"  # a Leader turn is running → input locked
    FAILED = "failed"  # last Leader turn errored; the patron may retry (treated as idle)


class LeaderChatError(CodedError):
    """Raised on an illegal leader-chat operation (no Leader seated, offline, or busy)."""


@dataclass
class ProjectLeaderConversation:
    id: UUID = field(default_factory=uuid4)
    project_id: UUID | None = None
    leader_marius_id: UUID | None = None
    session_params: dict = field(default_factory=dict)  # native Leader handle (resume)
    transcript: list[dict] = field(default_factory=list)  # [{role: patron|leader, text, ts}]
    state: ChatState = ChatState.IDLE
    # The run taking this conversation's current turn, when the turn is one this process
    # does not carry out itself. A turn handed to a machine ends somewhere else, and the
    # only thing tying that ending back to this chat is the run it was handed over as —
    # ``state`` says a turn is running, this says *which* turn, which is the question asked
    # from the other direction when a run reports itself finished.
    driving_run_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def append(self, role: str, text: str, ts: datetime) -> None:
        self.transcript = [
            *self.transcript,
            {"role": role, "text": text, "ts": ts.isoformat()},
        ]

    def append_system(
        self,
        *,
        code: str,
        params: dict[str, str],
        text: str,
        detail: str,
        ts: datetime,
    ) -> None:
        """Record a wake the system delivered into this conversation (FR-044).

        Not a `patron` turn and not a `leader` one: nobody said this, the system did, and
        rendering it as either puts words in someone's mouth — it used to arrive on screen
        as a bubble from the Leader itself.

        The cause is kept as **code plus parameters**, not as a finished sentence, because
        both an agent and a person read this same turn and they do not read the same
        language (Constitution VII). `text` is the agent's English copy; `detail` is the
        part that only the agent needs (the snag list, the dossier behind an escalation)
        and never reaches the screen.
        """
        self.transcript = [
            *self.transcript,
            {
                "role": "system",
                "code": code,
                "params": dict(params),
                "text": text,
                "detail": detail,
                "ts": ts.isoformat(),
            },
        ]
