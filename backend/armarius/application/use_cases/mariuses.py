"""Marius (agent) use cases — register an agent and read the directory (§3.1)."""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from uuid import UUID

from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.marius import Marius
from armarius.shared.clock import utcnow


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
        skill_ids: list[str] | None = None,
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
                skill_ids=skill_ids or [],
                adapter_type=adapter_type,
                adapter_config=adapter_config,
                owner_user_id=owner_user_id,
                agent_token=f"arm_{secrets.token_urlsafe(32)}",
            )
            created = await uow.mariuses.add(marius)
            await uow.commit()
            return created

    async def update(
        self,
        marius_id: UUID,
        *,
        name: str | None = None,
        role: str | None = None,
        skills: list[str] | None = None,
        skill_ids: list[str] | None = None,
        adapter_type: str | None = None,
        adapter_config: dict | None = None,
    ) -> Marius:
        """Edit an existing Marius (partial). Token and liveness are untouched."""
        async with self._uow() as uow:
            marius = await uow.mariuses.get(marius_id)
            if marius is None:
                raise LookupError("marius not found")
            if name is not None:
                marius.name = name
            if role is not None:
                marius.role = role
            if skills is not None:
                marius.skills = skills
            if skill_ids is not None:
                marius.skill_ids = skill_ids
            if adapter_type is not None:
                marius.adapter_type = adapter_type
            if adapter_config is not None:
                marius.adapter_config = adapter_config
            marius.updated_at = utcnow()
            updated = await uow.mariuses.update(marius)
            await uow.commit()
            return updated

    async def get(self, marius_id: UUID) -> Marius | None:
        async with self._uow() as uow:
            return await uow.mariuses.get(marius_id)

    async def list_directory(self, workspace_id: UUID) -> Sequence[Marius]:
        async with self._uow() as uow:
            return await uow.mariuses.list_by_workspace(workspace_id)
