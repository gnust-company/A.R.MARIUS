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

    async def events(self, run_id: UUID) -> Sequence[RunEvent]:
        async with self._uow() as uow:
            return await uow.run_events.list_by_run(run_id)
