"""SQLAlchemy implementations of the domain repository ports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import CursorResult, case, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from armarius.domain.entities.approval import Approval
from armarius.domain.entities.artifact import Artifact
from armarius.domain.entities.auto_approval import AutoApproval
from armarius.domain.entities.checklist_item import ChecklistItem, ChecklistTally
from armarius.domain.entities.comment import Comment
from armarius.domain.entities.inbox_item import InboxItem, InboxItemStatus
from armarius.domain.entities.label import Label
from armarius.domain.entities.leader_chat import ProjectLeaderConversation
from armarius.domain.entities.marius import Marius
from armarius.domain.entities.onboarding import OnboardingSession
from armarius.domain.entities.orchestration_sweep import OrchestrationSweep
from armarius.domain.entities.plan import Plan
from armarius.domain.entities.project import ProjectStatus
from armarius.domain.entities.project_context import ContextApprovalStatus, ProjectContext
from armarius.domain.entities.push_reason import TaskPushReason
from armarius.domain.entities.role import Role
from armarius.domain.entities.run import ACTIVE_RUN_STATUSES, Run, RunEvent
from armarius.domain.entities.seat_grant import SeatGrant
from armarius.domain.entities.session import AgentTaskSession
from armarius.domain.entities.skill import Skill
from armarius.domain.entities.task import Task, TaskStatus
from armarius.domain.entities.task_dependency import TaskDependency
from armarius.domain.entities.task_log import TaskLogEntry
from armarius.domain.entities.user import User
from armarius.domain.entities.wakeup import (
    PENDING_WAKEUP_STATUSES,
    WakePairBusyError,
    WakeupRequest,
    WakeupStatus,
)
from armarius.domain.entities.workspace import Project, Workspace
from armarius.domain.repositories.repositories import (
    ApprovalRepository,
    ArtifactRepository,
    AutoApprovalRepository,
    ChecklistItemRepository,
    CommentRepository,
    InboxRepository,
    LabelRepository,
    LeaderChatRepository,
    MariusRepository,
    OnboardingRepository,
    OrchestrationSweepRepository,
    PlanRepository,
    ProjectContextRepository,
    ProjectRepository,
    RoleRepository,
    RunEventRepository,
    RunRepository,
    SeatGrantRepository,
    SessionRepository,
    SkillRepository,
    TaskDependencyRepository,
    TaskLogRepository,
    TaskPushReasonRepository,
    TaskRepository,
    UserRepository,
    WakeupRepository,
    WorkspaceRepository,
)
from armarius.domain.services.push_reason_rules import WATCHED_STATUSES
from armarius.domain.services.wake_reason import to_payload as causes_to_payload
from armarius.infrastructure.database.models import (
    ArtifactModel,
    ChecklistItemModel,
    CommentModel,
    InboxItemModel,
    LabelModel,
    MariusModel,
    OnboardingSessionModel,
    OrchestrationSweepModel,
    PlanItemModel,
    PlanModel,
    ProjectAutoApprovalModel,
    ProjectContextModel,
    ProjectLeaderConversationModel,
    ProjectModel,
    RoleModel,
    RunEventModel,
    RunModel,
    SeatGrantModel,
    SessionModel,
    SkillModel,
    TaskApprovalModel,
    TaskDependencyModel,
    TaskLogModel,
    TaskModel,
    TaskPushReasonModel,
    UserModel,
    WakeupModel,
    WorkspaceModel,
)
from armarius.infrastructure.persistence import mappers
from armarius.shared.clock import utcnow
from armarius.shared.errors import NotFound


async def _purge_projects(session: AsyncSession, project_ids: Sequence[UUID]) -> None:
    """Delete a set of projects and every row they own, children first.

    One list, used by both the project delete and the workspace delete, because they are
    the same cascade and keeping two copies is how one of them falls behind. Which is
    exactly what happened: this cascade was written when a project owned tasks, comments,
    artifacts, roles and seats, and every table added afterwards — runs, wakes, sessions,
    the task log, the acceptance criteria, the signatures, the recovery ladder, the plan,
    the brief, the cadence record, the Leader conversation — was never added to it. On
    Postgres those foreign keys refuse the delete outright, so deleting any project an
    agent had ever run on failed with a 500; on SQLite it silently orphaned the rows.

    No ``ON DELETE CASCADE`` anywhere in the schema, so the order below IS the constraint
    graph: run events before runs, plan items before plans, everything hanging off a task
    before the task, everything hanging off a project before the project.
    """
    if not project_ids:
        return
    ids = list(project_ids)

    task_ids = (
        await session.execute(select(TaskModel.id).where(TaskModel.project_id.in_(ids)))
    ).scalars().all()
    run_ids = (
        await session.execute(select(RunModel.id).where(RunModel.project_id.in_(ids)))
    ).scalars().all()
    plan_ids = (
        await session.execute(select(PlanModel.id).where(PlanModel.project_id.in_(ids)))
    ).scalars().all()

    if run_ids:
        await session.execute(delete(RunEventModel).where(RunEventModel.run_id.in_(run_ids)))
    if task_ids:
        for owned_by_task in (
            ArtifactModel,
            CommentModel,
            ChecklistItemModel,
            TaskApprovalModel,
            TaskLogModel,
            TaskPushReasonModel,
        ):
            await session.execute(
                delete(owned_by_task).where(owned_by_task.task_id.in_(task_ids))
            )
        # Both ends of a dependency edge point at a task, and an edge is dropped when
        # either end goes — a project can be deleted while a sibling still points into it.
        await session.execute(
            delete(TaskDependencyModel).where(
                or_(
                    TaskDependencyModel.task_id.in_(task_ids),
                    TaskDependencyModel.blocks_task_id.in_(task_ids),
                )
            )
        )
    for keyed_on_project in (WakeupModel, SessionModel, RunModel):
        await session.execute(
            delete(keyed_on_project).where(keyed_on_project.project_id.in_(ids))
        )
    if task_ids:
        await session.execute(delete(TaskModel).where(TaskModel.id.in_(task_ids)))
    if plan_ids:
        await session.execute(delete(PlanItemModel).where(PlanItemModel.plan_id.in_(plan_ids)))
    for owned_by_project in (
        PlanModel,
        ProjectContextModel,
        ProjectAutoApprovalModel,
        OrchestrationSweepModel,
        ProjectLeaderConversationModel,
        SeatGrantModel,
        RoleModel,
        # The patron's inbox lives on the workspace, but an item that points at a deleted
        # project is a row on a screen that can no longer open.
        InboxItemModel,
    ):
        await session.execute(
            delete(owned_by_project).where(owned_by_project.project_id.in_(ids))
        )
    await session.execute(delete(ProjectModel).where(ProjectModel.id.in_(ids)))


class SqlWorkspaceRepository(WorkspaceRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, workspace: Workspace) -> Workspace:
        self._s.add(
            WorkspaceModel(
                id=workspace.id,
                name=workspace.name,
                slug=workspace.slug,
                owner_user_id=workspace.owner_user_id,
                workspace_agent_id=workspace.workspace_agent_id,
                created_at=workspace.created_at,
                updated_at=workspace.updated_at,
            )
        )
        await self._s.flush()
        return workspace

    async def get(self, workspace_id: UUID) -> Workspace | None:
        m = await self._s.get(WorkspaceModel, workspace_id)
        return mappers.workspace_to_entity(m) if m else None

    async def list(self) -> Sequence[Workspace]:
        rows = (await self._s.execute(select(WorkspaceModel))).scalars().all()
        return [mappers.workspace_to_entity(m) for m in rows]

    async def list_by_owner(self, owner_user_id: str) -> Sequence[Workspace]:
        rows = (
            await self._s.execute(
                select(WorkspaceModel).where(WorkspaceModel.owner_user_id == owner_user_id)
            )
        ).scalars().all()
        return [mappers.workspace_to_entity(m) for m in rows]

    async def update(self, workspace: Workspace) -> Workspace:
        m = await self._s.get(WorkspaceModel, workspace.id)
        if m is None:
            raise NotFound("workspace_not_found")
        m.name = workspace.name
        m.slug = workspace.slug
        m.workspace_agent_id = workspace.workspace_agent_id
        m.updated_at = workspace.updated_at
        await self._s.flush()
        return workspace

    async def remove(self, workspace_id: UUID) -> None:
        """Delete a workspace and every child it owns. FK columns carry no
        ``ON DELETE CASCADE``, so a bare delete orphans (SQLite) or errors (Postgres) —
        we cascade explicitly (projects + their roster/tasks, then mariuses/skills/labels)
        so the behaviour is identical on both backends.

        The runtime/history tables (runs, run_events, agent_task_sessions, wakeup_requests,
        onboarding_sessions, project_leader_conversations) reference workspace children by
        plain UUID with no FK either, so we clear them here too — otherwise deleting a
        workspace leaves them dangling forever (issue #28: cascade chosen over audit
        retention)."""
        project_ids = (
            await self._s.execute(
                select(ProjectModel.id).where(ProjectModel.workspace_id == workspace_id)
            )
        ).scalars().all()
        marius_ids = (
            await self._s.execute(
                select(MariusModel.id).where(MariusModel.workspace_id == workspace_id)
            )
        ).scalars().all()
        task_ids: Sequence[UUID] = []
        if project_ids:
            task_ids = (
                await self._s.execute(
                    select(TaskModel.id).where(TaskModel.project_id.in_(project_ids))
                )
            ).scalars().all()

        # Runtime/history rows key off marius/task/project by plain UUID. Gather the runs
        # first so their run_events (FK, no cascade) and wakeups can be cleared by run_id.
        if project_ids or marius_ids or task_ids:
            run_ids = (
                await self._s.execute(
                    select(RunModel.id).where(
                        or_(
                            RunModel.project_id.in_(project_ids),
                            RunModel.marius_id.in_(marius_ids),
                            RunModel.task_id.in_(task_ids),
                        )
                    )
                )
            ).scalars().all()
            if run_ids:
                await self._s.execute(
                    delete(RunEventModel).where(RunEventModel.run_id.in_(run_ids))
                )
                await self._s.execute(delete(RunModel).where(RunModel.id.in_(run_ids)))
            await self._s.execute(
                delete(SessionModel).where(
                    or_(
                        SessionModel.project_id.in_(project_ids),
                        SessionModel.marius_id.in_(marius_ids),
                        SessionModel.task_id.in_(task_ids),
                    )
                )
            )
            await self._s.execute(
                delete(WakeupModel).where(
                    or_(
                        WakeupModel.project_id.in_(project_ids),
                        WakeupModel.marius_id.in_(marius_ids),
                        WakeupModel.task_id.in_(task_ids),
                        WakeupModel.run_id.in_(run_ids),
                    )
                )
            )
            await self._s.execute(
                delete(ProjectLeaderConversationModel).where(
                    or_(
                        ProjectLeaderConversationModel.project_id.in_(project_ids),
                        ProjectLeaderConversationModel.leader_marius_id.in_(marius_ids),
                    )
                )
            )
        await self._s.execute(
            delete(OnboardingSessionModel).where(
                or_(
                    OnboardingSessionModel.workspace_id == workspace_id,
                    OnboardingSessionModel.created_project_id.in_(project_ids),
                )
            )
        )

        await _purge_projects(self._s, project_ids)
        await self._s.execute(delete(LabelModel).where(LabelModel.workspace_id == workspace_id))
        await self._s.execute(
            delete(MariusModel).where(MariusModel.workspace_id == workspace_id)
        )
        await self._s.execute(delete(SkillModel).where(SkillModel.workspace_id == workspace_id))
        m = await self._s.get(WorkspaceModel, workspace_id)
        if m is not None:
            await self._s.delete(m)
        await self._s.flush()


class SqlLabelRepository(LabelRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, label: Label) -> Label:
        self._s.add(
            LabelModel(
                id=label.id,
                workspace_id=label.workspace_id,
                name=label.name,
                color=label.color,
                created_at=label.created_at,
            )
        )
        await self._s.flush()
        return label

    async def list_by_workspace(self, workspace_id: UUID) -> Sequence[Label]:
        rows = (
            await self._s.execute(
                select(LabelModel)
                .where(LabelModel.workspace_id == workspace_id)
                .order_by(LabelModel.created_at)
            )
        ).scalars().all()
        return [mappers.label_to_entity(m) for m in rows]


class SqlLeaderChatRepository(LeaderChatRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(
        self, conversation: ProjectLeaderConversation
    ) -> ProjectLeaderConversation:
        self._s.add(
            ProjectLeaderConversationModel(
                id=conversation.id,
                project_id=conversation.project_id,
                leader_marius_id=conversation.leader_marius_id,
                session_params=dict(conversation.session_params),
                transcript=list(conversation.transcript),
                state=str(conversation.state),
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
            )
        )
        await self._s.flush()
        return conversation

    async def get(
        self, conversation_id: UUID
    ) -> ProjectLeaderConversation | None:
        m = await self._s.get(ProjectLeaderConversationModel, conversation_id)
        return mappers.leader_chat_to_entity(m) if m else None

    async def get_by_project(
        self, project_id: UUID
    ) -> ProjectLeaderConversation | None:
        m = (
            await self._s.execute(
                select(ProjectLeaderConversationModel).where(
                    ProjectLeaderConversationModel.project_id == project_id
                )
            )
        ).scalar_one_or_none()
        return mappers.leader_chat_to_entity(m) if m else None

    async def update(
        self, conversation: ProjectLeaderConversation
    ) -> ProjectLeaderConversation:
        m = await self._s.get(ProjectLeaderConversationModel, conversation.id)
        if m is None:
            raise LookupError("leader chat conversation not found")
        m.leader_marius_id = conversation.leader_marius_id
        m.session_params = dict(conversation.session_params)
        m.transcript = list(conversation.transcript)
        m.state = str(conversation.state)
        m.updated_at = conversation.updated_at
        await self._s.flush()
        return conversation


class SqlOnboardingRepository(OnboardingRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, session: OnboardingSession) -> OnboardingSession:
        self._s.add(
            OnboardingSessionModel(
                id=session.id,
                workspace_id=session.workspace_id,
                status=str(session.status),
                transcript=list(session.transcript),
                collected=dict(session.collected),
                created_project_id=session.created_project_id,
                created_at=session.created_at,
                updated_at=session.updated_at,
            )
        )
        await self._s.flush()
        return session

    async def get(self, session_id: UUID) -> OnboardingSession | None:
        m = await self._s.get(OnboardingSessionModel, session_id)
        return mappers.onboarding_to_entity(m) if m else None

    async def update(self, session: OnboardingSession) -> OnboardingSession:
        m = await self._s.get(OnboardingSessionModel, session.id)
        if m is None:
            raise NotFound("onboarding_session_not_found")
        m.status = str(session.status)
        m.transcript = list(session.transcript)
        m.collected = dict(session.collected)
        m.created_project_id = session.created_project_id
        m.updated_at = session.updated_at
        await self._s.flush()
        return session

    async def list_by_workspace(
        self, workspace_id: UUID
    ) -> Sequence[OnboardingSession]:
        rows = (
            await self._s.execute(
                select(OnboardingSessionModel)
                .where(OnboardingSessionModel.workspace_id == workspace_id)
                .order_by(OnboardingSessionModel.created_at.desc())
            )
        ).scalars().all()
        return [mappers.onboarding_to_entity(m) for m in rows]


class SqlProjectRepository(ProjectRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, project: Project) -> Project:
        self._s.add(
            ProjectModel(
                id=project.id,
                workspace_id=project.workspace_id,
                name=project.name,
                slug=project.slug,
                key=project.key,
                description=project.description,
                status=str(project.status),
                next_task_seq=project.next_task_seq,
                objective=project.objective,
                success_metrics=project.success_metrics,
                target_date=project.target_date,
                github_url=project.github_url,
                context=project.context,
                settings=dict(project.settings) if project.settings else None,
                created_by_user_id=project.created_by_user_id,
                created_at=project.created_at,
                updated_at=project.updated_at,
            )
        )
        await self._s.flush()
        return project

    async def get(self, project_id: UUID) -> Project | None:
        m = await self._s.get(ProjectModel, project_id)
        return mappers.project_to_entity(m) if m else None

    async def list_by_workspace(self, workspace_id: UUID) -> Sequence[Project]:
        rows = (
            await self._s.execute(
                select(ProjectModel).where(ProjectModel.workspace_id == workspace_id)
            )
        ).scalars().all()
        return [mappers.project_to_entity(m) for m in rows]

    async def get_by_key(self, workspace_id: UUID, key: str) -> Project | None:
        m = (
            await self._s.execute(
                select(ProjectModel).where(
                    ProjectModel.workspace_id == workspace_id,
                    ProjectModel.key == key,
                )
            )
        ).scalar_one_or_none()
        return mappers.project_to_entity(m) if m else None

    async def allocate_task_number(self, project_id: UUID) -> int:
        """Atomically bump + return the next per-project task number.

        One ``UPDATE … RETURNING`` (row-level lock inside the statement) so concurrent
        creates can never share a number — the core guarantee max+1 could not give.
        """
        stmt = (
            update(ProjectModel)
            .where(ProjectModel.id == project_id)
            .values(next_task_seq=ProjectModel.next_task_seq + 1)
            .returning(ProjectModel.next_task_seq)
        )
        value = (await self._s.execute(stmt)).scalar_one_or_none()
        if value is None:
            raise NotFound("project_not_found")
        # `next_task_seq` is the NEXT number to assign (starts at 1); the UPDATE advanced
        # it, so the number we just claimed is the pre-increment value.
        return int(value) - 1

    async def update(self, project: Project) -> Project:
        m = await self._s.get(ProjectModel, project.id)
        if m is None:
            raise NotFound("project_not_found")
        m.name = project.name
        m.slug = project.slug
        m.key = project.key
        m.description = project.description
        m.status = str(project.status)
        m.next_task_seq = project.next_task_seq
        m.objective = project.objective
        m.success_metrics = project.success_metrics
        m.target_date = project.target_date
        m.github_url = project.github_url
        m.context = project.context
        m.settings = dict(project.settings) if project.settings else None
        m.updated_at = project.updated_at
        await self._s.flush()
        return project

    async def remove(self, project_id: UUID) -> None:
        """Delete a project and every row it owns — see `_purge_projects` for the order
        and for why the list is shared with the workspace delete."""
        await _purge_projects(self._s, [project_id])
        await self._s.flush()


class SqlRoleRepository(RoleRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, role: Role) -> Role:
        self._s.add(
            RoleModel(
                id=role.id,
                project_id=role.project_id,
                key=role.key,
                title=role.title,
                seats=role.seats,
                is_leader=role.is_leader,
                description=role.description,
                skill_ids=[str(x) for x in role.skill_ids],
                created_at=role.created_at,
            )
        )
        await self._s.flush()
        return role

    async def get(self, role_id: UUID) -> Role | None:
        m = await self._s.get(RoleModel, role_id)
        return mappers.role_to_entity(m) if m else None

    async def list_by_project(self, project_id: UUID) -> Sequence[Role]:
        rows = (
            await self._s.execute(
                select(RoleModel)
                .where(RoleModel.project_id == project_id)
                .order_by(RoleModel.created_at)
            )
        ).scalars().all()
        return [mappers.role_to_entity(m) for m in rows]

    async def update(self, role: Role) -> Role:
        m = await self._s.get(RoleModel, role.id)
        if m is None:
            raise NotFound("role_not_found")
        m.key = role.key
        m.title = role.title
        m.seats = role.seats
        m.is_leader = role.is_leader
        m.description = role.description
        m.skill_ids = [str(x) for x in role.skill_ids]
        await self._s.flush()
        return role

    async def remove(self, role_id: UUID) -> None:
        m = await self._s.get(RoleModel, role_id)
        if m is not None:
            await self._s.delete(m)
            await self._s.flush()


class SqlSeatGrantRepository(SeatGrantRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, grant: SeatGrant) -> SeatGrant:
        self._s.add(
            SeatGrantModel(
                id=grant.id,
                project_id=grant.project_id,
                role_key=grant.role_key,
                marius_id=grant.marius_id,
                status=str(grant.status),
                granted_by_user_id=grant.granted_by_user_id,
                granted_at=grant.granted_at,
                created_at=grant.created_at,
            )
        )
        await self._s.flush()
        return grant

    async def get(self, grant_id: UUID) -> SeatGrant | None:
        m = await self._s.get(SeatGrantModel, grant_id)
        return mappers.seat_grant_to_entity(m) if m else None

    async def list_by_project(self, project_id: UUID) -> Sequence[SeatGrant]:
        rows = (
            await self._s.execute(
                select(SeatGrantModel)
                .where(SeatGrantModel.project_id == project_id)
                .order_by(SeatGrantModel.created_at)
            )
        ).scalars().all()
        return [mappers.seat_grant_to_entity(m) for m in rows]

    async def update(self, grant: SeatGrant) -> SeatGrant:
        m = await self._s.get(SeatGrantModel, grant.id)
        if m is None:
            raise NotFound("seat_grant_not_found")
        m.role_key = grant.role_key
        m.marius_id = grant.marius_id
        m.status = str(grant.status)
        m.granted_by_user_id = grant.granted_by_user_id
        m.granted_at = grant.granted_at
        await self._s.flush()
        return grant


class SqlApprovalRepository(ApprovalRepository):
    """Signatures. No delete, and the one update is a flag flip that retires a signature
    without touching a word of it — a signature whose *content* can be edited afterwards
    is not evidence of anything (FR-039)."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, approval: Approval) -> Approval:
        self._s.add(
            TaskApprovalModel(
                id=approval.id,
                task_id=approval.task_id,
                superseded=approval.superseded,
                signer_kind=str(approval.signer_kind),
                signer_marius_id=approval.signer_marius_id,
                signer_user_id=approval.signer_user_id,
                result=str(approval.result),
                reason=approval.reason,
                is_auto=approval.is_auto,
                signed_at=approval.signed_at,
            )
        )
        await self._s.flush()
        return approval

    async def list_for_task(self, task_id: UUID) -> Sequence[Approval]:
        rows = (
            await self._s.execute(
                select(TaskApprovalModel)
                .where(TaskApprovalModel.task_id == task_id)
                .order_by(TaskApprovalModel.signed_at)
            )
        ).scalars().all()
        return [mappers.approval_to_entity(m) for m in rows]

    async def list_for_tasks(self, task_ids: Sequence[UUID]) -> Sequence[Approval]:
        if not task_ids:
            return []
        rows = (
            await self._s.execute(
                select(TaskApprovalModel)
                .where(TaskApprovalModel.task_id.in_(list(task_ids)))
                .order_by(TaskApprovalModel.signed_at)
            )
        ).scalars().all()
        return [mappers.approval_to_entity(m) for m in rows]

    async def supersede_for_task(self, task_id: UUID) -> int:
        result = cast(
            CursorResult[Any],
            await self._s.execute(
                update(TaskApprovalModel)
                .where(
                    TaskApprovalModel.task_id == task_id,
                    TaskApprovalModel.superseded.is_(False),
                )
                .values(superseded=True)
            ),
        )
        await self._s.flush()
        return int(result.rowcount or 0)


