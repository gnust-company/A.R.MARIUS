"""Workspace & Project use cases."""

from __future__ import annotations

import re
from collections.abc import Sequence
from uuid import UUID

from armarius.application.use_cases.skills import SkillService
from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.user import User
from armarius.domain.entities.workspace import Project, Workspace
from armarius.shared.clock import utcnow


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
        # Ship the built-in Skill Shop entries so the workspace is ready. A project is
        # NOT auto-created — the patron commissions the first project explicitly (the
        # board's empty state guides them). `ensure_default_project` stays as a lazy
        # safety net for the agent-invitation flow only.
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

    async def rename_workspace(self, workspace_id: UUID, name: str) -> Workspace:
        """Rename a workspace and re-derive its slug from the new name."""
        async with self._uow() as uow:
            ws = await uow.workspaces.get(workspace_id)
            if ws is None:
                raise LookupError("workspace not found")
            ws.name = name
            ws.slug = _slugify(name)
            ws.updated_at = utcnow()
            updated = await uow.workspaces.update(ws)
            await uow.commit()
            return updated

    async def delete_workspace(self, workspace_id: UUID, *, owner_user_id: str) -> None:
        """Delete a workspace and all its contents. Refuses to delete the owner's only
        workspace so the patron is never left with nowhere to land."""
        async with self._uow() as uow:
            ws = await uow.workspaces.get(workspace_id)
            if ws is None:
                raise LookupError("workspace not found")
            # Fast path: reject deleting the only workspace up front (friendly error, no
            # write). This check alone is racy — two concurrent deletes can both read len==2
            # and proceed (issue #27 TOCTOU) — so we re-verify AFTER the delete below.
            owned = await uow.workspaces.list_by_owner(owner_user_id)
            if len(owned) <= 1:
                raise ValueError(
                    "You can't delete your only workspace — create another one first."
                )
            await uow.workspaces.remove(workspace_id)
            # Re-read inside the same transaction: if the delete just emptied the owner's
            # last workspace (a concurrent delete slipped past the pre-check), raise so the
            # UoW rolls back on __aexit__ and undoes the delete. This closes the race on
            # SQLite (writes serialize) and narrows it sharply on Postgres; a fully airtight
            # Postgres fix would take SELECT ... FOR UPDATE, deferred until PG is in prod.
            remaining = await uow.workspaces.list_by_owner(owner_user_id)
            if not remaining:
                raise ValueError(
                    "You can't delete your only workspace — create another one first."
                )
            await uow.commit()

    async def ensure_personal_workspace(self, user: User) -> Workspace:
        """Create a user's personal workspace for a newly registered user.

        Named simply "Personal" (not "{name}'s Workspace"). Seeds the built-in Skill
        Shop entries so the workspace is ready; no project is auto-created — new users
        start empty and commission their first project. Idempotent: if the user already
        owns a workspace, returns the first one.
        """
        async with self._uow() as uow:
            owned = await uow.workspaces.list_by_owner(str(user.id))
            if owned:
                return owned[0]

            ws = Workspace(
                name="Personal",
                slug="personal",
                owner_user_id=str(user.id),
            )
            ws = await uow.workspaces.add(ws)
            await uow.commit()

        # Seed the built-in Skill Shop entries for the new workspace.
        await self._skills.seed_builtins(ws.id)
        return ws

    async def ensure_default_project(self, workspace_id: UUID) -> Project:
        """Lazily create the default "General" project for a workspace if it has none.

        Safety net for the agent-invitation flow (an invitation names a real project),
        not run on workspace creation — new workspaces start empty by design.
        """
        async with self._uow() as uow:
            existing = await uow.projects.list_by_workspace(workspace_id)
            if existing:
                return existing[0]
            project = Project(
                workspace_id=workspace_id,
                name="General",
                slug="general",
                description=None,
            )
            created = await uow.projects.add(project)
            await uow.commit()
            return created

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
