"""Marius (agent) use cases — register an agent and read the directory (§3.1)."""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from uuid import UUID

from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.marius import Marius


class MariusService:
    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow = uow_factory

    async def register(
        self,
        *,
        workspace_id: UUID,
        name: str,
        role: str,
        skills: list[str],
        adapter_type: str,
        adapter_config: dict,
        owner_user_id: str | None = None,
    ) -> Marius:
        async with self._uow() as uow:
            if await uow.workspaces.get(workspace_id) is None:
                raise LookupError("workspace not found")
            marius = Marius(
                workspace_id=workspace_id,
                name=name,
                role=role,
                skills=skills,
                adapter_type=adapter_type,
                adapter_config=adapter_config,
                owner_user_id=owner_user_id,
                agent_token=f"arm_{secrets.token_urlsafe(32)}",
            )
            created = await uow.mariuses.add(marius)
            await uow.commit()
            return created

    async def get(self, marius_id: UUID) -> Marius | None:
        async with self._uow() as uow:
            return await uow.mariuses.get(marius_id)

    async def list_directory(self, workspace_id: UUID) -> Sequence[Marius]:
        async with self._uow() as uow:
            return await uow.mariuses.list_by_workspace(workspace_id)
