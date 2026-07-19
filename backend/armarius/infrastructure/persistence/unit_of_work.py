"""SQLAlchemy Unit of Work — binds the repositories to one async session/transaction."""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from armarius.application.ports.unit_of_work import UnitOfWork
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.persistence.repositories import (
    SqlArtifactRepository,
    SqlCommentRepository,
    SqlLabelRepository,
    SqlLeaderChatRepository,
    SqlMariusRepository,
    SqlOnboardingRepository,
    SqlProjectRepository,
    SqlRoleRepository,
    SqlRunEventRepository,
    SqlRunRepository,
    SqlSeatGrantRepository,
    SqlSessionRepository,
    SqlSkillRepository,
    SqlTaskDependencyRepository,
    SqlTaskRepository,
    SqlUserRepository,
    SqlWakeupRepository,
    SqlWorkspaceRepository,
)


class SqlAlchemyUnitOfWork(UnitOfWork):
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._sessionmaker = sessionmaker or get_sessionmaker()
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        self._session = self._sessionmaker()
        s = self._session
        self.workspaces = SqlWorkspaceRepository(s)
        self.labels = SqlLabelRepository(s)
        self.leader_chats = SqlLeaderChatRepository(s)
        self.onboardings = SqlOnboardingRepository(s)
        self.projects = SqlProjectRepository(s)
        self.roles = SqlRoleRepository(s)
        self.seat_grants = SqlSeatGrantRepository(s)
        self.mariuses = SqlMariusRepository(s)
        self.tasks = SqlTaskRepository(s)
        self.dependencies = SqlTaskDependencyRepository(s)
        self.comments = SqlCommentRepository(s)
        self.sessions = SqlSessionRepository(s)
        self.runs = SqlRunRepository(s)
        self.run_events = SqlRunEventRepository(s)
        self.artifacts = SqlArtifactRepository(s)
        self.wakeups = SqlWakeupRepository(s)
        self.users = SqlUserRepository(s)
        self.skills = SqlSkillRepository(s)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self._session is not None
        try:
            if exc_type is not None:
                await self._session.rollback()
        finally:
            await self._session.close()
            self._session = None

    async def commit(self) -> None:
        assert self._session is not None
        await self._session.commit()

    async def rollback(self) -> None:
        assert self._session is not None
        await self._session.rollback()


def make_uow() -> SqlAlchemyUnitOfWork:
    """UoW factory used across the application layer."""
    return SqlAlchemyUnitOfWork()
