"""Marius (agent) entity — a named, skilled, autonomous worker seated in a project.

Owns two small state machines, both pure here (the application layer adds I/O):
  - invite FSM (LLD §3.4) — enroll-and-wait: invited → pending_review → approved; the
    `agent_token` is minted ONCE on approve, never at invite time.
  - liveness (LLD §10) — recency+probe model: ONLINE→CHECKING→OFFLINE with backoff. The
    transition logic lives in `domain.services.liveness_fsm`; this entity just holds the
    bookkeeping fields it reads/writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class Liveness(StrEnum):
    """Observable liveness state of a Marius, owned by Armarius (not the runtime)."""

    OFFLINE = "offline"
    ONLINE = "online"
    CHECKING = "checking"  # probing after T1 of silence (replaces legacy IDLE)
    WORKING = "working"
    HUNG = "hung"
    IDLE = "idle"  # DEPRECATED — kept for back-compat; CHECKING supersedes it (LLD §10)


class InviteStatus(StrEnum):
    INVITED = "invited"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REVOKED = "revoked"


class InviteError(Exception):
    """Raised on an illegal invite-lifecycle transition (LLD §3.4)."""


@dataclass
class Marius:
    """An agent identity bound to a runtime adapter.

    `adapter_config` carries connection details (e.g. Hermes gateway base_url +
    api key). `agent_token` is the bearer the agent uses to call back into the
    Armarius agent-facing API (claim/comment/publish) — minted on approval, not invite.
    """

    id: UUID = field(default_factory=uuid4)
    workspace_id: UUID | None = None
    name: str = ""
    role: str = ""
    skills: list[str] = field(default_factory=list)
    # IDs of Skill Shop skills linked to this Marius (drives per-skill install steps
    # in the invitation prompt). Stored as strings to stay ORM/transport-friendly.
    skill_ids: list[str] = field(default_factory=list)
    adapter_type: str = "hermes_gateway"
    adapter_config: dict = field(default_factory=dict)
    owner_user_id: str | None = None
    agent_token: str | None = None
    # Invite lifecycle (LLD §3.4) — enroll-and-wait.
    invite_status: InviteStatus = InviteStatus.INVITED
    enrollment_code: str | None = None  # issued at invite; used ONCE on /agent/enroll
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
    def begin_enroll(self) -> None:
        """Agent presented the enrollment_code → hold for Patron review. Idempotent."""
        if self.invite_status not in (InviteStatus.INVITED, InviteStatus.PENDING_REVIEW):
            raise InviteError(f"Cannot enroll from '{self.invite_status}'.")
        self.invite_status = InviteStatus.PENDING_REVIEW

    def approve(self, agent_token: str, now: datetime) -> None:
        """Patron approves → mint the token ONCE and flip to approved."""
        if self.invite_status != InviteStatus.PENDING_REVIEW:
            raise InviteError(f"Cannot approve from '{self.invite_status}'.")
        self.agent_token = agent_token
        self.approved_at = now
        self.invite_status = InviteStatus.APPROVED

    def revoke(self) -> None:
        """Withdraw an invite before approval (LLD §3.4)."""
        if self.invite_status not in (InviteStatus.INVITED, InviteStatus.PENDING_REVIEW):
            raise InviteError(f"Cannot revoke from '{self.invite_status}'.")
        self.invite_status = InviteStatus.REVOKED

    def token_for_claim(self) -> str:
        """Recovery path: return the token iff already approved (LLD §12)."""
        if self.invite_status != InviteStatus.APPROVED or not self.agent_token:
            raise InviteError("Claim is only valid after approval.")
        return self.agent_token
