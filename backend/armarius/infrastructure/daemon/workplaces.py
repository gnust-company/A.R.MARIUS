"""What a machine offers, and the beat that says it is still there (FR-002, FR-004, FR-033).

A **workplace** is one agent CLI on one machine. The daemon sweeps its own machine and reports
the whole list every time; this module is what turns that report into rows. Two rules shape all
of it:

  * **Nothing is ever deleted.** An agent is bound to a workplace for life (FR-007), so a CLI
    that disappears from a machine turns its workplace *not ready* with a reason and keeps the
    row. Deleting it would break the binding of every agent that lived there, and the agent
    would go quiet with nothing to point at.
  * **A reason is a code, never a sentence.** The screen builds the sentence through i18n
    (Constitution VI + VII).

Infrastructure only, like everything else under `daemon/` (Constitution III). Nothing above the
adapter contract may learn that a machine, a workplace or a CLI exists; the layers above ask
one question — is this agent alive — and every not-ready branch here collapses into that same
single answer (FR-006a).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from armarius.infrastructure.daemon.enrollment import MachineIdentity
from armarius.infrastructure.daemon.models import (
    MachineModel,
    RunClaimModel,
    WorkplaceModel,
)
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.shared.clock import utcnow

# Why a workplace is not ready. Codes, never sentences. They do not overlap: a CLI that is
# gone from the machine says so even if the machine also cannot link, because *this CLI is
# not here* is the thing its operator can act on.
REASON_CLI_REMOVED = "cli_removed"
REASON_LINK_UNSUPPORTED = "link_unsupported"

# How many times a sync is retried when two of them collide on the unique index over
# (machine_id, cli_kind). One retry is enough by construction: after the loser rolls back, the
# row the winner inserted is there to be found, so the second pass updates instead of inserting.
_SYNC_ATTEMPTS = 2


@dataclass(frozen=True)
class ReportedWorkplace:
    """One CLI as the machine found it. Every field is what the daemon measured, not inferred."""

    cli_kind: str
    cli_version: str = ""
    protocol_family: str = ""
    capabilities: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SyncedWorkplace:
    """One workplace after the sync, as the machine is told about it."""

    id: UUID
    cli_kind: str
    ready: bool
    not_ready_reason: str | None
    # The machine's own readable name, carried here so a workplace can be told apart from the
    # same CLI on the person's other machine (FR-003).
    machine_name: str


@dataclass(frozen=True)
class OfferedWorkplace:
    """One workplace as the person choosing where to put an agent sees it."""

    id: UUID
    cli_kind: str
    machine_name: str


@dataclass(frozen=True)
class Heartbeat:
    """The answer to one beat."""

    pending_work: bool
    cancel: tuple[UUID, ...]


class DaemonWorkplaceService:
    """Owns `workplaces`, and the two columns of `machines` a live daemon keeps moving."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._clock = clock

    def _sessions(self) -> async_sessionmaker[AsyncSession]:
        # Resolved on use rather than in __init__, for the reason given in enrollment.py: the
        # container is built before the engine is necessarily pointed at its database.
        return self._sessionmaker or get_sessionmaker()

    async def sync(
        self,
        machine: MachineIdentity,
        *,
        reported: Sequence[ReportedWorkplace],
        symlink_capable: bool,
    ) -> list[SyncedWorkplace]:
        """Make the stored workplaces of one machine match what it just reported (FR-002).

        The daemon sends its whole list every time rather than a difference, so this is the one
        place that knows which CLIs left. A missing CLI is not a missing row.
        """
        for attempt in range(_SYNC_ATTEMPTS):
            try:
                return await self._sync_once(
                    machine, reported=reported, symlink_capable=symlink_capable
                )
            except IntegrityError:
                # Two syncs from the same machine raced and both tried to insert the same
                # cli_kind. The unique index refused one of them, which is exactly its job;
                # the loser starts again and finds the row this time.
                if attempt == _SYNC_ATTEMPTS - 1:
                    raise
        raise AssertionError("unreachable")  # pragma: no cover

    async def _sync_once(
        self,
        machine: MachineIdentity,
        *,
        reported: Sequence[ReportedWorkplace],
        symlink_capable: bool,
    ) -> list[SyncedWorkplace]:
        now = self._clock()
        async with self._sessions()() as session:
            try:
                found = await session.execute(
                    select(WorkplaceModel).where(
                        WorkplaceModel.machine_id == machine.machine_id,
                        WorkplaceModel.workspace_id == machine.workspace_id,
                    )
                )
                stored = {row.cli_kind: row for row in found.scalars()}

                machine_row = await session.get(MachineModel, machine.machine_id)
                if machine_row is not None:
                    machine_row.symlink_capable = symlink_capable
                    machine_row.updated_at = now
                machine_name = machine_row.display_name if machine_row else ""

                # A machine that cannot link the pieces of a CLI's home that have to be linked
                # offers no usable workplace at all — session state would be silently lost
                # instead of kept (research.md §5). It is a property of the machine, so it
                # lands on every workplace on it.
                blocked = None if symlink_capable else REASON_LINK_UNSUPPORTED

                for one in reported:
                    row = stored.pop(one.cli_kind, None)
                    if row is None:
                        row = WorkplaceModel(
                            id=uuid4(),
                            workspace_id=machine.workspace_id,
                            machine_id=machine.machine_id,
                            cli_kind=one.cli_kind,
                            created_at=now,
                        )
                        session.add(row)
                    row.cli_version = one.cli_version
                    row.protocol_family = one.protocol_family
                    row.capabilities = one.capabilities
                    row.ready = blocked is None
                    row.not_ready_reason = blocked
                    row.updated_at = now

                # Whatever is left in `stored` was registered before and is not on the machine
                # any more. It stops being offered work and says why; it does not stop
                # existing (FR-033).
                for gone in stored.values():
                    gone.ready = False
                    gone.not_ready_reason = REASON_CLI_REMOVED
                    gone.updated_at = now

                await session.commit()
            except Exception:
                await session.rollback()
                raise

            synced = [
                SyncedWorkplace(
                    id=row.id,
                    cli_kind=row.cli_kind,
                    ready=row.ready,
                    not_ready_reason=row.not_ready_reason,
                    machine_name=machine_name,
                )
                for row in await self._workplaces_of(session, machine)
            ]
        return synced

    async def heartbeat(
        self,
        machine: MachineIdentity,
        *,
        free_slots: int,
        running: Sequence[UUID],
    ) -> Heartbeat:
        """Record that this machine is still there, and answer what it should do next (FR-004).

        What is written here is the *machine's* liveness and nothing else. A beat proves the
        daemon can be reached; it says nothing about whether an agent CLI on that machine can
        run, and treating it as if it did would leave a machine whose CLI was uninstalled
        looking alive forever (FR-055b).
        """
        now = self._clock()
        async with self._sessions()() as session:
            try:
                await session.execute(
                    update(MachineModel)
                    .where(
                        MachineModel.id == machine.machine_id,
                        MachineModel.workspace_id == machine.workspace_id,
                    )
                    .values(last_heartbeat_at=now)
                )

                mine = {row.id for row in await self._workplaces_of(session, machine)}
                pending = False
                if free_slots > 0 and mine:
                    # Telling a full machine that work is waiting is noise: it cannot take it,
                    # and the ask it prompts comes back empty. The number it just reported is
                    # the freshest reading there is, and it is used here rather than stored —
                    # a stored copy would be wrong from the next beat onwards.
                    waiting = await session.execute(
                        select(RunClaimModel.run_id)
                        .where(
                            RunClaimModel.workspace_id == machine.workspace_id,
                            RunClaimModel.workplace_id.in_(mine),
                            RunClaimModel.machine_id.is_(None),
                        )
                        .limit(1)
                    )
                    pending = waiting.first() is not None

                cancel: tuple[UUID, ...] = ()
                if running:
                    held = await session.execute(
                        select(RunClaimModel.run_id).where(
                            RunClaimModel.workspace_id == machine.workspace_id,
                            RunClaimModel.machine_id == machine.machine_id,
                            RunClaimModel.run_id.in_(list(running)),
                        )
                    )
                    still_ours = set(held.scalars())
                    # Order preserved from what the machine reported, so the same situation
                    # produces the same answer twice.
                    cancel = tuple(
                        run_id for run_id in running if run_id not in still_ours
                    )

                await session.commit()
            except Exception:
                await session.rollback()
                raise
        return Heartbeat(pending_work=pending, cancel=cancel)

    async def list_ready(self, workspace_id: UUID) -> list[OfferedWorkplace]:
        """Every workplace in one workspace that can take an agent right now (FR-007f).

        Only the ready ones. Offering a workplace whose CLI has been uninstalled would let
        somebody create an agent that is offline from its first second — and because the
        attachment can never be changed (FR-007), the only way out of that would be to
        delete the agent and start again.

        The machine's name rides along because a person picking between `claude_code` on
        two of their own machines has nothing else to tell them apart (FR-003).
        """
        async with self._sessions()() as session:
            found = await session.execute(
                select(WorkplaceModel, MachineModel.display_name)
                .join(MachineModel, MachineModel.id == WorkplaceModel.machine_id)
                .where(
                    WorkplaceModel.workspace_id == workspace_id,
                    WorkplaceModel.ready.is_(True),
                )
                .order_by(MachineModel.display_name, WorkplaceModel.cli_kind)
            )
            return [
                OfferedWorkplace(
                    id=row.id, cli_kind=row.cli_kind, machine_name=machine_name or ""
                )
                for row, machine_name in found.all()
            ]

    async def _workplaces_of(
        self, session: AsyncSession, machine: MachineIdentity
    ) -> list[WorkplaceModel]:
        """Every workplace of one machine, in a stable order.

        Ordered by `cli_kind` so two syncs that found the same CLIs answer identically. A list
        whose order moves looks, to whatever reads it next, like a machine whose CLIs keep
        changing.
        """
        rows = await session.execute(
            select(WorkplaceModel)
            .where(
                WorkplaceModel.machine_id == machine.machine_id,
                WorkplaceModel.workspace_id == machine.workspace_id,
            )
            .order_by(WorkplaceModel.cli_kind)
        )
        return list(rows.scalars())
