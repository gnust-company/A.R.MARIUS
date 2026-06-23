"""Repository interfaces (ports). Infrastructure implements these; the application
layer depends only on these abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from armarius.domain.entities.artifact import Artifact
from armarius.domain.entities.comment import Comment
from armarius.domain.entities.marius import Marius
from armarius.domain.entities.run import Run, RunEvent
from armarius.domain.entities.session import AgentTaskSession
from armarius.domain.entities.task import Task
from armarius.domain.entities.user import User
from armarius.domain.entities.wakeup import WakeupRequest
from armarius.domain.entities.workspace import Project, Workspace


class WorkspaceRepository(ABC):
    @abstractmethod
    async def add(self, workspace: Workspace) -> Workspace: ...
    @abstractmethod
    async def get(self, workspace_id: UUID) -> Workspace | None: ...
    @abstractmethod
    async def list(self) -> Sequence[Workspace]: ...
    @abstractmethod
    async def list_by_owner(self, owner_user_id: str) -> Sequence[Workspace]: ...


class ProjectRepository(ABC):
    @abstractmethod
    async def add(self, project: Project) -> Project: ...
    @abstractmethod
    async def get(self, project_id: UUID) -> Project | None: ...
    @abstractmethod
    async def list_by_workspace(self, workspace_id: UUID) -> Sequence[Project]: ...


class MariusRepository(ABC):
    @abstractmethod
    async def add(self, marius: Marius) -> Marius: ...
    @abstractmethod
    async def get(self, marius_id: UUID) -> Marius | None: ...
    @abstractmethod
    async def get_by_token(self, token: str) -> Marius | None: ...
    @abstractmethod
    async def list_by_workspace(self, workspace_id: UUID) -> Sequence[Marius]: ...
    @abstractmethod
    async def update(self, marius: Marius) -> Marius: ...


class TaskRepository(ABC):
    @abstractmethod
    async def add(self, task: Task) -> Task: ...
    @abstractmethod
    async def get(self, task_id: UUID) -> Task | None: ...
    @abstractmethod
    async def list_by_project(
        self, project_id: UUID, *, statuses: list[str] | None = None
    ) -> Sequence[Task]: ...
    @abstractmethod
    async def update(self, task: Task) -> Task: ...


class CommentRepository(ABC):
    @abstractmethod
    async def add(self, comment: Comment) -> Comment: ...
    @abstractmethod
    async def list_by_task(self, task_id: UUID) -> Sequence[Comment]: ...
    @abstractmethod
    async def list_since(self, task_id: UUID, after_seq: int) -> Sequence[Comment]: ...


class SessionRepository(ABC):
    @abstractmethod
    async def get_for(
        self, marius_id: UUID, adapter_type: str, task_id: UUID
    ) -> AgentTaskSession | None: ...
    @abstractmethod
    async def upsert(self, session: AgentTaskSession) -> AgentTaskSession: ...
    @abstractmethod
    async def delete(self, session_id: UUID) -> None: ...


class RunRepository(ABC):
    @abstractmethod
    async def add(self, run: Run) -> Run: ...
    @abstractmethod
    async def get(self, run_id: UUID) -> Run | None: ...
    @abstractmethod
    async def update(self, run: Run) -> Run: ...
    @abstractmethod
    async def list_by_task(self, task_id: UUID) -> Sequence[Run]: ...


class RunEventRepository(ABC):
    @abstractmethod
    async def add(self, event: RunEvent) -> RunEvent: ...
    @abstractmethod
    async def list_by_run(self, run_id: UUID) -> Sequence[RunEvent]: ...


class ArtifactRepository(ABC):
    @abstractmethod
    async def add(self, artifact: Artifact) -> Artifact: ...
    @abstractmethod
    async def list_by_task(self, task_id: UUID) -> Sequence[Artifact]: ...
    @abstractmethod
    async def count_by_task(self, task_id: UUID) -> int: ...


class WakeupRepository(ABC):
    @abstractmethod
    async def add(self, wakeup: WakeupRequest) -> WakeupRequest: ...
    @abstractmethod
    async def update(self, wakeup: WakeupRequest) -> WakeupRequest: ...
    @abstractmethod
    async def list_active_for(
        self, marius_id: UUID, task_id: UUID
    ) -> Sequence[WakeupRequest]: ...


class UserRepository(ABC):
    """Repository for User entities (human users)."""

    @abstractmethod
    async def add(self, user: User) -> User: ...

    @abstractmethod
    async def get(self, user_id: UUID) -> User | None: ...

    @abstractmethod
    async def get_by_email(self, email: str) -> User | None: ...

    @abstractmethod
    async def get_by_username(self, username: str) -> User | None: ...

    @abstractmethod
    async def update(self, user: User) -> User: ...

    @abstractmethod
    async def list(self) -> Sequence[User]: ...
