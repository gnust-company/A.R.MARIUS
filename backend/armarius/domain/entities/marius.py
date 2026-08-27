"""Marius (agent) entity — a named, skilled, autonomous worker seated in a project.

Owns two small state machines, both pure here (the application layer adds I/O):
  - invite FSM (LLD §3.4) — operator-invite: invited → approved. The operator entering an
    agent's gateway IS the approval, so the `agent_token` is minted at invite time and
    embedded in the setup prompt the system pushes to the agent (issue #63). There is no
    enroll/approve gate anymore.
  - liveness (LLD §10) — recency+probe model: ONLINE→CHECKING→OFFLINE with backoff. The
    transition logic lives in `domain.services.liveness_fsm`; this entity just holds the
    bookkeeping fields it reads/writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from armarius.shared.errors import CodedError, Conflict


class Liveness(StrEnum):
    """Observable liveness state of a Marius, owned by Armarius (not the runtime)."""

    OFFLINE = "offline"
    ONLINE = "online"  # online now (recent signal); also the "free between turns" state — after a
                       # run finalises the agent returns here (last_seen_at just bumped = a signal).
    CHECKING = "checking"  # probing after T1 of silence
    WORKING = "working"
    HUNG = "hung"


class InviteStatus(StrEnum):
    INVITED = "invited"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REVOKED = "revoked"


class InviteError(CodedError):
    """Raised on an illegal invite-lifecycle transition (LLD §3.4)."""


class NameTaken(Conflict):
    """Another agent in this workspace already answers to that name (FR-007h).

    Lives here rather than beside the use case because two layers have to raise the very
    same refusal: the use case, which looks before it writes so the common case reads well,
    and the mapper, which is where the database — the only thing that actually decides —
    says no. A refusal split across two classes is a refusal the caller has to handle twice.
    """


@dataclass
class Marius:
    """An agent identity bound to a runtime adapter.

    `adapter_config` carries whatever connection details that runtime needs, captured
    from the operator at invite time. `agent_token` is the bearer the
    agent uses to call back into the Armarius agent-facing API (whoami/comment/publish) —
    minted at invite time and embedded in the pushed setup prompt (issue #63).
    """

    id: UUID = field(default_factory=uuid4)
    workspace_id: UUID | None = None
    name: str = ""
    # Unique within the workspace (FR-007h). Two agents answering to the same name in the
    # same place leaves nobody — patron or Leader — able to say which one they meant.
    role: str = ""
    # What this agent is told to be, sent to it on every single run (FR-007i). It is the
    # whole of how an agent behaves: there is no per-project role adding to it or
    # overriding it (Constitution V).
    instructions: str = ""
    # What the humans call this agent among themselves (FR-007j). It never reaches the
    # agent — a line meant for the team would otherwise quietly become an instruction.
    description: str = ""
    skills: list[str] = field(default_factory=list)
    # IDs of Skill Shop skills linked to this Marius (drives per-skill install steps
    # in the invitation prompt). Stored as strings to stay ORM/transport-friendly.
    skill_ids: list[str] = field(default_factory=list)
    # No default: which runtime an agent runs on is a decision the caller must make,
    # never one this entity quietly makes for it (FR-040a).
    adapter_type: str = ""
    adapter_config: dict = field(default_factory=dict)
    owner_user_id: str | None = None
    agent_token: str | None = None
    # Invite lifecycle (LLD §3.4) — operator-invite: invited → approved (no enroll/approve).
    invite_status: InviteStatus = InviteStatus.INVITED
    approved_at: datetime | None = None
    # Liveness bookkeeping (LLD §10) — driven by LivenessEngine via liveness_fsm.
    liveness: Liveness = Liveness.OFFLINE
    last_seen_at: datetime | None = None
    probe_attempts: int = 0  # within a CHECKING cycle (≤ max_probe_attempts)
    backoff_step: int = 0  # count of failed OFFLINE cycles; interval = R·factor**step
    next_probe_at: datetime | None = None
    offline_since: datetime | None = None
    turn_started_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def has_skills(self, required: list[str]) -> bool:
        """True when this Marius covers every required skill."""
        owned = {s.lower() for s in self.skills}
        return all(req.lower() in owned for req in required)

    # ── invite FSM (pure; LLD §3.4) ────────────────────────────────────────────
    def activate(self, agent_token: str, now: datetime) -> None:
        """Operator-invite activation: mint the token once and flip to approved.

        Inviting an agent IS the approval (issue #63): the operator entering the agent's
        gateway has already decided to admit it, so the token is minted at invite time and
        embedded in the setup prompt the system pushes. Idempotent re-activation is an
        error — a second mint would silently replace the token an agent already holds.
        Allowed from INVITED (the normal invite path) or PENDING_REVIEW (legacy rows only).
        """
        if self.invite_status == InviteStatus.REVOKED:
            raise InviteError("agent_revoked_cannot_activate")
        if self.invite_status == InviteStatus.APPROVED:
            raise InviteError("agent_already_active")
        self.agent_token = agent_token
        self.approved_at = now
        self.invite_status = InviteStatus.APPROVED

    def revoke(self) -> None:
        """Withdraw an agent's access from any pre-revoked state (LLD §3.4)."""
        if self.invite_status == InviteStatus.REVOKED:
            raise InviteError("agent_cannot_revoke", status=self.invite_status)
        self.invite_status = InviteStatus.REVOKED
