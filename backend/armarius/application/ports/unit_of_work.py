"""Unit of Work port — a transactional boundary aggregating the repositories.

Use cases depend on this abstraction, not on SQLAlchemy. The infrastructure layer
provides a concrete implementation bound to an async DB session.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from types import TracebackType

from armarius.domain.repositories.repositories import (
    ArtifactRepository,
    CommentRepository,
    CommissionRepository,
    LabelRepository,
    MariusRepository,
    ProjectRepository,
    RoleRepository,
    RunEventRepository,
    RunRepository,
    SeatGrantRepository,
    SessionRepository,
    SkillRepository,
    TaskRepository,
    UserRepository,
    WakeupRepository,
    WorkspaceRepository,
)


class UnitOfWork(ABC):
    workspaces: WorkspaceRepository
    labels: LabelRepository
    commissions: CommissionRepository
    projects: ProjectRepository
    roles: RoleRepository
    seat_grants: SeatGrantRepository
    mariuses: MariusRepository
    tasks: TaskRepository
    comments: CommentRepository
    sessions: SessionRepository
    runs: RunRepository
    run_events: RunEventRepository
    artifacts: ArtifactRepository
    wakeups: WakeupRepository
    users: UserRepository
    skills: SkillRepository

    @abstractmethod
    async def __aenter__(self) -> UnitOfWork: ...

    @abstractmethod
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    @abstractmethod
    async def commit(self) -> None: ...

    @abstractmethod
    async def rollback(self) -> None: ...
