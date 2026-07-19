"""ORM ↔ domain entity mapping. Keeps the domain free of SQLAlchemy."""

from __future__ import annotations

from uuid import UUID

from armarius.domain.entities.artifact import Artifact
from armarius.domain.entities.comment import AuthorKind, Comment
from armarius.domain.entities.commission import (
    CommissionSession,
    CommissionStatus,
    LeaderState,
)
from armarius.domain.entities.label import Label
from armarius.domain.entities.leader_chat import (
    ChatState,
    ProjectLeaderConversation,
)
from armarius.domain.entities.marius import InviteStatus, Liveness, Marius
from armarius.domain.entities.onboarding import OnboardingSession, OnboardingStatus
from armarius.domain.entities.project import (
    Project,
    ProjectStatus,
    default_project_settings,
)
from armarius.domain.entities.role import Role
from armarius.domain.entities.run import Run, RunEvent, RunStatus, WakeSource
from armarius.domain.entities.seat_grant import SeatGrant, SeatGrantStatus
from armarius.domain.entities.session import AgentTaskSession
from armarius.domain.entities.skill import Skill
from armarius.domain.entities.task import Task, TaskPriority, TaskStatus
from armarius.domain.entities.task_dependency import TaskDependency
from armarius.domain.entities.user import User, UserRole
from armarius.domain.entities.wakeup import WakeupRequest, WakeupStatus
from armarius.domain.entities.workspace import Workspace
from armarius.infrastructure.database.models import (
    ArtifactModel,
    CommentModel,
    CommissionModel,
    LabelModel,
    MariusModel,
    OnboardingSessionModel,
    ProjectLeaderConversationModel,
    ProjectModel,
    RoleModel,
    RunEventModel,
    RunModel,
    SeatGrantModel,
    SessionModel,
    SkillModel,
    TaskDependencyModel,
    TaskModel,
    UserModel,
    WakeupModel,
    WorkspaceModel,
)


