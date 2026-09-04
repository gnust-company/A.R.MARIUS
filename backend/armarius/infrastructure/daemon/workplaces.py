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
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from armarius.domain.entities.placement import PlacementOption
from armarius.infrastructure.daemon.enrollment import MachineIdentity
from armarius.infrastructure.daemon.models import (
    AgentWorkplaceBindingModel,
    MachineModel,
    RunClaimModel,
    WorkplaceModel,
)
from armarius.infrastructure.daemon.placement import options_of
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import MariusModel
from armarius.shared.clock import as_utc, utcnow
from armarius.shared.config import settings
from armarius.shared.errors import BadRequest

# Why a workplace is not ready. Codes, never sentences. They do not overlap: a CLI that is
# gone from the machine says so even if the machine also cannot link, because *this CLI is
# not here* is the thing its operator can act on.
REASON_CLI_REMOVED = "cli_removed"
REASON_LINK_UNSUPPORTED = "link_unsupported"
#: The daemon on that machine was stopped, and said so on its way out (FR-005). Distinct from
#: `cli_removed` although both arrive as the same thing — a workplace the machine stopped
#: reporting — because the two send the person reading the screen to do different work: one to
#: reinstall a CLI, the other to start the daemon again. Without this code a routine restart
#: told every operator their agent CLI had been uninstalled.
REASON_DAEMON_STOPPED = "daemon_stopped"

# The range a machine's ceiling may be set to (FR-008).
#
# One at the bottom rather than zero: zero is *stop giving this machine work*, which is a
# different decision with a different word for it, and a ceiling of zero would look on the
# screen like a number somebody mistyped. The top is a guard rather than a measurement —
# nothing here knows how much a given laptop can stand — but an unbounded box invites a
# number that turns one person's own machine into the thing that broke, and every real
# answer is far below it.
MIN_CEILING = 1
MAX_CEILING = 64

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
    # What may be set on an agent put here (FR-007k), read from what the CLI answered when
    # the daemon asked it — never from the kind of CLI it is (FR-017).
    options: tuple[PlacementOption, ...] = ()


@dataclass(frozen=True)
class Heartbeat:
    """The answer to one beat."""

    pending_work: bool
    cancel: tuple[UUID, ...]


@dataclass(frozen=True)
class ResidentAgent:
    """One agent living at a workplace. Name included because that is what a person reads."""

    id: UUID
    name: str


@dataclass(frozen=True)
class MachineWorkplace:
    """One agent CLI on one machine, as the person who linked that machine sees it."""

    id: UUID
    cli_kind: str
    cli_version: str
    ready: bool
    # A code, never a sentence: the same fact is read on screen in the patron's own
    # language and written into records in English (Constitution VI, Constitution VII).
    not_ready_reason: str | None
    agents: tuple[ResidentAgent, ...] = ()


