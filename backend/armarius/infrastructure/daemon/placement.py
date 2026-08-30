"""Where the business layer's *placement* turns back into a workplace on a machine.

This module is the whole translation, and it is one file deep on purpose. Above it, a
placement is somewhere an agent works, open or closed; below it, a placement is one agent
CLI on one enrolled machine, and the attachment lives in `agent_workplace_bindings`
(data-model.md). Nothing between the two has to know both halves — which is what lets a
second kind of place arrive later without reopening a single use case (Constitution III).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from armarius.domain.entities.placement import (
    OptionSource,
    Placement,
    PlacementOption,
)
from armarius.domain.repositories.repositories import PlacementRepository
from armarius.infrastructure.daemon.models import (
    AgentWorkplaceBindingModel,
    MachineModel,
    WorkplaceModel,
)
from armarius.shared.clock import utcnow
from armarius.shared.config import settings
from armarius.shared.errors import Conflict

# Why the place an agent was put cannot take work. Codes, never sentences — the screen
# builds the sentence (Constitution VI + VII). This one is the module's own; the rest
# arrive already written on the workplace row (`cli_removed`, `link_unsupported`), and
# the two that need no knowledge of machines at all live in the domain beside `Placement`.
REASON_MACHINE_UNREACHABLE = "machine_unreachable"


class SqlPlacementRepository(PlacementRepository):
    """`workplaces` read as placements, `agent_workplace_bindings` written once."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._s = session
        self._clock = clock

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
            options=options_of(row),
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

    async def placed_at(self, marius_ids: Sequence[UUID]) -> Mapping[UUID, Placement]:
        """One query for the whole roster: where each agent sits, and whether it can work.

        Three things have to be true at once for an agent to have somewhere to work, and
        they fail independently: it was put somewhere at all, that CLI is still installed
        there, and the machine holding it is still beating. Every one of those failures
        comes back as the same verdict — *not ready* — because that is all the layer above
        is allowed to care about (FR-006, FR-006a). The reason rides along beside the
        verdict for the screen alone (FR-006c).

        The join is an outer one on `machines` on purpose. An inner join would silently
        drop an agent whose machine row went missing, and a dropped row reads to the caller
        as *never placed* — the one wrong answer that looks like a right one.
        """
        wanted = list(dict.fromkeys(marius_ids))
        if not wanted:
            return {}

        rows = (
            await self._s.execute(
                select(
                    AgentWorkplaceBindingModel.marius_id,
                    AgentWorkplaceBindingModel.workspace_id,
                    WorkplaceModel.id,
                    WorkplaceModel.ready,
                    WorkplaceModel.not_ready_reason,
                    MachineModel.last_heartbeat_at,
                )
                .join(
                    WorkplaceModel,
                    WorkplaceModel.id == AgentWorkplaceBindingModel.workplace_id,
                )
                .outerjoin(MachineModel, MachineModel.id == WorkplaceModel.machine_id)
                .where(AgentWorkplaceBindingModel.marius_id.in_(wanted))
            )
        ).all()

        cutoff = self._clock() - timedelta(
            seconds=settings.machine_unreachable_after_seconds
        )
        placed: dict[UUID, Placement] = {}
        for marius_id, workspace_id, placement_id, ready, reason, beat in rows:
            # A recorded reason wins over a quiet machine, and that order is deliberate.
            # `cli_removed` was written by a sweep that actually ran on that machine while
            # it was up, so it is a measured fact; the machine being quiet now is the
            # newer event but the vaguer one. Whoever reads this has to reinstall the CLI
            # either way, and telling them only that the machine is off would send them to
            # boot it and find nothing changed.
            if not ready:
                placed[marius_id] = Placement(
                    id=placement_id,
                    workspace_id=workspace_id,
                    ready=False,
                    not_ready_reason=reason,
                )
                continue
            alive = beat is not None and _at_least(beat) > cutoff
            placed[marius_id] = Placement(
                id=placement_id,
                workspace_id=workspace_id,
                ready=alive,
                not_ready_reason=None if alive else REASON_MACHINE_UNREACHABLE,
            )
        return placed


def _at_least(moment: datetime) -> datetime:
    """Timestamps read back from SQLite come home without a timezone; Postgres keeps one.

    Comparing the two raises rather than answering wrong, which is the good failure mode,
    but it fails in the watchdog rather than in a test — so the naive one is read as UTC
    here, which is the only thing it has ever meant on the way in.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment


def options_of(row: WorkplaceModel) -> tuple[PlacementOption, ...]:
    """What a person may choose for an agent put at this workplace (FR-007k, FR-017).

    Read straight out of what the daemon reported the CLI answered. **Nothing here is keyed
    on the CLI's name** — this function would return the same thing for a kind of tool that
    did not exist when it was written, which is the whole of FR-017's ban on deciding a
    tool's abilities from its name.

    Anything malformed is dropped rather than repaired. The column is written by a program on
    somebody else's machine, so it is data from outside; a half-understood entry offered to a
    person as a choice is worse than one that never appears, because they would pick it.
    """
    declared = row.capabilities or {}
    if not isinstance(declared, dict):
        return ()
    offered = declared.get("choices")
    if not isinstance(offered, list):
        return ()

    options: list[PlacementOption] = []
    for one in offered:
        if not isinstance(one, dict):
            continue
        key = one.get("key")
        if not isinstance(key, str) or not key:
            continue
        raw = one.get("values")
        values = tuple(v for v in raw if isinstance(v, str) and v) if isinstance(raw, list) else ()
        try:
            source = OptionSource(one.get("source"))
        except ValueError:
            # A source this build does not know is treated as the careful reading: values
            # are suggestions, and nothing is refused for being outside them. Guessing the
            # other way would refuse a legitimate value on the strength of a word we could
            # not read.
            source = OptionSource.EXAMPLES
        if not values:
            # A setting with nothing to pick from is not a setting anybody can pick.
            continue
        options.append(PlacementOption(key=key, values=values, source=source))
    return tuple(options)
