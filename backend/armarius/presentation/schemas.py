"""Pydantic request/response schemas for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------- workspace
class CreateWorkspaceIn(BaseModel):
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
    created_at: datetime | None = None


# ----------------------------------------------------------------------- marius
class RegisterMariusIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    role: str = ""
    skills: list[str] = Field(default_factory=list)
    adapter_type: str = "hermes_gateway"
    adapter_config: dict = Field(default_factory=dict)
    owner_user_id: str | None = None


class MariusOut(_Out):
    id: UUID
    workspace_id: UUID | None = None
    name: str
    role: str
    skills: list[str]
    adapter_type: str
    liveness: str
    last_seen_at: datetime | None = None
    created_at: datetime | None = None


class MariusCreatedOut(MariusOut):
    agent_token: str | None = None
    invite: str | None = None


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
class PublishArtifactIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    kind: str = "file"
    content: str | None = None  # text content for file/patch/note
    uri: str | None = None  # for kind="link"


class ArtifactOut(_Out):
    id: UUID
    task_id: UUID | None = None
    marius_id: UUID | None = None
    name: str
    kind: str
    uri: str
    content_sha256: str | None = None
    size_bytes: int | None = None
    created_at: datetime | None = None


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
    content: str | None = None
    uri: str | None = None
