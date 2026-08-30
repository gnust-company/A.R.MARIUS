"""Run query use cases — read the durable trace (§8.1)."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.run import Run, RunEvent


class RunQueryService:
    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow = uow_factory

    async def get(self, run_id: UUID) -> Run | None:
        async with self._uow() as uow:
            return await uow.runs.get(run_id)

    async def list_by_task(self, task_id: UUID) -> Sequence[Run]:
        async with self._uow() as uow:
            return await uow.runs.list_by_task(task_id)

    async def list_by_marius(self, marius_id: UUID) -> Sequence[Run]:
        """Every run the system dispatched to this agent, newest first — the raw material
        for the agent-detail activity feed (the system↔agent interaction log)."""
        async with self._uow() as uow:
            return await uow.runs.list_by_marius(marius_id)

    async def events(
        self,
        run_id: UUID,
        *,
        types: Sequence[str] | None = None,
        after_seq: int | None = None,
        limit: int | None = None,
    ) -> Sequence[RunEvent]:
        """The durable log of one run, narrowed the three ways a reader narrows it (FR-052)."""
        async with self._uow() as uow:
            return await uow.run_events.list_by_run(
                run_id, types=types, after_seq=after_seq, limit=limit
            )

    async def full_text(self, run_id: UUID, seq: int) -> tuple[str, str, int] | None:
        """The whole of what one event only carries the opening of (FR-049)."""
        async with self._uow() as uow:
            return await uow.run_events.full_text(run_id, seq)
