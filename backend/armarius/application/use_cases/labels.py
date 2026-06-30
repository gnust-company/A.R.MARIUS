"""Label use cases — workspace-scoped task tags (API_CONTRACT §5.4)."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.label import Label
from armarius.shared.clock import utcnow


class LabelService:
    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow = uow_factory

    async def list_labels(self, workspace_id: UUID) -> Sequence[Label]:
        async with self._uow() as uow:
            return await uow.labels.list_by_workspace(workspace_id)

    async def create(self, workspace_id: UUID, name: str, color: str = "") -> Label:
        async with self._uow() as uow:
            if await uow.workspaces.get(workspace_id) is None:
                raise LookupError("workspace not found")
            label = Label(
                workspace_id=workspace_id,
                name=name,
                color=color,
                created_at=utcnow(),
            )
            created = await uow.labels.add(label)
            await uow.commit()
            return created