class SqlAutoApprovalRepository(AutoApprovalRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get(self, project_id: UUID, user_id: str) -> AutoApproval | None:
        m = (
            await self._s.execute(
                select(ProjectAutoApprovalModel).where(
                    ProjectAutoApprovalModel.project_id == project_id,
                    ProjectAutoApprovalModel.user_id == user_id,
                )
            )
        ).scalars().first()
        return mappers.auto_approval_to_entity(m) if m else None

    async def set_enabled(
        self, project_id: UUID, user_id: str, *, enabled: bool
    ) -> AutoApproval:
        now = utcnow()
        m = (
            await self._s.execute(
                select(ProjectAutoApprovalModel).where(
                    ProjectAutoApprovalModel.project_id == project_id,
                    ProjectAutoApprovalModel.user_id == user_id,
                )
            )
        ).scalars().first()
        if m is None:
            m = ProjectAutoApprovalModel(
                id=uuid4(),
                project_id=project_id,
                user_id=user_id,
                enabled=enabled,
                created_at=now,
                updated_at=now,
            )
            self._s.add(m)
        else:
            m.enabled = enabled
            m.updated_at = now
        await self._s.flush()
        return mappers.auto_approval_to_entity(m)


class SqlMariusRepository(MariusRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, marius: Marius) -> Marius:
        self._s.add(
            MariusModel(
                id=marius.id,
                workspace_id=marius.workspace_id,
                name=marius.name,
                role=marius.role,
                skills=list(marius.skills),
                adapter_type=marius.adapter_type,
                adapter_config=dict(marius.adapter_config),
                skill_ids=[str(x) for x in marius.skill_ids],
                skill_installs=dict(marius.skill_installs),
                owner_user_id=marius.owner_user_id,
                agent_token=marius.agent_token,
                invite_status=str(marius.invite_status),
                approved_at=marius.approved_at,
                liveness=str(marius.liveness),
                last_seen_at=marius.last_seen_at,
                probe_attempts=marius.probe_attempts,
                backoff_step=marius.backoff_step,
                next_probe_at=marius.next_probe_at,
                offline_since=marius.offline_since,
                turn_started_at=marius.turn_started_at,
                created_at=marius.created_at,
                updated_at=marius.updated_at,
            )
        )
        await self._s.flush()
        return marius

    async def get(self, marius_id: UUID) -> Marius | None:
        m = await self._s.get(MariusModel, marius_id)
        return mappers.marius_to_entity(m) if m else None

    async def get_by_token(self, token: str) -> Marius | None:
        m = (
            await self._s.execute(select(MariusModel).where(MariusModel.agent_token == token))
        ).scalar_one_or_none()
        return mappers.marius_to_entity(m) if m else None

    async def list_by_workspace(self, workspace_id: UUID) -> Sequence[Marius]:
        rows = (
            await self._s.execute(
                select(MariusModel).where(MariusModel.workspace_id == workspace_id)
            )
        ).scalars().all()
        return [mappers.marius_to_entity(m) for m in rows]

    async def list_by_ids(self, marius_ids: list[UUID]) -> Sequence[Marius]:
        if not marius_ids:
            return []
        rows = (
            await self._s.execute(
                select(MariusModel).where(MariusModel.id.in_(marius_ids))
            )
        ).scalars().all()
        return [mappers.marius_to_entity(m) for m in rows]

    async def update(self, marius: Marius) -> Marius:
        m = await self._s.get(MariusModel, marius.id)
        if m is None:
            raise NotFound("agent_not_found")
        m.name = marius.name
        m.role = marius.role
        m.skills = list(marius.skills)
        m.skill_ids = [str(x) for x in marius.skill_ids]
        m.skill_installs = dict(marius.skill_installs)
        m.adapter_type = marius.adapter_type
        m.adapter_config = dict(marius.adapter_config)
        m.owner_user_id = marius.owner_user_id
        m.agent_token = marius.agent_token
        m.invite_status = str(marius.invite_status)
        m.approved_at = marius.approved_at
        m.liveness = str(marius.liveness)
        m.last_seen_at = marius.last_seen_at
        m.probe_attempts = marius.probe_attempts
        m.backoff_step = marius.backoff_step
        m.next_probe_at = marius.next_probe_at
        m.offline_since = marius.offline_since
        m.turn_started_at = marius.turn_started_at
        m.updated_at = marius.updated_at
        await self._s.flush()
        return marius

    async def remove(self, marius_id: UUID) -> None:
        """Delete a Marius and vacate any roster seats it held (seat grants carry a plain
        UUID ref, so we clear them explicitly rather than orphaning a filled seat).

        Also clears the runtime/history rows that reference this Marius by plain UUID
        (its runs + their run_events, agent_task_sessions, wakeup_requests, and any
        leader chat it led) so a delete doesn't leave them dangling (issue #28)."""
        run_ids = (
            await self._s.execute(
                select(RunModel.id).where(RunModel.marius_id == marius_id)
            )
        ).scalars().all()
        if run_ids:
            await self._s.execute(
                delete(RunEventModel).where(RunEventModel.run_id.in_(run_ids))
            )
            await self._s.execute(delete(RunModel).where(RunModel.id.in_(run_ids)))
        await self._s.execute(
            delete(SessionModel).where(SessionModel.marius_id == marius_id)
        )
        await self._s.execute(
            delete(WakeupModel).where(
                or_(WakeupModel.marius_id == marius_id, WakeupModel.run_id.in_(run_ids))
            )
        )
        await self._s.execute(
            delete(SeatGrantModel).where(SeatGrantModel.marius_id == marius_id)
        )
        m = await self._s.get(MariusModel, marius_id)
        if m is not None:
            await self._s.delete(m)
        await self._s.flush()


# The statuses the safety net watches, as stored strings. Mirrors
# `push_reason_rules.WATCHED_STATUSES` — the rule owns the meaning, this is the shape
# the query needs, and the parity is asserted in tests rather than hoped for.
_WATCHED_STATUS_VALUES: list[str] = sorted(str(s) for s in WATCHED_STATUSES)


def _not_in_a_closed_project() -> ColumnElement[bool]:
    """The FR-005 half of both safety-net scans: a closed project is history.

    Written as NOT EXISTS rather than `project_id NOT IN (closed ids)` on purpose. The
    `IN` form compares against an empty cell as *unknown* rather than *true*, so the day
    `tasks.project_id` stops being mandatory, every task without a project would drop
    silently out of the net — and a task with no project is exactly the kind nobody is
    coming back for. NOT EXISTS keeps those rows.

    It costs the one join the scan otherwise avoids. Worth it: the alternative is the
    recovery ladder waking workers about a project the patron has declared finished, and
    `change_phase` already promises in writing that nothing wakes for a closed project.
    """
    return ~(
        select(ProjectModel.id)
        .where(ProjectModel.id == TaskModel.project_id)
        .where(ProjectModel.status == str(ProjectStatus.CLOSED))
        .exists()
    )


class SqlTaskRepository(TaskRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, task: Task) -> Task:
        self._s.add(
            TaskModel(
                id=task.id,
                project_id=task.project_id,
                identifier=task.identifier,
                title=task.title,
                description=task.description,
                status=str(task.status),
                status_reason=task.status_reason,
                priority=str(task.priority),
                due_date=task.due_date,
                definition_of_done=task.definition_of_done,
                plan_item_id=task.plan_item_id,
                drive=str(task.drive) if task.drive else None,
                drive_expires_at=task.drive_expires_at,
                stalled=task.stalled,
                stalled_reason=task.stalled_reason,
                assigned_marius_id=task.assigned_marius_id,
                created_by_user_id=task.created_by_user_id,
                created_by_marius_id=task.created_by_marius_id,
                next_action=task.next_action,
                in_progress_at=task.in_progress_at,
                completed_at=task.completed_at,
                created_at=task.created_at,
                updated_at=task.updated_at,
            )
        )
        await self._s.flush()
        return task

    async def get(self, task_id: UUID) -> Task | None:
        m = await self._s.get(TaskModel, task_id)
        return mappers.task_to_entity(m) if m else None

    async def list_by_project(
        self, project_id: UUID, *, statuses: list[str] | None = None
    ) -> Sequence[Task]:
        stmt = select(TaskModel).where(TaskModel.project_id == project_id)
        if statuses:
            stmt = stmt.where(TaskModel.status.in_(statuses))
        stmt = stmt.order_by(TaskModel.created_at)
        rows = (await self._s.execute(stmt)).scalars().all()
        return [mappers.task_to_entity(m) for m in rows]

    async def update(self, task: Task) -> Task:
        m = await self._s.get(TaskModel, task.id)
        if m is None:
            raise NotFound("task_not_found")
        m.identifier = task.identifier
        m.title = task.title
        m.description = task.description
        m.status = str(task.status)
        m.status_reason = task.status_reason
        m.priority = str(task.priority)
        m.due_date = task.due_date
        m.definition_of_done = task.definition_of_done
        m.plan_item_id = task.plan_item_id
        m.drive = str(task.drive) if task.drive else None
        m.drive_expires_at = task.drive_expires_at
        m.stalled = task.stalled
        m.stalled_reason = task.stalled_reason
        m.assigned_marius_id = task.assigned_marius_id
        m.next_action = task.next_action
        m.in_progress_at = task.in_progress_at
        m.completed_at = task.completed_at
        m.updated_at = task.updated_at
        await self._s.flush()
        return task

    async def list_stall_candidates(
        self, now: datetime, *, limit: int = 500
    ) -> Sequence[Task]:
        stmt = (
            select(TaskModel)
            .where(TaskModel.status.in_(_WATCHED_STATUS_VALUES))
            .where(_not_in_a_closed_project())
            .where(
                or_(
                    TaskModel.drive.is_(None),
                    TaskModel.drive_expires_at <= now,
                    TaskModel.stalled.is_(True),
                )
            )
            # Oldest first: on a service that comes up behind a backlog of dropped tasks,
            # the ones that have been dropped longest are the ones nobody has been told
            # about for longest.
            .order_by(TaskModel.updated_at)
            .limit(limit)
        )
        rows = (await self._s.execute(stmt)).scalars().all()
        return [mappers.task_to_entity(m) for m in rows]

    async def list_open(self, *, limit: int = 1000) -> Sequence[Task]:
        stmt = (
            select(TaskModel)
            .where(TaskModel.status.in_(_WATCHED_STATUS_VALUES))
            .where(_not_in_a_closed_project())
            .order_by(TaskModel.updated_at)
            .limit(limit)
        )
        rows = (await self._s.execute(stmt)).scalars().all()
        return [mappers.task_to_entity(m) for m in rows]


class SqlTaskPushReasonRepository(TaskPushReasonRepository):
    """The recovery ladder, one row per task (spec 001 §9)."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_for_task(self, task_id: UUID) -> TaskPushReason | None:
        stmt = select(TaskPushReasonModel).where(TaskPushReasonModel.task_id == task_id)
        m = (await self._s.execute(stmt)).scalars().first()
        return mappers.push_reason_to_entity(m) if m else None

    async def upsert(self, reason: TaskPushReason) -> TaskPushReason:
        stmt = select(TaskPushReasonModel).where(
            TaskPushReasonModel.task_id == reason.task_id
        )
        m = (await self._s.execute(stmt)).scalars().first()
        if m is None:
            self._s.add(
                TaskPushReasonModel(
                    id=reason.id,
                    task_id=reason.task_id,
                    ref=reason.ref,
                    level=int(reason.level),
                    attempts=reason.attempts,
                    handover_attempts=reason.handover_attempts,
                    leader_reached_at=reason.leader_reached_at,
                    cause=reason.cause,
                    last_attempt_at=reason.last_attempt_at,
                    next_retry_at=reason.next_retry_at,
                    created_at=reason.created_at,
                    updated_at=reason.updated_at,
                )
            )
        else:
            # The row's identity is the task, not the id the caller happened to carry —
            # keep the stored id so a caller that built a fresh entity does not silently
            # renumber a ladder that other rows may already reference.
            reason.id = m.id
            m.ref = reason.ref
            m.level = int(reason.level)
            m.attempts = reason.attempts
            m.handover_attempts = reason.handover_attempts
            m.leader_reached_at = reason.leader_reached_at
            m.cause = reason.cause
            m.last_attempt_at = reason.last_attempt_at
            m.next_retry_at = reason.next_retry_at
            m.updated_at = reason.updated_at
        await self._s.flush()
        return reason

    async def clear_for_task(self, task_id: UUID) -> None:
        await self._s.execute(
            delete(TaskPushReasonModel).where(TaskPushReasonModel.task_id == task_id)
        )
        await self._s.flush()

    async def list_for_tasks(self, task_ids: Sequence[UUID]) -> Sequence[TaskPushReason]:
        if not task_ids:
            return []
        stmt = select(TaskPushReasonModel).where(
            TaskPushReasonModel.task_id.in_(list(task_ids))
        )
        rows = (await self._s.execute(stmt)).scalars().all()
        return [mappers.push_reason_to_entity(m) for m in rows]


class SqlChecklistItemRepository(ChecklistItemRepository):
    """Acceptance criteria, stored and replaced as one list (spec 001 §7)."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def list_by_task(self, task_id: UUID) -> Sequence[ChecklistItem]:
        rows = (
            await self._s.execute(
                select(ChecklistItemModel)
                .where(ChecklistItemModel.task_id == task_id)
                .order_by(ChecklistItemModel.order_index)
            )
        ).scalars().all()
        return [mappers.checklist_item_to_entity(m) for m in rows]

    async def count_by_project(
        self, project_id: UUID
    ) -> Mapping[UUID, ChecklistTally]:
        """One grouped query for the whole board. Per-task counting would put a fan-out
        on the one call a board makes on every push, which is the shape that turns a fix
        for a frozen screen into a load problem."""
        passed = case((ChecklistItemModel.result == "passed", 1), else_=0)
        rows = await self._s.execute(
            select(
                ChecklistItemModel.task_id,
                func.count(),
                func.coalesce(func.sum(passed), 0),
            )
            .join(TaskModel, TaskModel.id == ChecklistItemModel.task_id)
            .where(TaskModel.project_id == project_id)
            .group_by(ChecklistItemModel.task_id)
        )
        return {
            task_id: ChecklistTally(total=int(total), passed=int(scored))
            for task_id, total, scored in rows.all()
        }

    async def replace_for_task(
        self, task_id: UUID, items: Sequence[ChecklistItem]
    ) -> Sequence[ChecklistItem]:
        """Swap the whole yardstick in one transaction — never half of one."""
        await self._s.execute(
            delete(ChecklistItemModel).where(ChecklistItemModel.task_id == task_id)
        )
        await self._s.flush()
        for item in items:
            item.task_id = task_id
            self._s.add(
                ChecklistItemModel(
                    id=item.id,
                    task_id=task_id,
                    text=item.text,
                    done=item.done,
                    order_index=item.order,
                    result=str(item.result),
                    evidence_artifact_id=item.evidence_artifact_id,
                )
            )
        await self._s.flush()
        return list(items)

    async def update(self, item: ChecklistItem) -> ChecklistItem:
        m = await self._s.get(ChecklistItemModel, item.id)
        if m is None:
            return item
        m.text = item.text
        m.done = item.done
        m.order_index = item.order
        m.result = str(item.result)
        m.evidence_artifact_id = item.evidence_artifact_id
        await self._s.flush()
        return item


class SqlTaskDependencyRepository(TaskDependencyRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, dependency: TaskDependency) -> TaskDependency:
        self._s.add(
            TaskDependencyModel(
                id=dependency.id,
                task_id=dependency.task_id,
                blocks_task_id=dependency.blocks_task_id,
            )
        )
        await self._s.flush()
        return dependency

    async def remove(self, task_id: UUID, blocks_task_id: UUID) -> None:
        await self._s.execute(
            delete(TaskDependencyModel).where(
                TaskDependencyModel.task_id == task_id,
                TaskDependencyModel.blocks_task_id == blocks_task_id,
            )
        )
        await self._s.flush()

    async def get(
        self, task_id: UUID, blocks_task_id: UUID
    ) -> TaskDependency | None:
        m = (
            await self._s.execute(
                select(TaskDependencyModel).where(
                    TaskDependencyModel.task_id == task_id,
                    TaskDependencyModel.blocks_task_id == blocks_task_id,
                )
            )
        ).scalar_one_or_none()
        return mappers.task_dependency_to_entity(m) if m else None

    async def list_blockers(self, task_id: UUID) -> Sequence[TaskDependency]:
        rows = (
            await self._s.execute(
                select(TaskDependencyModel).where(
                    TaskDependencyModel.task_id == task_id
                )
            )
        ).scalars().all()
        return [mappers.task_dependency_to_entity(m) for m in rows]

    async def list_dependents(self, task_id: UUID) -> Sequence[TaskDependency]:
        rows = (
            await self._s.execute(
                select(TaskDependencyModel).where(
                    TaskDependencyModel.blocks_task_id == task_id
                )
            )
        ).scalars().all()
        return [mappers.task_dependency_to_entity(m) for m in rows]

    async def list_by_project(self, project_id: UUID) -> Sequence[TaskDependency]:
        rows = (
            await self._s.execute(
                select(TaskDependencyModel)
                .join(TaskModel, TaskModel.id == TaskDependencyModel.task_id)
                .where(TaskModel.project_id == project_id)
            )
        ).scalars().all()
        return [mappers.task_dependency_to_entity(m) for m in rows]

    async def list_unfinished_blockers(self, task_id: UUID) -> Sequence[Task]:
        rows = (
            await self._s.execute(
                select(TaskModel)
                .join(
                    TaskDependencyModel,
                    TaskDependencyModel.blocks_task_id == TaskModel.id,
                )
                .where(
                    TaskDependencyModel.task_id == task_id,
                    TaskModel.status != str(TaskStatus.DONE),
                )
                .order_by(TaskModel.identifier)
            )
        ).scalars().all()
        return [mappers.task_to_entity(m) for m in rows]

    async def all_blockers_done(self, task_id: UUID) -> bool:
        # Count blockers not yet done; 0 unfinished ⇒ gate satisfied (also when
        # the task has no blockers at all).
        unfinished = await self._s.execute(
            select(func.count())
            .select_from(TaskDependencyModel)
            .join(TaskModel, TaskModel.id == TaskDependencyModel.blocks_task_id)
            .where(
                TaskDependencyModel.task_id == task_id,
                TaskModel.status != str(TaskStatus.DONE),
            )
        )
        return int(unfinished.scalar_one()) == 0


class SqlCommentRepository(CommentRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, comment: Comment) -> Comment:
        self._s.add(
            CommentModel(
                id=comment.id,
                task_id=comment.task_id,
                author_kind=str(comment.author_kind),
                author_marius_id=comment.author_marius_id,
                author_user_id=comment.author_user_id,
                body=comment.body,
                mentions=[str(x) for x in comment.mentions],
                created_at=comment.created_at,
            )
        )
        await self._s.flush()
        return comment

    async def list_by_task(self, task_id: UUID) -> Sequence[Comment]:
        rows = (
            await self._s.execute(
                select(CommentModel)
                .where(CommentModel.task_id == task_id)
                .order_by(CommentModel.created_at)
            )
        ).scalars().all()
        return [mappers.comment_to_entity(m) for m in rows]

    async def count_by_project(self, project_id: UUID) -> Mapping[UUID, int]:
        """Comments per task across one project — the count a board card draws, without
        shipping the comment bodies to a screen that only renders a number."""
        rows = await self._s.execute(
            select(CommentModel.task_id, func.count())
            .join(TaskModel, TaskModel.id == CommentModel.task_id)
            .where(TaskModel.project_id == project_id)
            .group_by(CommentModel.task_id)
        )
        return {task_id: int(n) for task_id, n in rows.all()}

    async def list_since(self, task_id: UUID, after_seq: int) -> Sequence[Comment]:
        return await self.list_by_task(task_id)


class SqlSessionRepository(SessionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_for(
        self, marius_id: UUID, adapter_type: str, task_id: UUID
    ) -> AgentTaskSession | None:
        m = (
            await self._s.execute(
                select(SessionModel).where(
                    SessionModel.marius_id == marius_id,
                    SessionModel.adapter_type == adapter_type,
                    SessionModel.task_id == task_id,
                )
            )
        ).scalar_one_or_none()
        return mappers.session_to_entity(m) if m else None

    async def upsert(self, session: AgentTaskSession) -> AgentTaskSession:
        m = await self._s.get(SessionModel, session.id)
        if m is None:
            self._s.add(
                SessionModel(
                    id=session.id,
                    project_id=session.project_id,
                    marius_id=session.marius_id,
                    adapter_type=session.adapter_type,
                    task_id=session.task_id,
                    session_params_json=dict(session.session_params_json),
                    session_display_id=session.session_display_id,
                    last_run_id=session.last_run_id,
                    last_error=session.last_error,
                    created_at=session.created_at,
                    updated_at=session.updated_at,
                )
            )
        else:
            m.session_params_json = dict(session.session_params_json)
            m.session_display_id = session.session_display_id
            m.last_run_id = session.last_run_id
            m.last_error = session.last_error
            m.updated_at = session.updated_at
        await self._s.flush()
        return session

    async def delete(self, session_id: UUID) -> None:
        m = await self._s.get(SessionModel, session_id)
        if m is not None:
            await self._s.delete(m)
            await self._s.flush()


class SqlRunRepository(RunRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, run: Run) -> Run:
        self._s.add(
            RunModel(
                id=run.id,
                project_id=run.project_id,
                marius_id=run.marius_id,
                task_id=run.task_id,
                adapter_type=run.adapter_type,
                wake_source=str(run.wake_source),
                trigger_causes=causes_to_payload(run.trigger_causes),
                trigger_detail=run.trigger_detail,
                status=str(run.status),
                external_run_id=run.external_run_id,
                session_id_before=run.session_id_before,
                session_id_after=run.session_id_after,
                usage_json=dict(run.usage_json),
                error=run.error,
                next_action=run.next_action,
                continuation_attempt=run.continuation_attempt,
                started_at=run.started_at,
                finished_at=run.finished_at,
                last_output_at=run.last_output_at,
                created_at=run.created_at,
            )
        )
        try:
            await self._s.flush()
        except IntegrityError as exc:
            # The other half of FR-050: a live run already holds this (agent, task) pair.
            raise WakePairBusyError(
                "đã có một lượt chạy đang giữ cặp agent–đầu việc này"
            ) from exc
        return run

    async def get(self, run_id: UUID) -> Run | None:
        m = await self._s.get(RunModel, run_id)
        return mappers.run_to_entity(m) if m else None

    async def update(self, run: Run) -> Run:
        m = await self._s.get(RunModel, run.id)
        if m is None:
            raise NotFound("run_not_found")
        m.status = str(run.status)
        # Both of these change after a run is created: a cause folded in before the turn
        # starts re-files the run under the stronger cause and rewrites the merged reason
        # (FR-050). Leaving them out here dropped that write silently — no error, and the
        # cause was then excluded from the end-of-run re-check too, on the assumption it
        # had already reached the packet. It had not.
        m.wake_source = str(run.wake_source)
        m.trigger_causes = causes_to_payload(run.trigger_causes)
        m.trigger_detail = run.trigger_detail
        m.external_run_id = run.external_run_id
        m.session_id_before = run.session_id_before
        m.session_id_after = run.session_id_after
        m.usage_json = dict(run.usage_json)
        m.error = run.error
        m.next_action = run.next_action
        m.continuation_attempt = run.continuation_attempt
        m.started_at = run.started_at
        m.finished_at = run.finished_at
        m.last_output_at = run.last_output_at
        await self._s.flush()
        return run

    async def list_by_task(self, task_id: UUID) -> Sequence[Run]:
        rows = (
            await self._s.execute(
                select(RunModel)
                .where(RunModel.task_id == task_id)
                .order_by(RunModel.created_at)
            )
        ).scalars().all()
        return [mappers.run_to_entity(m) for m in rows]

    async def list_by_marius(self, marius_id: UUID) -> Sequence[Run]:
        # Newest-first: the agent-detail activity feed reads like a log, most recent on top.
        # `marius_id` is indexed on `runs`, so this stays a cheap point-lookup scan.
        rows = (
            await self._s.execute(
                select(RunModel)
                .where(RunModel.marius_id == marius_id)
                .order_by(RunModel.created_at.desc())
            )
        ).scalars().all()
        return [mappers.run_to_entity(m) for m in rows]

    async def get_active_for(self, marius_id: UUID, task_id: UUID) -> Run | None:
        # The partial unique index means there is at most one row, so the ordering should
        # never matter. It is here for the case where it does: a database the migration has
        # not reached yet would otherwise return whichever row the planner happened to hand
        # back first, and "which run holds this pair" would stop being a stable answer.
        m = (
            await self._s.execute(
                select(RunModel)
                .where(
                    RunModel.marius_id == marius_id,
                    RunModel.task_id == task_id,
                    RunModel.status.in_([str(s) for s in ACTIVE_RUN_STATUSES]),
                )
                .order_by(RunModel.created_at.desc())
            )
        ).scalars().first()
        return mappers.run_to_entity(m) if m else None

    async def task_ids_with_active_run(self, task_ids: Sequence[UUID]) -> set[UUID]:
        if not task_ids:
            return set()
        rows = (
            await self._s.execute(
                select(RunModel.task_id)
                .where(
                    RunModel.task_id.in_(list(task_ids)),
                    RunModel.status.in_([str(s) for s in ACTIVE_RUN_STATUSES]),
                )
                .distinct()
            )
        ).scalars().all()
        return {r for r in rows if r is not None}

    async def list_silent_active(
        self, silent_since: datetime, *, limit: int = 200
    ) -> Sequence[Run]:
        stmt = (
            select(RunModel)
            .where(RunModel.status.in_([str(s) for s in ACTIVE_RUN_STATUSES]))
            .where(
                func.coalesce(
                    RunModel.last_output_at, RunModel.started_at, RunModel.created_at
                )
                <= silent_since
            )
            .order_by(RunModel.created_at)
            .limit(limit)
        )
        rows = (await self._s.execute(stmt)).scalars().all()
        return [mappers.run_to_entity(m) for m in rows]

    async def has_active_for_task(self, task_id: UUID) -> bool:
        found = (
            await self._s.execute(
                select(RunModel.id)
                .where(
                    RunModel.task_id == task_id,
                    RunModel.status.in_([str(s) for s in ACTIVE_RUN_STATUSES]),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return found is not None


class SqlRunEventRepository(RunEventRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, event: RunEvent) -> RunEvent:
        self._s.add(
            RunEventModel(
                id=event.id,
                run_id=event.run_id,
                seq=event.seq,
                type=event.type,
                payload=dict(event.payload),
                created_at=event.created_at,
            )
        )
        await self._s.flush()
        return event

    async def list_by_run(self, run_id: UUID) -> Sequence[RunEvent]:
        rows = (
            await self._s.execute(
                select(RunEventModel)
                .where(RunEventModel.run_id == run_id)
                .order_by(RunEventModel.seq)
            )
        ).scalars().all()
        return [mappers.run_event_to_entity(m) for m in rows]


class SqlArtifactRepository(ArtifactRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, artifact: Artifact) -> Artifact:
        self._s.add(
            ArtifactModel(
                id=artifact.id,
                project_id=artifact.project_id,
                task_id=artifact.task_id,
                marius_id=artifact.marius_id,
                name=artifact.name,
                kind=artifact.kind,
                uri=artifact.uri,
                content_sha256=artifact.content_sha256,
                size_bytes=artifact.size_bytes,
                created_at=artifact.created_at,
            )
        )
        await self._s.flush()
        return artifact

    async def list_by_task(self, task_id: UUID) -> Sequence[Artifact]:
        rows = (
            await self._s.execute(
                select(ArtifactModel)
                .where(ArtifactModel.task_id == task_id)
                .order_by(ArtifactModel.created_at)
            )
        ).scalars().all()
        return [mappers.artifact_to_entity(m) for m in rows]

    async def count_by_task(self, task_id: UUID) -> int:
        result = await self._s.execute(
            select(func.count()).select_from(ArtifactModel).where(
                ArtifactModel.task_id == task_id
            )
        )
        return int(result.scalar_one())

    async def count_by_project(self, project_id: UUID) -> Mapping[UUID, int]:
        """Artifacts per task across one project. Joined through the task rather than read
        off ``ArtifactModel.project_id``: that column is nullable, so a row written without
        it would silently drop out of the count and the card would lose its clip."""
        rows = await self._s.execute(
            select(ArtifactModel.task_id, func.count())
            .join(TaskModel, TaskModel.id == ArtifactModel.task_id)
            .where(TaskModel.project_id == project_id)
            .group_by(ArtifactModel.task_id)
        )
        return {task_id: int(n) for task_id, n in rows.all()}


class SqlWakeupRepository(WakeupRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, wakeup: WakeupRequest) -> WakeupRequest:
        self._s.add(
            WakeupModel(
                id=wakeup.id,
                project_id=wakeup.project_id,
                marius_id=wakeup.marius_id,
                task_id=wakeup.task_id,
                source=str(wakeup.source),
                causes=causes_to_payload(wakeup.causes),
                reason=wakeup.reason,
                prompt=wakeup.prompt,
                status=str(wakeup.status),
                run_id=wakeup.run_id,
                created_at=wakeup.created_at,
                updated_at=wakeup.updated_at,
            )
        )
        try:
            await self._s.flush()
        except IntegrityError as exc:
            # The partial unique index refused a second pending wake for this pair. Hand
            # the caller a domain error rather than a driver one: the application layer
            # decides to fold the losing cause in, and it should not have to know which
            # database said no (FR-050).
            raise WakePairBusyError(
                "đã có một lệnh đánh thức đang treo cho cặp agent–đầu việc này"
            ) from exc
        return wakeup

    async def update(self, wakeup: WakeupRequest) -> WakeupRequest:
        m = await self._s.get(WakeupModel, wakeup.id)
        if m is None:
            raise LookupError("wakeup not found")
        m.source = str(wakeup.source)
        m.causes = causes_to_payload(wakeup.causes)
        m.reason = wakeup.reason
        m.prompt = wakeup.prompt
        m.status = str(wakeup.status)
        m.run_id = wakeup.run_id
        m.updated_at = wakeup.updated_at
        await self._s.flush()
        return wakeup

    async def list_active_for(
        self, marius_id: UUID, task_id: UUID
    ) -> Sequence[WakeupRequest]:
        rows = (
            await self._s.execute(
                select(WakeupModel).where(
                    WakeupModel.marius_id == marius_id,
                    WakeupModel.task_id == task_id,
                    WakeupModel.status.in_([str(s) for s in PENDING_WAKEUP_STATUSES]),
                )
            )
        ).scalars().all()
        return [mappers.wakeup_to_entity(m) for m in rows]

    async def list_pending_for_task(self, task_id: UUID) -> Sequence[WakeupRequest]:
        rows = (
            await self._s.execute(
                select(WakeupModel).where(
                    WakeupModel.task_id == task_id,
                    WakeupModel.status.in_([str(s) for s in PENDING_WAKEUP_STATUSES]),
                )
            )
        ).scalars().all()
        return [mappers.wakeup_to_entity(m) for m in rows]

    async def list_coalesced_into(self, run_id: UUID) -> Sequence[WakeupRequest]:
        rows = (
            await self._s.execute(
                select(WakeupModel)
                .where(
                    WakeupModel.run_id == run_id,
                    WakeupModel.status == str(WakeupStatus.COALESCED),
                )
                .order_by(WakeupModel.created_at)
            )
        ).scalars().all()
        return [mappers.wakeup_to_entity(m) for m in rows]


class SqlUserRepository(UserRepository):
    """SQLAlchemy implementation of UserRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, user: User) -> User:
        self._s.add(
            UserModel(
                id=user.id,
                email=user.email,
                username=user.username,
                full_name=user.full_name,
                hashed_password=user.hashed_password,
                role=str(user.role),
                is_active=user.is_active,
                is_verified=user.is_verified,
                created_at=user.created_at,
                updated_at=user.updated_at,
                last_login_at=user.last_login_at,
            )
        )
        await self._s.flush()
        return user

    async def get(self, user_id: UUID) -> User | None:
        m = await self._s.get(UserModel, user_id)
        return mappers.user_to_entity(m) if m else None

    async def get_by_email(self, email: str) -> User | None:
        row = (
            await self._s.execute(select(UserModel).where(UserModel.email == email.lower()))
        ).scalar_one_or_none()
        return mappers.user_to_entity(row) if row else None

    async def get_by_username(self, username: str) -> User | None:
        row = (
            await self._s.execute(
                select(UserModel).where(UserModel.username == username)
            )
        ).scalar_one_or_none()
        return mappers.user_to_entity(row) if row else None

    async def update(self, user: User) -> User:
        m = await self._s.get(UserModel, user.id)
        if m is None:
            raise LookupError("user not found")
        m.full_name = user.full_name
        m.hashed_password = user.hashed_password
        m.role = str(user.role)
        m.is_active = user.is_active
        m.is_verified = user.is_verified
        m.updated_at = user.updated_at
        m.last_login_at = user.last_login_at
        await self._s.flush()
        return user

    async def list(self) -> Sequence[User]:
        rows = (await self._s.execute(select(UserModel))).scalars().all()
        return [mappers.user_to_entity(m) for m in rows]


class SqlSkillRepository(SkillRepository):
    """SQLAlchemy implementation of SkillRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, skill: Skill) -> Skill:
        self._s.add(
            SkillModel(
                id=skill.id,
                workspace_id=skill.workspace_id,
                slug=skill.slug,
                name=skill.name,
                description=skill.description,
                source=skill.source,
                source_url=skill.source_url,
                files=dict(skill.files),
                created_at=skill.created_at,
                updated_at=skill.updated_at,
            )
        )
        await self._s.flush()
        return skill

    async def get(self, skill_id: UUID) -> Skill | None:
        m = await self._s.get(SkillModel, skill_id)
        return mappers.skill_to_entity(m) if m else None

    async def update(self, skill: Skill) -> Skill:
        m = await self._s.get(SkillModel, skill.id)
        if m is None:
            raise NotFound("skill_not_found")
        m.slug = skill.slug
        m.name = skill.name
        m.description = skill.description
        m.source = skill.source
        m.source_url = skill.source_url
        m.files = dict(skill.files)
        m.updated_at = skill.updated_at
        await self._s.flush()
        return skill

    async def list_by_workspace(self, workspace_id: UUID) -> Sequence[Skill]:
        rows = (
            await self._s.execute(
                select(SkillModel)
                .where(SkillModel.workspace_id == workspace_id)
                .order_by(SkillModel.created_at)
            )
        ).scalars().all()
        return [mappers.skill_to_entity(m) for m in rows]

    async def get_by_slug(self, workspace_id: UUID, slug: str) -> Skill | None:
        row = (
            await self._s.execute(
                select(SkillModel).where(
                    SkillModel.workspace_id == workspace_id,
                    SkillModel.slug == slug,
                )
            )
        ).scalar_one_or_none()
        return mappers.skill_to_entity(row) if row else None

    async def list_by_ids(self, skill_ids: list[UUID]) -> Sequence[Skill]:
        if not skill_ids:
            return []
        rows = (
            await self._s.execute(
                select(SkillModel).where(SkillModel.id.in_(skill_ids))
            )
        ).scalars().all()
        return [mappers.skill_to_entity(m) for m in rows]

    async def remove(self, skill_id: UUID) -> None:
        m = await self._s.get(SkillModel, skill_id)
        if m is not None:
            await self._s.delete(m)
        await self._s.flush()


class SqlTaskLogRepository(TaskLogRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def append(self, entry: TaskLogEntry) -> TaskLogEntry:
        self._s.add(
            TaskLogModel(
                id=entry.id,
                task_id=entry.task_id,
                seq=entry.seq,
                kind=str(entry.kind),
                actor_kind=str(entry.actor_kind),
                actor_marius_id=entry.actor_marius_id,
                actor_user_id=entry.actor_user_id,
                before_value=entry.before,
                after_value=entry.after,
                reason=entry.reason,
                detail=dict(entry.detail or {}),
                created_at=entry.created_at,
            )
        )
        await self._s.flush()
        return entry

    async def next_seq(self, task_id: UUID) -> int:
        """One past the highest seq recorded for this task (1 for a fresh task).

        The ``uq_task_log_task_seq`` constraint is what actually makes this safe: two
        writers reading the same maximum cannot both commit.
        """
        highest = (
            await self._s.execute(
                select(func.max(TaskLogModel.seq)).where(TaskLogModel.task_id == task_id)
            )
        ).scalar_one_or_none()
        return int(highest or 0) + 1

    async def list_by_task(self, task_id: UUID) -> Sequence[TaskLogEntry]:
        rows = (
            await self._s.execute(
                select(TaskLogModel)
                .where(TaskLogModel.task_id == task_id)
                .order_by(TaskLogModel.seq)
            )
        ).scalars().all()
        return [mappers.task_log_to_entity(m) for m in rows]


class SqlInboxRepository(InboxRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, item: InboxItem) -> InboxItem:
        self._s.add(
            InboxItemModel(
                id=item.id,
                workspace_id=item.workspace_id,
                recipient_user_id=item.recipient_user_id,
                project_id=item.project_id,
                task_id=item.task_id,
                kind=str(item.kind),
                status=str(item.status),
                title=item.title,
                body=item.body,
                reminder_tier=item.reminder_tier,
                attempt_dossier=dict(item.attempt_dossier or {}),
                created_at=item.created_at,
                last_reminded_at=item.last_reminded_at,
                resolved_at=item.resolved_at,
            )
        )
        await self._s.flush()
        return item

    async def get(self, item_id: UUID) -> InboxItem | None:
        m = await self._s.get(InboxItemModel, item_id)
        return mappers.inbox_item_to_entity(m) if m else None

    async def update(self, item: InboxItem) -> InboxItem:
        m = await self._s.get(InboxItemModel, item.id)
        if m is None:
            return item
        m.status = str(item.status)
        m.title = item.title
        m.body = item.body
        m.reminder_tier = item.reminder_tier
        m.attempt_dossier = dict(item.attempt_dossier or {})
        m.last_reminded_at = item.last_reminded_at
        m.resolved_at = item.resolved_at
        await self._s.flush()
        return item

    async def list_for_recipient(
        self,
        recipient_user_id: str,
        *,
        status: InboxItemStatus | None = None,
        project_id: UUID | None = None,
    ) -> Sequence[InboxItem]:
        stmt = select(InboxItemModel).where(
            InboxItemModel.recipient_user_id == recipient_user_id
        )
        if status is not None:
            stmt = stmt.where(InboxItemModel.status == str(status))
        if project_id is not None:
            stmt = stmt.where(InboxItemModel.project_id == project_id)
        rows = (
            await self._s.execute(stmt.order_by(InboxItemModel.created_at))
        ).scalars().all()
        return [mappers.inbox_item_to_entity(m) for m in rows]

    async def list_pending_for_task(self, task_id: UUID) -> Sequence[InboxItem]:
        rows = (
            await self._s.execute(
                select(InboxItemModel)
                .where(InboxItemModel.task_id == task_id)
                .where(InboxItemModel.status == str(InboxItemStatus.PENDING))
                .order_by(InboxItemModel.created_at)
            )
        ).scalars().all()
        return [mappers.inbox_item_to_entity(m) for m in rows]

    async def list_pending_for_project(self, project_id: UUID) -> Sequence[InboxItem]:
        rows = (
            await self._s.execute(
                select(InboxItemModel)
                .where(InboxItemModel.project_id == project_id)
                .where(InboxItemModel.status == str(InboxItemStatus.PENDING))
                .order_by(InboxItemModel.created_at)
            )
        ).scalars().all()
        return [mappers.inbox_item_to_entity(m) for m in rows]

    async def list_pending(self, *, limit: int = 500) -> Sequence[InboxItem]:
        stmt = (
            select(InboxItemModel)
            .where(InboxItemModel.status == str(InboxItemStatus.PENDING))
            .order_by(InboxItemModel.created_at)
            .limit(limit)
        )
        rows = (await self._s.execute(stmt)).scalars().all()
        return [mappers.inbox_item_to_entity(m) for m in rows]


class SqlProjectContextRepository(ProjectContextRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, context: ProjectContext) -> ProjectContext:
        self._s.add(
            ProjectContextModel(
                id=context.id,
                project_id=context.project_id,
                version=context.version,
                objective=context.objective,
                background=context.background,
                constraints=context.constraints,
                scope=context.scope,
                principles=context.principles,
                approval_status=str(context.approval_status),
                approved_at=context.approved_at,
                approved_by_user_id=context.approved_by_user_id,
                created_at=context.created_at,
                updated_at=context.updated_at,
            )
        )
        await self._s.flush()
        return context

    async def update(self, context: ProjectContext) -> ProjectContext:
        m = await self._s.get(ProjectContextModel, context.id)
        if m is None:
            return context
        m.objective = context.objective
        m.background = context.background
        m.constraints = context.constraints
        m.scope = context.scope
        m.principles = context.principles
        m.approval_status = str(context.approval_status)
        m.approved_at = context.approved_at
        m.approved_by_user_id = context.approved_by_user_id
        m.updated_at = context.updated_at
        await self._s.flush()
        return context

    async def _by_status(
        self, project_id: UUID, status: ContextApprovalStatus
    ) -> ProjectContext | None:
        row = (
            await self._s.execute(
                select(ProjectContextModel)
                .where(ProjectContextModel.project_id == project_id)
                .where(ProjectContextModel.approval_status == str(status))
                .order_by(ProjectContextModel.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return mappers.project_context_to_entity(row) if row else None

    async def get_approved(self, project_id: UUID) -> ProjectContext | None:
        """The version in force — the one attached to wake packets (FR-009)."""
        return await self._by_status(project_id, ContextApprovalStatus.APPROVED)

    async def get_pending(self, project_id: UUID) -> ProjectContext | None:
        """The version awaiting the patron. Has no effect until approved (FR-010)."""
        return await self._by_status(project_id, ContextApprovalStatus.SUBMITTED)

    async def latest_version(self, project_id: UUID) -> int:
        highest = (
            await self._s.execute(
                select(func.max(ProjectContextModel.version)).where(
                    ProjectContextModel.project_id == project_id
                )
            )
        ).scalar_one_or_none()
        return int(highest or 0)


class SqlPlanRepository(PlanRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, plan: Plan) -> Plan:
        self._s.add(
            PlanModel(
                id=plan.id,
                project_id=plan.project_id,
                version=plan.version,
                summary=plan.summary,
                risks=plan.risks,
                milestones=plan.milestones,
                status=str(plan.status),
                patron_note=plan.patron_note,
                submitted_at=plan.submitted_at,
                decided_at=plan.decided_at,
                decided_by_user_id=plan.decided_by_user_id,
                created_at=plan.created_at,
                updated_at=plan.updated_at,
            )
        )
        # Flush the plan BEFORE its items. There is no ORM relationship between the two
        # (plain FK column), so SQLAlchemy has no dependency to sort by and can emit the
        # child INSERTs first — which PostgreSQL rejects on the foreign key while SQLite,
        # with FK enforcement off by default, silently accepts. Found by running the real
        # stack, not by the test suite.
        await self._s.flush()
        for item in plan.items:
            item.plan_id = plan.id
            self._s.add(
                PlanItemModel(
                    id=item.id,
                    plan_id=plan.id,
                    title=item.title,
                    description=item.description,
                    order_index=item.order,
                    depends_on=[str(x) for x in item.depends_on],
                    definition_of_done=item.definition_of_done,
                    created_at=item.created_at,
                )
            )
        await self._s.flush()
        return plan

    async def update(self, plan: Plan) -> Plan:
        """Plan-level fields only. Items are replaced by submitting a new version, so a
        decision can never silently land on a different set of items than the one the
        patron read."""
        m = await self._s.get(PlanModel, plan.id)
        if m is None:
            return plan
        m.summary = plan.summary
        m.risks = plan.risks
        m.milestones = plan.milestones
        m.status = str(plan.status)
        m.patron_note = plan.patron_note
        m.submitted_at = plan.submitted_at
        m.decided_at = plan.decided_at
        m.decided_by_user_id = plan.decided_by_user_id
        m.updated_at = plan.updated_at
        await self._s.flush()
        return plan

    async def _items(self, plan_id: UUID) -> list[PlanItemModel]:
        return list(
            (
                await self._s.execute(
                    select(PlanItemModel)
                    .where(PlanItemModel.plan_id == plan_id)
                    .order_by(PlanItemModel.order_index)
                )
            ).scalars().all()
        )

    async def get(self, plan_id: UUID) -> Plan | None:
        m = await self._s.get(PlanModel, plan_id)
        if m is None:
            return None
        return mappers.plan_to_entity(m, await self._items(plan_id))

    async def get_current(self, project_id: UUID) -> Plan | None:
        """The newest version, whatever its status — what both surfaces show."""
        row = (
            await self._s.execute(
                select(PlanModel)
                .where(PlanModel.project_id == project_id)
                .order_by(PlanModel.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return mappers.plan_to_entity(row, await self._items(row.id))

    async def get_approved(self, project_id: UUID) -> Plan | None:
        """The version in force — its items define what counts as in scope (FR-027)."""
        row = (
            await self._s.execute(
                select(PlanModel)
                .where(PlanModel.project_id == project_id)
                .where(PlanModel.status == "approved")
                .order_by(PlanModel.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return mappers.plan_to_entity(row, await self._items(row.id))

    async def latest_version(self, project_id: UUID) -> int:
        highest = (
            await self._s.execute(
                select(func.max(PlanModel.version)).where(
                    PlanModel.project_id == project_id
                )
            )
        ).scalar_one_or_none()
        return int(highest or 0)


class SqlOrchestrationSweepRepository(OrchestrationSweepRepository):
    """Append-only, newest-first (spec 001 FR-052 → FR-055).

    The whole point of these rows is that a quiet sweep is still evidence the loop ran,
    so there is no path here that skips writing one.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, sweep: OrchestrationSweep) -> OrchestrationSweep:
        self._s.add(
            OrchestrationSweepModel(
                id=sweep.id,
                project_id=sweep.project_id,
                swept_at=sweep.swept_at,
                snags=[mappers.snag_to_row(s) for s in sweep.snags],
                snag_count=sweep.snag_count,
                woke_leader=sweep.woke_leader,
                skipped_reason=sweep.skipped_reason,
                next_interval_seconds=sweep.next_interval_seconds,
                reported_marks=dict(sweep.reported_marks),
            )
        )
        await self._s.flush()
        return sweep

    async def list_recent(
        self, project_id: UUID, *, limit: int = 32
    ) -> Sequence[OrchestrationSweep]:
        rows = (
            await self._s.execute(
                select(OrchestrationSweepModel)
                .where(OrchestrationSweepModel.project_id == project_id)
                # `id` breaks the tie so two sweeps sharing a timestamp — which the tests'
                # fixed clock produces on purpose — still come back in a stable order.
                .order_by(
                    OrchestrationSweepModel.swept_at.desc(),
                    OrchestrationSweepModel.id.desc(),
                )
                .limit(limit)
            )
        ).scalars()
        return [mappers.orchestration_sweep_to_entity(r) for r in rows]

    async def count_wakes_since(self, project_id: UUID, since: datetime) -> int:
        total = (
            await self._s.execute(
                select(func.count())
                .select_from(OrchestrationSweepModel)
                .where(
                    OrchestrationSweepModel.project_id == project_id,
                    OrchestrationSweepModel.woke_leader.is_(True),
                    OrchestrationSweepModel.swept_at >= since,
                )
            )
        ).scalar_one()
        return int(total or 0)
