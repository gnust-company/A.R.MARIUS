"""In-memory fakes of the application ports — drive use cases without SQLAlchemy.

A single `_Store` is shared across every `FakeUnitOfWork` a `FakeUowFactory` hands out,
so writes committed in one UoW are visible to the next (mirroring a real DB across
transactions). `commit`/`rollback` are no-ops: repos mutate the shared store directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import TracebackType
from uuid import UUID

from armarius.application.ports.liveness_probe import LivenessProbe
from armarius.application.ports.unit_of_work import UnitOfWork
from armarius.domain.entities.marius import Marius
from armarius.domain.entities.role import Role
from armarius.domain.entities.seat_grant import SeatGrant
from armarius.domain.entities.skill import Skill
from armarius.domain.entities.workspace import Project, Workspace


@dataclass
class _Store:
    workspaces: dict[UUID, Workspace] = field(default_factory=dict)
    projects: dict[UUID, Project] = field(default_factory=dict)
    roles: dict[UUID, Role] = field(default_factory=dict)
    seat_grants: dict[UUID, SeatGrant] = field(default_factory=dict)
    mariuses: dict[UUID, Marius] = field(default_factory=dict)
    skills: dict[UUID, Skill] = field(default_factory=dict)


class _FakeWorkspaceRepo:
    def __init__(self, store: _Store) -> None:
        self._s = store

    async def add(self, ws: Workspace) -> Workspace:
        self._s.workspaces[ws.id] = ws
        return ws

    async def get(self, workspace_id: UUID) -> Workspace | None:
        return self._s.workspaces.get(workspace_id)

    async def list(self) -> list[Workspace]:
        return list(self._s.workspaces.values())

    async def list_by_owner(self, owner_user_id: str) -> list[Workspace]:
        return [w for w in self._s.workspaces.values() if w.owner_user_id == owner_user_id]


class _FakeProjectRepo:
    def __init__(self, store: _Store) -> None:
        self._s = store

    async def add(self, project: Project) -> Project:
        self._s.projects[project.id] = project
        return project

    async def get(self, project_id: UUID) -> Project | None:
        return self._s.projects.get(project_id)

    async def list_by_workspace(self, workspace_id: UUID) -> list[Project]:
        return [p for p in self._s.projects.values() if p.workspace_id == workspace_id]

    async def update(self, project: Project) -> Project:
        self._s.projects[project.id] = project
        return project


class _FakeRoleRepo:
    def __init__(self, store: _Store) -> None:
        self._s = store

    async def add(self, role: Role) -> Role:
        self._s.roles[role.id] = role
        return role

    async def get(self, role_id: UUID) -> Role | None:
        return self._s.roles.get(role_id)

    async def list_by_project(self, project_id: UUID) -> list[Role]:
        return [r for r in self._s.roles.values() if r.project_id == project_id]

    async def update(self, role: Role) -> Role:
        self._s.roles[role.id] = role
        return role

    async def remove(self, role_id: UUID) -> None:
        self._s.roles.pop(role_id, None)


class _FakeSeatGrantRepo:
    def __init__(self, store: _Store) -> None:
        self._s = store

    async def add(self, grant: SeatGrant) -> SeatGrant:
        self._s.seat_grants[grant.id] = grant
        return grant

    async def get(self, grant_id: UUID) -> SeatGrant | None:
        return self._s.seat_grants.get(grant_id)

    async def list_by_project(self, project_id: UUID) -> list[SeatGrant]:
        return [g for g in self._s.seat_grants.values() if g.project_id == project_id]

    async def update(self, grant: SeatGrant) -> SeatGrant:
        self._s.seat_grants[grant.id] = grant
        return grant


class _FakeMariusRepo:
    def __init__(self, store: _Store) -> None:
        self._s = store

    async def add(self, marius: Marius) -> Marius:
        self._s.mariuses[marius.id] = marius
        return marius

    async def get(self, marius_id: UUID) -> Marius | None:
        return self._s.mariuses.get(marius_id)

    async def get_by_token(self, token: str) -> Marius | None:
        return next((m for m in self._s.mariuses.values() if m.agent_token == token), None)

    async def list_by_workspace(self, workspace_id: UUID) -> list[Marius]:
        return [m for m in self._s.mariuses.values() if m.workspace_id == workspace_id]

    async def update(self, marius: Marius) -> Marius:
        self._s.mariuses[marius.id] = marius
        return marius


class _FakeSkillRepo:
    def __init__(self, store: _Store) -> None:
        self._s = store

    async def add(self, skill: Skill) -> Skill:
        self._s.skills[skill.id] = skill
        return skill

    async def get(self, skill_id: UUID) -> Skill | None:
        return self._s.skills.get(skill_id)

    async def update(self, skill: Skill) -> Skill:
        self._s.skills[skill.id] = skill
        return skill

    async def list_by_workspace(self, workspace_id: UUID) -> list[Skill]:
        return [s for s in self._s.skills.values() if s.workspace_id == workspace_id]

    async def get_by_slug(self, workspace_id: UUID, slug: str) -> Skill | None:
        return next(
            (
                s
                for s in self._s.skills.values()
                if s.workspace_id == workspace_id and s.slug == slug
            ),
            None,
        )

    async def list_by_ids(self, skill_ids: list[UUID]) -> list[Skill]:
        wanted = set(skill_ids)
        return [s for s in self._s.skills.values() if s.id in wanted]


class FakeUnitOfWork(UnitOfWork):
    """A UoW backed by an in-memory store. Only the repos the Sprint-2 use cases need."""

    def __init__(self, store: _Store) -> None:
        self._store = store

    async def __aenter__(self) -> FakeUnitOfWork:
        s = self._store
        self.workspaces = _FakeWorkspaceRepo(s)  # type: ignore[assignment]
        self.projects = _FakeProjectRepo(s)  # type: ignore[assignment]
        self.roles = _FakeRoleRepo(s)  # type: ignore[assignment]
        self.seat_grants = _FakeSeatGrantRepo(s)  # type: ignore[assignment]
        self.mariuses = _FakeMariusRepo(s)  # type: ignore[assignment]
        self.skills = _FakeSkillRepo(s)  # type: ignore[assignment]
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        return None  # repos already wrote through to the shared store

    async def rollback(self) -> None:
        return None


class FakeUowFactory:
    """Callable that hands out `FakeUnitOfWork`s over one shared store (introspect `.store`)."""

    def __init__(self) -> None:
        self.store = _Store()

    def __call__(self) -> FakeUnitOfWork:
        return FakeUnitOfWork(self.store)


class FakeLivenessProbe(LivenessProbe):
    """Scripted probe: a constant answer, or a list consumed one per call (default miss)."""

    def __init__(self, answers: bool | list[bool] = False) -> None:
        self._answers = answers
        self.calls = 0

    async def probe(self, marius: Marius) -> bool:
        self.calls += 1
        if isinstance(self._answers, bool):
            return self._answers
        idx = min(self.calls - 1, len(self._answers) - 1)
        return self._answers[idx]
