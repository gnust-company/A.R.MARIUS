"""Workspace & Project use cases."""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from uuid import UUID

from armarius.application.use_cases.skills import SkillService
from armarius.application.use_cases.types import UowFactory
from armarius.application.use_cases.workspace_agent import WorkspaceAgentService
from armarius.domain.entities.user import User
from armarius.domain.entities.workspace import Project, Workspace
from armarius.shared.clock import utcnow
from armarius.shared.errors import BadRequest, NotFound

logger = logging.getLogger(__name__)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "untitled"


class WorkspaceService:
    def __init__(
        self,
        uow_factory: UowFactory,
        skills: SkillService | None = None,
        workspace_agent: WorkspaceAgentService | None = None,
    ) -> None:
        self._uow = uow_factory
        self._skills = skills or SkillService(uow_factory)
        self._workspace_agent = workspace_agent or WorkspaceAgentService(uow_factory)

    async def _settle_host(self, workspace_id: UUID) -> None:
        """Give this workspace its host, and never let that be why creating one failed.

        Every new workspace gets one (FR-110): the host is what someone talks to before there
        is anything else here, and until now nothing created it, so agent-mode project setup
        was dead for every account ever made.

        Swallowed on failure, and this is the one place that is right (FR-113). The workspace
        is already committed by the time this runs; raising here would report failure for
        something that succeeded, and the caller would have no idea which half went wrong. A
        workspace the user was told did not exist is not repairable at all.

        What the swallow leaves behind, said plainly: a workspace with no host, and **nothing
        retries on a schedule**. `provide_host` is idempotent so any later call fixes it, but
        today the only later callers are this line on the next workspace and the backfill
        migration — so a failure here means one workspace whose owner cannot use agent-mode
        project setup, and a logged exception is the only thing that says so.
        """
        try:
            await self._workspace_agent.provide_host(workspace_id)
        except Exception:  # noqa: BLE001 - see the docstring: this must never be the reason
            logger.exception("could not give workspace %s a host", workspace_id)

    async def create_workspace(
        self, name: str, *, owner_user_id: str | None = None
    ) -> Workspace:
        async with self._uow() as uow:
            ws = Workspace(name=name, slug=_slugify(name), owner_user_id=owner_user_id)
            created = await uow.workspaces.add(ws)
            await uow.commit()
        # Ship the built-in Skill Shop entries so the workspace is ready. A project is
        # NOT auto-created anywhere — the patron commissions the first project explicitly
        # (the board's empty state guides them); inviting an agent no longer creates one
        # either (#49).
        await self._skills.seed_builtins(created.id)
        await self._settle_host(created.id)
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
                raise NotFound("workspace_not_found")
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
                raise NotFound("workspace_not_found")
            # Fast path: reject deleting the only workspace up front (friendly error, no
            # write). This check alone is racy — two concurrent deletes can both read len==2
            # and proceed (issue #27 TOCTOU) — so we re-verify AFTER the delete below.
            owned = await uow.workspaces.list_by_owner(owner_user_id)
            if len(owned) <= 1:
                raise BadRequest("last_workspace")
            await uow.workspaces.remove(workspace_id)
            # Re-read inside the same transaction: if the delete just emptied the owner's
            # last workspace (a concurrent delete slipped past the pre-check), raise so the
            # UoW rolls back on __aexit__ and undoes the delete. This closes the race on
            # SQLite (writes serialize) and narrows it sharply on Postgres; a fully airtight
            # Postgres fix would take SELECT ... FOR UPDATE, deferred until PG is in prod.
            remaining = await uow.workspaces.list_by_owner(owner_user_id)
            if not remaining:
                raise BadRequest("last_workspace")
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
        await self._settle_host(ws.id)
        return ws

    async def create_project(
        self, workspace_id: UUID, name: str, description: str | None = None
    ) -> Project:
        async with self._uow() as uow:
            if await uow.workspaces.get(workspace_id) is None:
                raise NotFound("workspace_not_found")
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
