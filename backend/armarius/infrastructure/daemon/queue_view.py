"""Where a task's place in the queue turns back into machines and workplaces.

The port above this file asks two neutral questions — *is every slot full, and by what*,
and *when was this work last taken*. Both are answered here from `run_claims`, because both
are facts about the machines the work would run on, and no layer above may learn that
(Constitution III).

The full-slots answer is deliberately narrow. A task counts as waiting for room only when
it has work sitting unclaimed **and** the place that work belongs to has no free slot. A
task with no waiting work is not waiting for room; a task whose place has room is not
waiting either, it is simply about to be picked up. Answering *full* in either case would
put a drive with no clock on a task nothing is actually blocking, and the safety net would
stop watching it (FR-008a, FR-008e).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from armarius.application.ports.queue_view import QueuePosition, QueueView
from armarius.domain.entities.run import RunStatus
from armarius.infrastructure.daemon.models import (
    MachineModel,
    RunClaimModel,
    WorkplaceModel,
)
from armarius.infrastructure.database.models import RunModel
from armarius.shared.clock import as_utc, utcnow


class SqlQueueView(QueueView):
    """`run_claims` read as a queue position."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._s = session
        self._clock = clock

    async def position_of(self, task_id: UUID) -> QueuePosition:
        now = self._clock()
        mine = (
            await self._s.execute(
                select(
                    RunClaimModel.run_id,
                    RunClaimModel.machine_id,
                    RunClaimModel.claimed_at,
                    WorkplaceModel.machine_id.label("host_id"),
                    RunModel.status,
                )
                .join(RunModel, RunModel.id == RunClaimModel.run_id)
                .join(WorkplaceModel, WorkplaceModel.id == RunClaimModel.workplace_id)
                .where(RunModel.task_id == task_id)
            )
        ).all()
        if not mine:
            return QueuePosition()

        marks = [stamp for row in mine if (stamp := as_utc(row.claimed_at)) is not None]
        last_taken = max(marks) if marks else None

        # The hosts this task still has work waiting on. A run already taken is not waiting
        # for a slot — it is in one.
        waiting_on = {
            row.host_id
            for row in mine
            if row.machine_id is None and row.status == RunStatus.QUEUED.value
        }
        if not waiting_on:
            return QueuePosition(last_taken_at=last_taken)

        filling = await self._runs_filling(waiting_on, now)
        return QueuePosition(runs_filling_every_slot=filling, last_taken_at=last_taken)

    async def _runs_filling(self, hosts: set[UUID], now: datetime) -> tuple[str, ...]:
        """The runs holding the slots, but only where there is genuinely no room left.

        A hold that has run out is not holding anything: the sweep is about to give it back,
        and counting it would tell a task it is blocked by a run that no longer exists.
        """
        rows = (
            await self._s.execute(
                select(
                    MachineModel.id,
                    MachineModel.max_concurrent,
                    RunClaimModel.run_id,
                )
                .join(WorkplaceModel, WorkplaceModel.machine_id == MachineModel.id)
                .join(RunClaimModel, RunClaimModel.workplace_id == WorkplaceModel.id)
                .join(RunModel, RunModel.id == RunClaimModel.run_id)
                .where(
                    MachineModel.id.in_(hosts),
                    RunClaimModel.machine_id.is_not(None),
                    RunModel.status.in_((RunStatus.QUEUED.value, RunStatus.RUNNING.value)),
                    # A hold with no deadline is a run that has started; the countdown ends
                    # at start-up, and what watches it from then on is the silence
                    # threshold. A hold whose deadline has passed is on its way back to the
                    # shelf and is holding nothing.
                    or_(
                        RunClaimModel.claim_expires_at.is_(None),
                        RunClaimModel.claim_expires_at > now,
                    ),
                )
            )
        ).all()

        ceiling: dict[UUID, int] = {}
        held: dict[UUID, list[UUID]] = {}
        for machine_id, max_concurrent, run_id in rows:
            ceiling[machine_id] = max_concurrent
            held.setdefault(machine_id, []).append(run_id)

        filling: list[str] = []
        for machine_id, runs in held.items():
            if len(runs) >= ceiling.get(machine_id, 0):
                filling += [str(run_id) for run_id in runs]
        # Sorted so the same jam reads the same way twice; the drive's `ref` is compared
        # against itself on every sweep.
        return tuple(sorted(filling))
