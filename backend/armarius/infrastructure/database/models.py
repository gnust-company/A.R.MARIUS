"""SQLAlchemy ORM models. Kept separate from domain entities (mapped in persistence)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class WorkspaceModel(Base):
    __tablename__ = "workspaces"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(200))
    owner_user_id: Mapped[str | None] = mapped_column(String(200), index=True)
    # The designated host Marius (#32). Plain UUID, no FK — a workspaces→mariuses FK
    # would be circular (mariuses.workspace_id already points back here).
    workspace_agent_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LabelModel(Base):
    """Workspace-scoped task tag (API_CONTRACT §5.4)."""

    __tablename__ = "labels"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    color: Mapped[str] = mapped_column(String(20), default="")
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectModel(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("workspace_id", "key", name="uq_project_ws_key"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(200))
    # Short uppercase code unique per workspace — the KEY in task identifiers "{key}-{n}".
    key: Mapped[str | None] = mapped_column(String(10), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    # Lifecycle (LLD §3.1): setup → active → archived. Activation is one-way.
    status: Mapped[str] = mapped_column(String(20), default="setup", index=True)
    # Monotonic per-project task counter (atomically incremented via allocate_task_number).
    next_task_seq: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # Commission/brief context (Patron-supplied, all optional).
    objective: Mapped[str | None] = mapped_column(Text)
    success_metrics: Mapped[dict | None] = mapped_column(JSON)
    target_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    github_url: Mapped[str | None] = mapped_column(Text)
    context: Mapped[str | None] = mapped_column(Text)
    settings: Mapped[dict | None] = mapped_column(JSON, default=dict)
    created_by_user_id: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RoleModel(Base):
    """A roster seat definition inside a project (LLD §2.3)."""

    __tablename__ = "roles"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("projects.id"), index=True)
    key: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(200), default="")
    seats: Mapped[int] = mapped_column(Integer, default=1)
    is_leader: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(Text, default="")
    skill_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SeatGrantModel(Base):
    """A system-only seat assignment of a Marius to a role (LLD §2.4, §3.3)."""

    __tablename__ = "seat_grants"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("projects.id"), index=True)
    role_key: Mapped[str] = mapped_column(String(120))
    marius_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    status: Mapped[str] = mapped_column(String(20), default="granted")
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MariusModel(Base):
    __tablename__ = "mariuses"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(120), default="")
    skills: Mapped[list] = mapped_column(JSON, default=list)
    adapter_type: Mapped[str] = mapped_column(String(80))
    adapter_config: Mapped[dict] = mapped_column(JSON, default=dict)
    skill_ids: Mapped[list] = mapped_column(JSON, default=list)
    # Per-skill install state (post-invite loop #74): slug → pending|installed|failed.
    skill_installs: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    owner_user_id: Mapped[str | None] = mapped_column(String(200))
    agent_token: Mapped[str | None] = mapped_column(String(120), unique=True, index=True)
    # Invite lifecycle (LLD §3.4) — operator-invite: invited → approved (no enroll/approve).
    invite_status: Mapped[str] = mapped_column(String(20), default="invited")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Liveness bookkeeping (LLD §10) — driven by LivenessEngine via liveness_fsm.
    liveness: Mapped[str] = mapped_column(String(20), default="offline")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    probe_attempts: Mapped[int] = mapped_column(Integer, default=0)
    backoff_step: Mapped[int] = mapped_column(Integer, default=0)
    next_probe_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    offline_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    turn_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskModel(Base):
    __tablename__ = "tasks"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("projects.id"), index=True)
    identifier: Mapped[str | None] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="backlog", index=True)
    status_reason: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    definition_of_done: Mapped[str | None] = mapped_column(Text)
    assigned_marius_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    created_by_user_id: Mapped[str | None] = mapped_column(String(200))
    created_by_marius_id: Mapped[UUID | None] = mapped_column(Uuid)
    next_action: Mapped[str | None] = mapped_column(Text)
    in_progress_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskDependencyModel(Base):
    """A `blocked_by` edge: `task_id` waits on `blocks_task_id` (unique per pair)."""

    __tablename__ = "task_dependencies"
    __table_args__ = (
        UniqueConstraint("task_id", "blocks_task_id", name="uq_task_dependency_pair"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    task_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tasks.id"), index=True)
    blocks_task_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tasks.id"), index=True)


class CommentModel(Base):
    __tablename__ = "comments"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    task_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tasks.id"), index=True)
    author_kind: Mapped[str] = mapped_column(String(20), default="system")
    author_marius_id: Mapped[UUID | None] = mapped_column(Uuid)
    author_user_id: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    mentions: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class ProjectLeaderConversationModel(Base):
    """Project-level Chat-with-Leader conversation (#82). At most one per project
    (``project_id`` is unique). Plain UUID refs (no FK) — consistent with the other
    runtime chat tables (onboarding sessions)."""

    __tablename__ = "project_leader_conversations"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID | None] = mapped_column(Uuid, unique=True, index=True)
    leader_marius_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    session_params: Mapped[dict] = mapped_column(JSON, default=dict)
    transcript: Mapped[list] = mapped_column(JSON, default=list)
    state: Mapped[str] = mapped_column(String(20), default="idle", index=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OnboardingSessionModel(Base):
    """Agent-assisted project-setup chat (LLD §2.10, Sprint 7 / Phase G). Plain UUID
    ref to the workspace (no FK) — consistent with the other runtime chat tables."""

    __tablename__ = "onboarding_sessions"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    workspace_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    transcript: Mapped[list] = mapped_column(JSON, default=list)
    collected: Mapped[dict] = mapped_column(JSON, default=dict)
    created_project_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SessionModel(Base):
    __tablename__ = "agent_task_sessions"
    __table_args__ = (
        UniqueConstraint(
            "marius_id", "adapter_type", "task_id", name="uq_session_marius_adapter_task"
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID | None] = mapped_column(Uuid)
    marius_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    adapter_type: Mapped[str] = mapped_column(String(80))
    task_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    session_params_json: Mapped[dict] = mapped_column(JSON, default=dict)
    session_display_id: Mapped[str | None] = mapped_column(String(200))
    last_run_id: Mapped[UUID | None] = mapped_column(Uuid)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunModel(Base):
    __tablename__ = "runs"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID | None] = mapped_column(Uuid)
    marius_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    task_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    adapter_type: Mapped[str] = mapped_column(String(80), default="")
    wake_source: Mapped[str] = mapped_column(String(40), default="on_demand")
    trigger_detail: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    external_run_id: Mapped[str | None] = mapped_column(String(200))
    session_id_before: Mapped[str | None] = mapped_column(Text)
    session_id_after: Mapped[str | None] = mapped_column(Text)
    usage_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    next_action: Mapped[str | None] = mapped_column(Text)
    continuation_attempt: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_output_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class RunEventModel(Base):
    __tablename__ = "run_events"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("runs.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    type: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ArtifactModel(Base):
    __tablename__ = "artifacts"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID | None] = mapped_column(Uuid)
    task_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tasks.id"), index=True)
    marius_id: Mapped[UUID | None] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(40), default="file")
    uri: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WakeupModel(Base):
    __tablename__ = "wakeup_requests"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID | None] = mapped_column(Uuid)
    marius_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    task_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    source: Mapped[str] = mapped_column(String(40), default="on_demand")
    reason: Mapped[str | None] = mapped_column(Text)
    prompt: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    run_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SkillModel(Base):
    """An installable skill in a workspace's Skill Shop."""

    __tablename__ = "skills"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_skill_workspace_slug"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("workspaces.id"), index=True
    )
    slug: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="builtin")
    source_url: Mapped[str] = mapped_column(Text, default="")
    files: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserModel(Base):
    """Human users of Armarius (Patrons)."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        UniqueConstraint("username", name="uq_users_username"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    username: Mapped[str] = mapped_column(String(80))
    full_name: Mapped[str] = mapped_column(String(200))
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="patron")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
