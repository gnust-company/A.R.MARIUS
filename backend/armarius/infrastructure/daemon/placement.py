"""Where the business layer's *placement* turns back into a workplace on a machine.

This module is the whole translation, and it is one file deep on purpose. Above it, a
placement is somewhere an agent works, open or closed; below it, a placement is one agent
CLI on one enrolled machine, and the attachment lives in `agent_workplace_bindings`
(data-model.md). Nothing between the two has to know both halves — which is what lets a
second kind of place arrive later without reopening a single use case (Constitution III).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from armarius.domain.entities.placement import Placement
from armarius.domain.repositories.repositories import PlacementRepository
from armarius.infrastructure.daemon.models import (
    AgentWorkplaceBindingModel,
    WorkplaceModel,
)
from armarius.shared.clock import utcnow
from armarius.shared.errors import Conflict


class SqlPlacementRepository(PlacementRepository):
    """`workplaces` read as placements, `agent_workplace_bindings` written once."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get(self, workspace_id: UUID, placement_id: UUID) -> Placement | None:
        row = (
            await self._s.execute(
                select(WorkplaceModel).where(
                    WorkplaceModel.id == placement_id,
                    # Both halves of the key, always. Matching on the id alone would answer
                    # for someone else's workplace, and answering at all is the leak — the
                    # caller learns the id is real (Constitution I).
                    WorkplaceModel.workspace_id == workspace_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return Placement(
            id=row.id,
            workspace_id=row.workspace_id,
            ready=row.ready,
            not_ready_reason=row.not_ready_reason,
        )

    async def attach(
        self, marius_id: UUID, workspace_id: UUID, placement_id: UUID
    ) -> None:
        # Read-then-write, and it is safe here for a reason worth stating: the agent this
        # row is for was created moments ago in this same transaction, so no second caller
        # has its id yet. The primary key on `marius_id` is the real guarantee — this check
        # exists to turn what would be a 500 into the refusal it actually is.
        existing = await self._s.get(AgentWorkplaceBindingModel, marius_id)
        if existing is not None:
            raise Conflict("agent_already_placed")
        self._s.add(
            AgentWorkplaceBindingModel(
                marius_id=marius_id,
                workspace_id=workspace_id,
                workplace_id=placement_id,
                created_at=utcnow(),
            )
        )
        await self._s.flush()
