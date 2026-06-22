"""Marius (agent) entity — a named, skilled, autonomous worker seated in a project."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class Liveness(StrEnum):
    """Observable liveness state of a Marius, owned by Armarius (not the runtime)."""

    OFFLINE = "offline"
    ONLINE = "online"
    WORKING = "working"
    IDLE = "idle"
    HUNG = "hung"


@dataclass
class Marius:
    """An agent identity bound to a runtime adapter.

    `adapter_config` carries connection details (e.g. Hermes gateway base_url +
    api key). `agent_token` is the bearer the agent uses to call back into the
    Armarius agent-facing API (claim/comment/publish).
    """

    id: UUID = field(default_factory=uuid4)
    workspace_id: UUID | None = None
    name: str = ""
    role: str = ""
    skills: list[str] = field(default_factory=list)
    adapter_type: str = "hermes_gateway"
    adapter_config: dict = field(default_factory=dict)
    owner_user_id: str | None = None
    agent_token: str | None = None
    liveness: Liveness = Liveness.OFFLINE
    last_seen_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def has_skills(self, required: list[str]) -> bool:
        """True when this Marius covers every required skill."""
        owned = {s.lower() for s in self.skills}
        return all(req.lower() in owned for req in required)
