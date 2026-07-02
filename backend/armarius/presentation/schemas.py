"""Pydantic request/response schemas for the HTTP API."""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------- workspace
class CreateWorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class UpdateWorkspaceIn(BaseModel):
    """Rename a workspace (slug is re-derived from the name)."""

    name: str = Field(min_length=1, max_length=200)


class WorkspaceOut(_Out):
    id: UUID
    name: str
    slug: str
    created_at: datetime | None = None


class CreateProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None


class ProjectOut(_Out):
    id: UUID
    workspace_id: UUID | None = None
    name: str
    slug: str
    description: str | None = None
    # Lifecycle (setup → active → archived) + brief so the project list can render a real
    # status chip and objective line without opening the detail view.
    status: str = "setup"
    objective: str | None = None
    created_at: datetime | None = None


# ------------------------------------------------- projects + roster (contract §3)
class LeaderIn(BaseModel):
    responsibilities: str = ""
    marius_id: UUID | None = None


class RoleIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    seats: int = Field(default=1, ge=1)
    description: str = ""
    skill_ids: list[str] = Field(default_factory=list)
    marius_ids: list[UUID | None] = Field(default_factory=list)  # pre-seat (len ≤ seats)


class CreateProjectPlanIn(BaseModel):
    """A complete seat plan (API_CONTRACT §3.1): one leader + ≥1 worker role."""

    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    mode: str = "manual"
    objective: str | None = None
    success_metrics: dict | None = None
    target_date: datetime | None = None
    github_url: str | None = None
    context: str | None = None
    leader: LeaderIn = Field(default_factory=LeaderIn)
    roles: list[RoleIn] = Field(default_factory=list)
    settings: dict | None = None
    onboarding_session_id: UUID | None = None


class UpdateProjectIn(BaseModel):
    description: str | None = None
    objective: str | None = None
    success_metrics: dict | None = None
    target_date: datetime | None = None
    github_url: str | None = None
    context: str | None = None
    settings: dict | None = None


class SeatOut(BaseModel):
    marius_id: UUID
    name: str
    role_key: str
    liveness: str
    is_primary: bool


class RosterRoleOut(BaseModel):
    key: str
    title: str
    seats: int
    is_leader: bool
    description: str
    skill_ids: list[str]
    filled: int
    seated: list[SeatOut]


class ProjectDetailOut(_Out):
    id: UUID
    workspace_id: UUID | None = None
    name: str
    slug: str
    description: str | None = None
    status: str
    objective: str | None = None
    success_metrics: dict | None = None
    target_date: datetime | None = None
    github_url: str | None = None
    context: str | None = None
    settings: dict | None = None
    created_by_user_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    roster: list[RosterRoleOut] = Field(default_factory=list)


class AddRoleIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    seats: int = Field(default=1, ge=1)
    description: str = ""
    responsibilities: str = ""
    skill_ids: list[str] = Field(default_factory=list)
    is_leader: bool = False


class UpdateRoleIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    seats: int | None = Field(default=None, ge=1)
    description: str | None = None
    responsibilities: str | None = None
    skill_ids: list[str] | None = None


class RoleOut(_Out):
    id: UUID
    project_id: UUID | None = None
    key: str
    title: str
    seats: int
    is_leader: bool
    description: str = ""
    responsibilities: str = ""
    skill_ids: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


# ------------------------------------------------------- labels (contract §5.4)
class CreateLabelIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    color: str = Field(default="", max_length=20)


class LabelOut(_Out):
    id: UUID
    workspace_id: UUID | None = None
    name: str
    color: str = ""
    created_at: datetime | None = None


class GrantSeatIn(BaseModel):
    marius_id: UUID
    role_key: str = Field(min_length=1, max_length=200)


class SeatGrantOut(_Out):
    id: UUID
    project_id: UUID | None = None
    role_key: str
    marius_id: UUID | None = None
    status: str
    granted_at: datetime | None = None
    created_at: datetime | None = None


# ------------------------------------------------------------------------ skill
class SkillOut(_Out):
    id: UUID
    workspace_id: UUID | None = None
    slug: str
    name: str
    description: str = ""
    source: str
    source_url: str = ""
    files: dict[str, str] = Field(default_factory=dict)
    created_at: datetime | None = None


class ManualSkillIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


class ImportSkillIn(BaseModel):
    source_url: str = Field(min_length=1, max_length=2000)


class UpdateSkillIn(BaseModel):
    files: dict[str, str] = Field(default_factory=dict)


# ----------------------------------------------------------------- agent skills
class AgentSkillSummary(_Out):
    """One skill linked to the calling agent — enough to know it exists and how big it
    is. Fetch its full file tree from GET /agent/skills/{slug}."""

    slug: str
    name: str
    description: str = ""
    file_count: int


class AgentSkillBundleOut(_Out):
    """A linked skill's complete file tree (path → content) so the agent can write each
    file under its runtime's skills directory."""

    slug: str
    name: str
    description: str = ""
    files: dict[str, str] = Field(default_factory=dict)


# ----------------------------------------------------------------------- marius
class RegisterMariusIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    role: str = ""
    skills: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)
    adapter_type: str = "hermes_gateway"
    adapter_config: dict = Field(default_factory=dict)
    owner_user_id: str | None = None


class UpdateMariusIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    role: str | None = None
    skills: list[str] | None = None
    skill_ids: list[str] | None = None
    adapter_type: str | None = None
    adapter_config: dict | None = None


class MariusOut(_Out):
    id: UUID
    workspace_id: UUID | None = None
    name: str
    role: str
    skills: list[str]
    skill_ids: list[str] = Field(default_factory=list)
    adapter_type: str
    liveness: str
    last_seen_at: datetime | None = None
    created_at: datetime | None = None


