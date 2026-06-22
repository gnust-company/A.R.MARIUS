"""Workspace & Project use cases."""

from __future__ import annotations

import re
from collections.abc import Sequence
from uuid import UUID

from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.workspace import Project, Workspace


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "untitled"


class WorkspaceService:
    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow = uow_factory

    async def create_workspace(self, name: str) -> Workspace:
        async with self._uow() as uow:
            ws = Workspace(name=name, slug=_slugify(name))
            created = await uow.workspaces.add(ws)
            await uow.commit()
            return created

    async def list_workspaces(self) -> Sequence[Workspace]:
        async with self._uow() as uow:
            return await uow.workspaces.list()

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