@dataclass(frozen=True)
class LinkedMachine:
    """One machine, everything it can run, and everyone who lives on it."""

    id: UUID
    display_name: str
    platform: str
    daemon_version: str
    last_heartbeat_at: datetime | None
    reachable: bool
    workplaces: list[MachineWorkplace]
    # How many runs this machine is allowed to hold at once (FR-008). Read here rather than
    # only enforced in the claim, because a number a person cannot see is a number they
    # cannot be expected to have chosen — and FR-008 says they choose it.
    max_concurrent: int = 1


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
        stopping: bool = False,
    ) -> list[SyncedWorkplace]:
        """Make the stored workplaces of one machine match what it just reported (FR-002).

        The daemon sends its whole list every time rather than a difference, so this is the one
        place that knows which CLIs left. A missing CLI is not a missing row.

        ``stopping`` is the daemon saying this is the last thing it will send before it exits
        (FR-005). It changes no rows that the ordinary path would not change; it changes only
        the *reason* written on them, and that reason is the sentence an operator acts on.
        """
        for attempt in range(_SYNC_ATTEMPTS):
            try:
                return await self._sync_once(
                    machine,
                    reported=reported,
                    symlink_capable=symlink_capable,
                    stopping=stopping,
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
        stopping: bool = False,
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
                    # A machine that is talking to us is a machine that is there. Reachability
                    # is not the property of one route — it is what any authenticated call
                    # from that machine demonstrates, and reading it off the beat alone would
                    # leave a daemon that is mid-sweep, or whose beat loop has not started
                    # yet, looking dead while it is plainly in the middle of a sentence.
                    #
                    # This is still not a liveness signal for any *agent* on the machine, and
                    # that line is the one FR-055b draws. Reaching the machine says nothing
                    # about whether a CLI on it can run — which is exactly the question the
                    # rest of this call answers, separately, from what the machine reported.
                    machine_row.last_heartbeat_at = now
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
                #
                # Why it stopped being reported is the machine's to say, and it says it by
                # calling this door one last time as it exits (FR-005). Guessing `cli_removed`
                # for a daemon that was simply stopped is not a small inaccuracy: it is the
                # difference between "start the daemon again" and "go and reinstall gemini",
                # and only one of those makes the workplace come back.
                closed = REASON_DAEMON_STOPPED if stopping else REASON_CLI_REMOVED
                for gone in stored.values():
                    gone.ready = False
                    gone.not_ready_reason = closed
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
                    id=row.id,
                    cli_kind=row.cli_kind,
                    machine_name=machine_name or "",
                    options=options_of(row),
                )
                for row, machine_name in found.all()
            ]

    async def list_machines(self, workspace_id: UUID) -> list[LinkedMachine]:
        """Every machine here, what it can run, and who lives on it (FR-003, FR-007a, FR-033).

        **The same reachability rule the liveness verdict uses**, not a second one written
        for the screen. Two rules would eventually disagree, and the shape of the
        disagreement is the worst one available: the machines screen saying a machine is off
        while the agent on it still counts as online, or the reverse. A person reading two
        contradictory answers trusts neither, which is worse than one answer being wrong.

        A CLI that was uninstalled keeps its row and turns *not ready* rather than
        disappearing — that is what makes it visible at all, and it is the whole of FR-033.
        The agents attached to it stay attached, because that attachment is for life
        (FR-007): the screen has to be able to show *who is stranded here*, which is the
        question the person is actually asking when a workplace goes red.
        """
        async with self._sessions()() as session:
            machines = list(
                (
                    await session.execute(
                        select(MachineModel)
                        .where(MachineModel.workspace_id == workspace_id)
                        .order_by(MachineModel.display_name, MachineModel.id)
                    )
                ).scalars()
            )
            if not machines:
                return []

            places = list(
                (
                    await session.execute(
                        select(WorkplaceModel)
                        .where(WorkplaceModel.workspace_id == workspace_id)
                        .order_by(WorkplaceModel.cli_kind)
                    )
                ).scalars()
            )
            # Every agent on every workplace in one read. Asked per workplace this would be
            # one query per CLI per machine, and the answer is a single small join.
            residents = (
                await session.execute(
                    select(
                        AgentWorkplaceBindingModel.workplace_id,
                        MariusModel.id,
                        MariusModel.name,
                    )
                    .join(
                        MariusModel,
                        MariusModel.id == AgentWorkplaceBindingModel.marius_id,
                    )
                    .where(AgentWorkplaceBindingModel.workspace_id == workspace_id)
                    .order_by(MariusModel.name)
                )
            ).all()

        living: dict[UUID, list[ResidentAgent]] = {}
        for workplace_id, marius_id, name in residents:
            living.setdefault(workplace_id, []).append(
                ResidentAgent(id=marius_id, name=name or "")
            )

        cutoff = self._clock() - timedelta(
            seconds=settings.machine_unreachable_after_seconds
        )
        by_machine: dict[UUID, list[WorkplaceModel]] = {}
        for place in places:
            by_machine.setdefault(place.machine_id, []).append(place)

        return [
            LinkedMachine(
                id=machine.id,
                display_name=machine.display_name or "",
                platform=machine.platform or "",
                daemon_version=machine.daemon_version or "",
                # Through `as_utc` for the same reason the hold deadline is: a timestamp
                # column comes back tz-aware from one engine and naive from another, and a
                # naive one serialises without an offset. A browser reads an offset-less
                # ISO string as **local time**, so the same beat would be shown hours out
                # on any machine that is not on UTC — wrong, and wrong quietly.
                last_heartbeat_at=as_utc(machine.last_heartbeat_at),
                max_concurrent=machine.max_concurrent,
                reachable=(
                    machine.last_heartbeat_at is not None
                    and as_utc(machine.last_heartbeat_at) > cutoff
                ),
                workplaces=[
                    MachineWorkplace(
                        id=place.id,
                        cli_kind=place.cli_kind,
                        cli_version=place.cli_version or "",
                        ready=bool(place.ready),
                        not_ready_reason=place.not_ready_reason,
                        agents=tuple(living.get(place.id, ())),
                    )
                    for place in by_machine.get(machine.id, [])
                ],
            )
            for machine in machines
        ]

    async def set_ceiling(
        self, workspace_id: UUID, machine_id: UUID, ceiling: int
    ) -> LinkedMachine | None:
        """Set how many runs one machine may hold at once (FR-008). None if it is not here.

        The number is the **server's**, which is the whole of FR-008d: a daemon reports the
        slots it believes are free and the claim takes the smaller of the two, so this column
        is the half that cannot be talked up by a machine reporting optimistically. Until it
        could be written it was a constant 1 in a migration's default, and a constant is not
        the adjustable ceiling FR-008 asks for — it is a ceiling nobody can reach.

        Scoped by workspace as well as by id, so a machine in somebody else's workspace
        answers exactly like one that does not exist (Constitution I).

        Takes effect on the **next** ask for work. Runs already out are not recalled: the
        claim is what reads this number, and a run past that point is being executed on a
        machine that was told to have it.
        """
        if not MIN_CEILING <= ceiling <= MAX_CEILING:
            raise BadRequest(
                "machine_ceiling_out_of_range",
                least=str(MIN_CEILING),
                most=str(MAX_CEILING),
            )
        async with self._sessions()() as session:
            row = (
                await session.execute(
                    select(MachineModel).where(
                        MachineModel.id == machine_id,
                        MachineModel.workspace_id == workspace_id,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            row.max_concurrent = ceiling
            await session.commit()
        # Read back through the one place that assembles this shape, rather than patching a
        # copy here: the screen that made the change redraws from this answer, and a second
        # assembly is a second chance for the two to disagree.
        for machine in await self.list_machines(workspace_id):
            if machine.id == machine_id:
                return machine
        return None  # pragma: no cover - unlinked between the write and the read

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
