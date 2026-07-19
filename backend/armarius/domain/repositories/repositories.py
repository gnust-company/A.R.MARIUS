"""Repository interfaces (ports). Infrastructure implements these; the application
layer depends only on these abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from armarius.domain.entities.artifact import Artifact
from armarius.domain.entities.comment import Comment
from armarius.domain.entities.commission import CommissionSession
from armarius.domain.entities.label import Label
from armarius.domain.entities.leader_chat import ProjectLeaderConversation
from armarius.domain.entities.marius import Marius
from armarius.domain.entities.onboarding import OnboardingSession
from armarius.domain.entities.role import Role
from armarius.domain.entities.run import Run, RunEvent
from armarius.domain.entities.seat_grant import SeatGrant
from armarius.domain.entities.session import AgentTaskSession
from armarius.domain.entities.skill import Skill
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
    @abstractmethod
    async def update(self, workspace: Workspace) -> Workspace: ...
    @abstractmethod
    async def remove(self, workspace_id: UUID) -> None:
        """Delete a workspace and every child it owns (projects + their roster/tasks,
        mariuses, skills, labels). No FK has ``ON DELETE CASCADE`` so the aggregate
        cascade is explicit — identical behaviour on SQLite and Postgres."""


class ProjectRepository(ABC):
    @abstractmethod
    async def add(self, project: Project) -> Project: ...
    @abstractmethod
    async def get(self, project_id: UUID) -> Project | None: ...
    @abstractmethod
    async def list_by_workspace(self, workspace_id: UUID) -> Sequence[Project]: ...
    @abstractmethod
    async def get_by_key(self, workspace_id: UUID, key: str) -> Project | None: ...
    @abstractmethod
    async def allocate_task_number(self, project_id: UUID) -> int:
        """Atomically increment + return the next per-project task sequence number.

        A single ``UPDATE … RETURNING`` so concurrent creates never share a number.
        """
    @abstractmethod
    async def update(self, project: Project) -> Project: ...
    @abstractmethod
    async def remove(self, project_id: UUID) -> None: ...


class RoleRepository(ABC):
    """Roster seats of a project (LLD §2.3)."""

    @abstractmethod
    async def add(self, role: Role) -> Role: ...
    @abstractmethod
    async def get(self, role_id: UUID) -> Role | None: ...
    @abstractmethod
    async def list_by_project(self, project_id: UUID) -> Sequence[Role]: ...
    @abstractmethod
    async def update(self, role: Role) -> Role: ...
    @abstractmethod
    async def remove(self, role_id: UUID) -> None: ...


class SeatGrantRepository(ABC):
    """System-only seat assignments (LLD §2.4, §3.3)."""

    @abstractmethod
    async def add(self, grant: SeatGrant) -> SeatGrant: ...
    @abstractmethod
    async def get(self, grant_id: UUID) -> SeatGrant | None: ...
    @abstractmethod
    async def list_by_project(self, project_id: UUID) -> Sequence[SeatGrant]: ...
    @abstractmethod
    async def update(self, grant: SeatGrant) -> SeatGrant: ...


class LabelRepository(ABC):
    """Workspace-scoped task tags (API_CONTRACT §5.4)."""

    @abstractmethod
    async def add(self, label: Label) -> Label: ...
    @abstractmethod
    async def list_by_workspace(self, workspace_id: UUID) -> Sequence[Label]: ...


class CommissionRepository(ABC):
    """Leader-mediated commission chats (LLD §2.13)."""

    @abstractmethod
    async def add(self, session: CommissionSession) -> CommissionSession: ...
    @abstractmethod
    async def get(self, session_id: UUID) -> CommissionSession | None: ...
    @abstractmethod
    async def update(self, session: CommissionSession) -> CommissionSession: ...
    @abstractmethod
    async def list_open_by_leader(
        self, leader_marius_id: UUID
    ) -> Sequence[CommissionSession]:
        """Open commissions a Leader owns — used to drain queued turns on online."""


class LeaderChatRepository(ABC):
    """Project-level Chat-with-Leader conversations (#82). One per project."""

    @abstractmethod
    async def add(
        self, conversation: ProjectLeaderConversation
    ) -> ProjectLeaderConversation: ...
    @abstractmethod
    async def get(self, conversation_id: UUID) -> ProjectLeaderConversation | None: ...
    @abstractmethod
    async def get_by_project(
        self, project_id: UUID
    ) -> ProjectLeaderConversation | None:
        """The single conversation for a project, or None if it was never opened."""
    @abstractmethod
    async def update(
        self, conversation: ProjectLeaderConversation
    ) -> ProjectLeaderConversation: ...


class OnboardingRepository(ABC):
    """Agent-assisted project-setup chats (LLD §2.10, Sprint 7 / Phase G)."""

    @abstractmethod
    async def add(self, session: OnboardingSession) -> OnboardingSession: ...
    @abstractmethod
    async def get(self, session_id: UUID) -> OnboardingSession | None: ...
    @abstractmethod
    async def update(self, session: OnboardingSession) -> OnboardingSession: ...
    @abstractmethod
    async def list_by_workspace(
        self, workspace_id: UUID
    ) -> Sequence[OnboardingSession]:
        """All sessions for a workspace (newest first) — the active one is the first OPEN."""


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
    async def list_by_ids(self, marius_ids: list[UUID]) -> Sequence[Marius]: ...
    @abstractmethod
    async def update(self, marius: Marius) -> Marius: ...
    @abstractmethod
    async def remove(self, marius_id: UUID) -> None:
        """Delete a Marius and vacate any roster seats it held."""


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
    @abstractmethod
    async def list_by_marius(self, marius_id: UUID) -> Sequence[Run]: ...


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


class SkillRepository(ABC):
    """Repository for Skill entities (workspace-scoped Skill Shop)."""

    @abstractmethod
    async def add(self, skill: Skill) -> Skill: ...
    @abstractmethod
    async def get(self, skill_id: UUID) -> Skill | None: ...
    @abstractmethod
    async def update(self, skill: Skill) -> Skill: ...
    @abstractmethod
    async def list_by_workspace(self, workspace_id: UUID) -> Sequence[Skill]: ...
    @abstractmethod
    async def get_by_slug(self, workspace_id: UUID, slug: str) -> Skill | None: ...
    @abstractmethod
    async def list_by_ids(self, skill_ids: list[UUID]) -> Sequence[Skill]: ...
    @abstractmethod
    async def remove(self, skill_id: UUID) -> None: ...


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