class MariusCreatedOut(MariusOut):
    agent_token: str | None = None
    invite: str | None = None
    enrollment_code: str | None = None
    invite_status: str | None = None


# enroll-and-wait agent surface (API_CONTRACT §4.1, §9)
class AgentEnrollIn(BaseModel):
    marius_id: UUID
    enrollment_code: str = Field(min_length=1)
    capabilities: list[str] = Field(default_factory=list)
    adapter_config: dict = Field(default_factory=dict)


class AgentClaimIn(BaseModel):
    marius_id: UUID
    enrollment_code: str = Field(min_length=1)


class AgentTokenOut(BaseModel):
    agent_token: str


class MetaOut(BaseModel):
    version: str
    public_base_url: str
    adapters: list[str]


# ------------------------------------------------------------------------- task
class CreateTaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    created_by_user_id: str | None = None


class AssignIn(BaseModel):
    marius_id: UUID


class TransitionIn(BaseModel):
    status: str
    reason: str | None = None


class NextActionIn(BaseModel):
    next_action: str | None = None


class TaskOut(_Out):
    id: UUID
    project_id: UUID | None = None
    title: str
    description: str | None = None
    status: str
    status_reason: str | None = None
    assigned_marius_id: UUID | None = None
    next_action: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------------- comment
class PostCommentIn(BaseModel):
    body: str = Field(min_length=1)
    author_kind: str = "human"
    author_user_id: str | None = None
    extra_mentions: list[UUID] = Field(default_factory=list)


class CommentOut(_Out):
    id: UUID
    task_id: UUID | None = None
    author_kind: str
    author_marius_id: UUID | None = None
    author_user_id: str | None = None
    body: str
    mentions: list[UUID]
    created_at: datetime | None = None


# --------------------------------------------------------------------- artifact
def decode_artifact_content(
    *,
    content_b64: str | None,
    content: str | None,
    content_sha256: str | None = None,
) -> bytes | None:
    """Resolve uploaded bytes for a `file` artifact (API_CONTRACT §7).

    Prefers base64 `content_b64` (decoded + optionally sha256-verified); falls back to raw
    text `content` for back-compat. Returns None when neither is present (e.g. a `link`).
    """
    if content_b64 is not None:
        try:
            raw = base64.b64decode(content_b64, validate=True)
        except (ValueError, base64.binascii.Error) as e:
            raise ValueError("content_b64 is not valid base64") from e
        if content_sha256 and hashlib.sha256(raw).hexdigest() != content_sha256:
            raise ValueError("content_sha256 does not match the uploaded bytes")
        return raw
    if content is not None:
        return content.encode("utf-8")
    return None


class PublishArtifactIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    kind: str = "file"
    content_b64: str | None = None  # REQUIRED for kind="file" (decoded + sha256-verified)
    content: str | None = None  # legacy: raw text content (utf-8)
    content_sha256: str | None = None
    size_bytes: int | None = None
    uri: str | None = None  # REQUIRED for kind="link"


class ArtifactOut(_Out):
    id: UUID
    project_id: UUID | None = None
    task_id: UUID | None = None
    marius_id: UUID | None = None
    name: str
    kind: str
    uri: str
    stored: bool = False
    content_sha256: str | None = None
    size_bytes: int | None = None
    created_at: datetime | None = None

    @model_validator(mode="after")
    def _derive_stored(self) -> ArtifactOut:
        # file ⇒ bytes live in the bucket; link ⇒ external uri (not stored). (§7)
        self.stored = self.kind == "file"
        return self


# -------------------------------------------------------------------------- run
class WakeIn(BaseModel):
    marius_id: UUID
    reason: str | None = None


class RunOut(_Out):
    id: UUID
    task_id: UUID | None = None
    marius_id: UUID | None = None
    adapter_type: str
    wake_source: str
    status: str
    external_run_id: str | None = None
    error: str | None = None
    next_action: str | None = None
    continuation_attempt: int = 0
    usage_json: dict = Field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None


class RunEventOut(_Out):
    seq: int
    type: str
    payload: dict
    created_at: datetime | None = None


class RunStartedOut(BaseModel):
    run_id: UUID


# ------------------------------------------------------------------ agent-facing
class AgentCommentIn(BaseModel):
    body: str = Field(min_length=1)


class AgentArtifactIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    kind: str = "file"
    content_b64: str | None = None
    content: str | None = None
    content_sha256: str | None = None
    uri: str | None = None


# ------------------------------------------------------------------- commission
class CommissionStartIn(BaseModel):
    project_id: UUID
    message: str = Field(min_length=1)
    title: str | None = Field(default=None, min_length=1, max_length=300)


class CommissionRefineIn(BaseModel):
    message: str = Field(min_length=1)


class CommissionEditIn(BaseModel):
    task_id: UUID
    message: str = Field(min_length=1)


class CommissionOut(_Out):
    id: UUID
    project_id: UUID | None = None
    leader_marius_id: UUID | None = None
    task_id: UUID | None = None
    status: str
    leader_state: str
    transcript: list[dict] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ------------------------------------------------------------------ onboarding
# Agent-assisted project setup (Sprint 7 / Phase G). The Workspace Agent interviews the
# Patron; `finalize` materialises the accumulated plan into a Project + roster.
class OnboardingMessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class OnboardingOut(_Out):
    id: UUID
    workspace_id: UUID | None = None
    status: str
    transcript: list[dict] = Field(default_factory=list)
    collected: dict = Field(default_factory=dict)
    created_project_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

