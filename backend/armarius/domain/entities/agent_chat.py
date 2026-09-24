"""AgentConversation — the patron talking to one of their agents directly (FR-007p).

Not about a project and not about a task. The project chat (``ProjectLeaderConversation``) is
the Leader answering for a project; this is the patron and one agent, the way a person
messages a colleague before there is any work to hand them. At most one per agent.

Every turn is a run like any other, so it shows in the agent's activity and is taken where
the agent works. The transcript is the durable history; the live typing streams on the
``agent-chat:{marius_id}`` channel; ``state`` does the turn-taking. Whether the agent can be
reached at all is read live off its liveness and never stored here — the same rule the
project chat follows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from armarius.domain.entities.leader_chat import ChatState
from armarius.shared.errors import CodedError


class AgentChatError(CodedError):
    """Raised on an illegal direct-chat operation (agent unreachable, or still replying)."""


@dataclass
class AgentConversation:
    id: UUID = field(default_factory=uuid4)
    marius_id: UUID | None = None
    transcript: list[dict] = field(default_factory=list)  # [{role: patron|agent, text, ts}]
    state: ChatState = ChatState.IDLE
    # The run taking the current turn. A turn taken somewhere else ends somewhere else, and
    # the run is the only thing tying that ending back to this conversation — see
    # ``ProjectLeaderConversation.driving_run_id``, which is the same idea for the same reason.
    driving_run_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def append(self, role: str, text: str, ts: datetime) -> None:
        self.transcript = [
            *self.transcript,
            {"role": role, "text": text, "ts": ts.isoformat()},
        ]