def workspace_to_entity(m: WorkspaceModel) -> Workspace:
    return Workspace(
        id=m.id,
        name=m.name,
        slug=m.slug,
        owner_user_id=m.owner_user_id,
        workspace_agent_id=m.workspace_agent_id,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def project_to_entity(m: ProjectModel) -> Project:
    return Project(
        id=m.id,
        workspace_id=m.workspace_id,
        name=m.name,
        slug=m.slug,
        key=m.key or "",
        description=m.description,
        objective=m.objective,
        success_metrics=dict(m.success_metrics) if m.success_metrics else None,
        target_date=m.target_date,
        github_url=m.github_url,
        context=m.context,
        settings=dict(m.settings) if m.settings else default_project_settings(),
        status=ProjectStatus(m.status) if m.status else ProjectStatus.SETUP,
        next_task_seq=m.next_task_seq if m.next_task_seq is not None else 1,
        created_by_user_id=m.created_by_user_id,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def label_to_entity(m: LabelModel) -> Label:
    return Label(
        id=m.id,
        workspace_id=m.workspace_id,
        name=m.name,
        color=m.color or "",
        created_at=m.created_at,
    )


def role_to_entity(m: RoleModel) -> Role:
    return Role(
        id=m.id,
        project_id=m.project_id,
        key=m.key,
        title=m.title,
        seats=m.seats,
        is_leader=m.is_leader,
        description=m.description or "",
        responsibilities=m.responsibilities or "",
        skill_ids=[str(x) for x in (m.skill_ids or [])],
        created_at=m.created_at,
    )


def seat_grant_to_entity(m: SeatGrantModel) -> SeatGrant:
    return SeatGrant(
        id=m.id,
        project_id=m.project_id,
        role_key=m.role_key,
        marius_id=m.marius_id,
        status=SeatGrantStatus(m.status),
        granted_at=m.granted_at,
        created_at=m.created_at,
    )


def marius_to_entity(m: MariusModel) -> Marius:
    return Marius(
        id=m.id,
        workspace_id=m.workspace_id,
        name=m.name,
        role=m.role,
        skills=list(m.skills or []),
        skill_ids=[str(x) for x in (m.skill_ids or [])],
        adapter_type=m.adapter_type,
        adapter_config=dict(m.adapter_config or {}),
        owner_user_id=m.owner_user_id,
        agent_token=m.agent_token,
        invite_status=InviteStatus(m.invite_status) if m.invite_status else InviteStatus.INVITED,
        enrollment_code=m.enrollment_code,
        approved_at=m.approved_at,
        liveness=Liveness(m.liveness),
        last_seen_at=m.last_seen_at,
        probe_attempts=m.probe_attempts or 0,
        backoff_step=m.backoff_step or 0,
        next_probe_at=m.next_probe_at,
        offline_since=m.offline_since,
        turn_started_at=m.turn_started_at,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def _task_priority(value: str | None) -> TaskPriority:
    try:
        return TaskPriority(value)
    except ValueError:
        return TaskPriority.MEDIUM


def task_to_entity(m: TaskModel) -> Task:
    return Task(
        id=m.id,
        project_id=m.project_id,
        identifier=m.identifier,
        title=m.title,
        description=m.description,
        status=TaskStatus(m.status),
        status_reason=m.status_reason,
        priority=_task_priority(m.priority),
        due_date=m.due_date,
        definition_of_done=m.definition_of_done,
        assigned_marius_id=m.assigned_marius_id,
        created_by_user_id=m.created_by_user_id,
        created_by_marius_id=m.created_by_marius_id,
        next_action=m.next_action,
        in_progress_at=m.in_progress_at,
        completed_at=m.completed_at,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def task_dependency_to_entity(m: TaskDependencyModel) -> TaskDependency:
    return TaskDependency(
        id=m.id,
        task_id=m.task_id,
        blocks_task_id=m.blocks_task_id,
    )


def comment_to_entity(m: CommentModel) -> Comment:
    return Comment(
        id=m.id,
        task_id=m.task_id,
        author_kind=AuthorKind(m.author_kind),
        author_marius_id=m.author_marius_id,
        author_user_id=m.author_user_id,
        body=m.body,
        mentions=[UUID(x) for x in (m.mentions or [])],
        created_at=m.created_at,
    )


def commission_to_entity(m: CommissionModel) -> CommissionSession:
    return CommissionSession(
        id=m.id,
        project_id=m.project_id,
        leader_marius_id=m.leader_marius_id,
        task_id=m.task_id,
        session_params=dict(m.session_params or {}),
        transcript=list(m.transcript or []),
        status=CommissionStatus(m.status),
        leader_state=LeaderState(m.leader_state),
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def leader_chat_to_entity(
    m: ProjectLeaderConversationModel,
) -> ProjectLeaderConversation:
    return ProjectLeaderConversation(
        id=m.id,
        project_id=m.project_id,
        leader_marius_id=m.leader_marius_id,
        session_params=dict(m.session_params or {}),
        transcript=list(m.transcript or []),
        state=ChatState(m.state),
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def onboarding_to_entity(m: OnboardingSessionModel) -> OnboardingSession:
    return OnboardingSession(
        id=m.id,
        workspace_id=m.workspace_id,
        status=OnboardingStatus(m.status),
        transcript=list(m.transcript or []),
        collected=dict(m.collected or {}),
        created_project_id=m.created_project_id,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def session_to_entity(m: SessionModel) -> AgentTaskSession:
    return AgentTaskSession(
        id=m.id,
        project_id=m.project_id,
        marius_id=m.marius_id,
        adapter_type=m.adapter_type,
        task_id=m.task_id,
        session_params_json=dict(m.session_params_json or {}),
        session_display_id=m.session_display_id,
        last_run_id=m.last_run_id,
        last_error=m.last_error,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def run_to_entity(m: RunModel) -> Run:
    return Run(
        id=m.id,
        project_id=m.project_id,
        marius_id=m.marius_id,
        task_id=m.task_id,
        adapter_type=m.adapter_type,
        wake_source=WakeSource(m.wake_source),
        trigger_detail=m.trigger_detail,
        status=RunStatus(m.status),
        external_run_id=m.external_run_id,
        session_id_before=m.session_id_before,
        session_id_after=m.session_id_after,
        usage_json=dict(m.usage_json or {}),
        error=m.error,
        next_action=m.next_action,
        continuation_attempt=m.continuation_attempt,
        started_at=m.started_at,
        finished_at=m.finished_at,
        last_output_at=m.last_output_at,
        created_at=m.created_at,
    )


def run_event_to_entity(m: RunEventModel) -> RunEvent:
    return RunEvent(
        id=m.id,
        run_id=m.run_id,
        seq=m.seq,
        type=m.type,
        payload=dict(m.payload or {}),
        created_at=m.created_at,
    )


def artifact_to_entity(m: ArtifactModel) -> Artifact:
    return Artifact(
        id=m.id,
        project_id=m.project_id,
        task_id=m.task_id,
        marius_id=m.marius_id,
        name=m.name,
        kind=m.kind,
        uri=m.uri,
        content_sha256=m.content_sha256,
        size_bytes=m.size_bytes,
        created_at=m.created_at,
    )


def wakeup_to_entity(m: WakeupModel) -> WakeupRequest:
    return WakeupRequest(
        id=m.id,
        project_id=m.project_id,
        marius_id=m.marius_id,
        task_id=m.task_id,
        source=WakeSource(m.source),
        reason=m.reason,
        prompt=m.prompt,
        status=WakeupStatus(m.status),
        run_id=m.run_id,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def skill_to_entity(m: SkillModel) -> Skill:
    return Skill(
        id=m.id,
        workspace_id=m.workspace_id,
        slug=m.slug,
        name=m.name,
        description=m.description or "",
        source=m.source,
        source_url=m.source_url or "",
        files=dict(m.files or {}),
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def user_to_entity(m: UserModel) -> User:
    return User(
        id=m.id,
        email=m.email,
        username=m.username,
        full_name=m.full_name,
        hashed_password=m.hashed_password,
        role=UserRole(m.role),
        is_active=m.is_active,
        is_verified=m.is_verified,
        created_at=m.created_at,
        updated_at=m.updated_at,
        last_login_at=m.last_login_at,
    )
