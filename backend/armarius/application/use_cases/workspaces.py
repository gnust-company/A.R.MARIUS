"""Workspace & Project use cases."""

from __future__ import annotations

import re
from collections.abc import Sequence
from uuid import UUID

from armarius.application.use_cases.skills import SkillService
from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.user import User
from armarius.domain.entities.workspace import Project, Workspace


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "untitled"


class WorkspaceService:
    def __init__(
        self, uow_factory: UowFactory, skills: SkillService | None = None
    ) -> None:
        self._uow = uow_factory
        self._skills = skills or SkillService(uow_factory)

    async def create_workspace(
        self, name: str, *, owner_user_id: str | None = None
    ) -> Workspace:
        async with self._uow() as uow:
            ws = Workspace(name=name, slug=_slugify(name), owner_user_id=owner_user_id)
            created = await uow.workspaces.add(ws)
            await uow.commit()
        # Every workspace ships with the built-in Skill Shop entries.
        await self._skills.seed_builtins(created.id)
        return created

    async def list_workspaces(self, owner_user_id: str | None = None) -> Sequence[Workspace]:
        """List workspaces. Scoped to the owner when given; all when None (admin/demo)."""
        async with self._uow() as uow:
            if owner_user_id is None:
                return await uow.workspaces.list()
            return await uow.workspaces.list_by_owner(owner_user_id)

    async def get_workspace(self, workspace_id: UUID) -> Workspace | None:
        async with self._uow() as uow:
            return await uow.workspaces.get(workspace_id)

    async def ensure_personal_workspace(self, user: User) -> Workspace:
        """Create a personal workspace + starter project for a newly registered user.

        Idempotent: if the user already owns a workspace, returns the first one.
        """
        async with self._uow() as uow:
            owned = await uow.workspaces.list_by_owner(str(user.id))
            if owned:
                return owned[0]

            ws = Workspace(
                name=f"{user.full_name}'s Workspace",
                slug=_slugify(f"{user.username}-workspace"),
                owner_user_id=str(user.id),
            )
            ws = await uow.workspaces.add(ws)

            # Starter empty project so the Board has somewhere to land.
            starter = Project(
                workspace_id=ws.id,
                name="Getting Started",
                slug="getting-started",
                description="Your first project. Commission tasks and invite Marius agents here.",
            )
            await uow.projects.add(starter)
            await uow.commit()

        # Seed the built-in Skill Shop entries for the new personal workspace.
        await self._skills.seed_builtins(ws.id)
        return ws

    async def create_project(
        self, workspace_id: UUID, name: str, description: str | None = None
    ) -> Project:
        async with self._uow() as uow:
            if await uow.workspaces.get(workspace_id) is None:
                raise LookupError("workspace not found")
            project = Project(
                workspace_id=workspace_id,
                name=name,
                slug=_slugify(name),
                description=description,
            )
            created = await uow.projects.add(project)
            await uow.commit()
            return created

    async def list_projects(self, workspace_id: UUID) -> Sequence[Project]:
        async with self._uow() as uow:
            return await uow.projects.list_by_workspace(workspace_id)
