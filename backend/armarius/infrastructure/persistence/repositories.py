"""SQLAlchemy implementations of the domain repository ports."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from armarius.domain.entities.artifact import Artifact
from armarius.domain.entities.comment import Comment
from armarius.domain.entities.marius import Marius
from armarius.domain.entities.run import Run, RunEvent
from armarius.domain.entities.session import AgentTaskSession
from armarius.domain.entities.task import Task
from armarius.domain.entities.wakeup import WakeupRequest
from armarius.domain.entities.workspace import Project, Workspace
from armarius.domain.repositories.repositories import (
    ArtifactRepository,
    CommentRepository,
    MariusRepository,
    ProjectRepository,
    RunEventRepository,
    RunRepository,
    SessionRepository,
    TaskRepository,
    WakeupRepository,
    WorkspaceRepository,
)
from armarius.infrastructure.database.models import (
    ArtifactModel,
    CommentModel,
    MariusModel,
    ProjectModel,
    RunEventModel,
    RunModel,
    SessionModel,
    TaskModel,
    WakeupModel,
    WorkspaceModel,
)
from armarius.infrastructure.persistence import mappers


class SqlWorkspaceRepository(WorkspaceRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, workspace: Workspace) -> Workspace:
        self._s.add(
            WorkspaceModel(
                id=workspace.id,
                name=workspace.name,
                slug=workspace.slug,
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
                description=project.description,
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
                owner_user_id=marius.owner_user_id,
                agent_token=marius.agent_token,
                liveness=str(marius.liveness),
                last_seen_at=marius.last_seen_at,
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

    async def update(self, marius: Marius) -> Marius:
        m = await self._s.get(MariusModel, marius.id)
        if m is None:
            raise LookupError("marius not found")
        m.name = marius.name
        m.role = marius.role
        m.skills = list(marius.skills)
        m.adapter_type = marius.adapter_type
        m.adapter_config = dict(marius.adapter_config)
        m.owner_user_id = marius.owner_user_id
        m.liveness = str(marius.liveness)
        m.last_seen_at = marius.last_seen_at
        m.updated_at = marius.updated_at
        await self._s.flush()
        return marius


class SqlTaskRepository(TaskRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def add(self, task: Task) -> Task:
        self._s.add(
            TaskModel(
                id=task.id,
                project_id=task.project_id,
                title=task.title,
                description=task.description,
                status=str(task.status),
                status_reason=task.status_reason,
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
            raise LookupError("task not found")
        m.title = task.title
        m.description = task.description
        m.status = str(task.status)
        m.status_reason = task.status_reason
        m.assigned_marius_id = task.assigned_marius_id
        m.next_action = task.next_action
        m.in_progress_at = task.in_progress_at
        m.completed_at = task.completed_at
        m.updated_at = task.updated_at
        await self._s.flush()
        return task


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
        await self._s.flush()
        return run

    async def get(self, run_id: UUID) -> Run | None:
        m = await self._s.get(RunModel, run_id)
        return mappers.run_to_entity(m) if m else None

    async def update(self, run: Run) -> Run:
        m = await self._s.get(RunModel, run.id)
        if m is None:
            raise LookupError("run not found")
        m.status = str(run.status)
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
                reason=wakeup.reason,
                prompt=wakeup.prompt,
                status=str(wakeup.status),
                run_id=wakeup.run_id,
                created_at=wakeup.created_at,
                updated_at=wakeup.updated_at,
            )
        )
        await self._s.flush()
        return wakeup

    async def update(self, wakeup: WakeupRequest) -> WakeupRequest:
        m = await self._s.get(WakeupModel, wakeup.id)
        if m is None:
            raise LookupError("wakeup not found")
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
                    WakeupModel.status.in_(["queued", "dispatched"]),
                )
            )
        ).scalars().all()
        return [mappers.wakeup_to_entity(m) for m in rows]
