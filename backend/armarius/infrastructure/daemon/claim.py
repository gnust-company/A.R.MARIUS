"""Nhận việc — the one door a run starts through (FR-053, FR-054, FR-056a).

Three writes live here and they are the same write seen from three moments:

  * **offer** — a run is put on the shelf, unclaimed, at the place its agent was put in.
  * **claim** — a machine takes some of what is on the shelf. This is the compare-and-swap,
    and it is the reason the module exists.
  * **release** — a machine that took work and then went quiet loses it again, and the run
    goes back on the shelf for the same machine to take when it comes back (FR-056a).

**Why the claim is one statement.** The race this guards is not two machines fighting over
one run — FR-007 binds every agent to a single place, so two machines never see the same
run. It is *one* machine asking twice: a push and a poll landing together, a reply lost on
the way back, or two daemons alive for a moment during an upgrade (FR-054b). A `SELECT` that
finds free work followed by an `UPDATE` that takes it leaves a gap between the two where the
second ask reads the same row as free, and both asks come back holding it. Putting the test
and the write in one statement closes the gap: the second ask matches nothing and comes back
empty-handed, which is exactly what an ask with nothing to do should look like.

**Why the token is minted after.** FR-054 is about the swap, and only the swap. Once
`machine_id` is ours no other caller can touch the row, so writing the run's token into it is
an ordinary write to something we already own — and it has to be a per-row write, because one
statement cannot give each of several rows a different secret.

Infrastructure only (Constitution III). The layers above know a run was *accepted*; they never
learn by what.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import secrets
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from armarius.domain.entities.project import ProjectStatus
from armarius.domain.entities.run import RunStatus
from armarius.infrastructure.daemon.enrollment import MachineIdentity
from armarius.infrastructure.daemon.models import (
    MachineModel,
    RunClaimModel,
    WorkplaceModel,
)
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import ProjectModel, RunModel
from armarius.shared.clock import as_utc, utcnow
from armarius.shared.config import settings
from armarius.shared.errors import NotFound
from armarius.shared.logging import get_logger

logger = get_logger(__name__)

_TOKEN_PREFIX = "armr_run_"

# The run statuses that actually occupy a slot on a machine.
_HOLDING_STATUSES = (RunStatus.QUEUED.value, RunStatus.RUNNING.value)


def _hash_token(token: str) -> str:
    """The only form of a run token this system keeps."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class GrantedRun:
    """One run handed to a machine, and the only moment its token exists in the clear."""

    run_id: UUID
    task_id: UUID | None
    workplace_id: UUID
    run_token: str
    claim_expires_at: datetime


class DaemonClaimService:
    """Owns `run_claims`, and the one neutral column of `runs` that pairs with it."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        *,
        clock: Callable[[], datetime] = utcnow,
        on_release: Callable[[UUID], Awaitable[None]] | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._clock = clock
        # Told which task just lost its run, so the board stops saying a run is live on it
        # without waiting for the next sweep. A callback rather than a call into the
        # business layer: nothing under `daemon/` may reach upwards (Constitution III).
        self._on_release = on_release
        self._task: asyncio.Task[None] | None = None

    def _sessions(self) -> async_sessionmaker[AsyncSession]:
        # Resolved on use, like the other daemon services: the container is built before
        # the engine is necessarily pointed at its database.
        return self._sessionmaker or get_sessionmaker()

    # ── putting work on the shelf ────────────────────────────────────────────────

    async def offer(self, *, run_id: UUID, workspace_id: UUID, workplace_id: UUID) -> None:
        """Mark a run as available to whoever holds this workplace (FR-009).

        Writing the row is the whole of "dispatch" on this path. Nothing is sent anywhere:
        the machine finds this the next time it asks, and the ask is the only way a run
        starts (FR-053). Called twice for the same run, the second call changes nothing —
        a re-offer of work already taken would hand the same run out twice.
        """
        async with self._sessions()() as session:
            existing = await session.get(RunClaimModel, run_id)
            if existing is not None:
                return
            session.add(
                RunClaimModel(
                    run_id=run_id,
                    workspace_id=workspace_id,
                    workplace_id=workplace_id,
                )
            )
            await session.commit()

    # ── taking it off ────────────────────────────────────────────────────────────

    async def claim(
        self,
        machine: MachineIdentity,
        *,
        workplace_ids: Sequence[UUID] = (),
        free_slots: int,
    ) -> list[GrantedRun]:
        """Hand this machine up to `free_slots` runs waiting at its own workplaces.

        Coming back with nothing is the ordinary answer, not a failure — most asks find an
        empty shelf, which is what makes a slow poll rhythm affordable (FR-055d).
        """
        now = self._clock()
        async with self._sessions()() as session:
            # First thing in the transaction, and always the same first thing: an exclusive
            # lock on this machine's own row. Two asks from one machine are the whole of the
            # race FR-054b describes, and without this each of them reads a machine that
            # still looks half-empty and each takes a full allowance — four asks on a
            # two-slot machine walking away with eight runs. Taking it here, before any
            # other row, also fixes the lock order for good: machine row, then this
            # machine's own claims, and nothing else. Two different machines therefore never
            # wait on each other, so they cannot deadlock.
            ceiling = await self._ceiling(session, machine)
            released = await self._release_expired(
                session, machine.workspace_id, now, machine_id=machine.machine_id
            )

            mine = await self._workplaces_of(session, machine, workplace_ids)
            allowance = await self._allowance(session, machine, free_slots, ceiling)
            if not mine or allowance <= 0:
                await session.commit()
                await self._announce(released)
                return []

            taken = await self._swap(session, machine, mine, allowance, now)
            granted = await self._hand_over(session, taken, now)
            await session.commit()

        await self._announce(released)
        return granted

    async def _workplaces_of(
        self,
        session: AsyncSession,
        machine: MachineIdentity,
        asked_for: Sequence[UUID],
    ) -> list[UUID]:
        """The workplaces this machine may take work from, narrowed to what it asked for.

        A workplace on somebody else's machine is simply dropped rather than refused. The
        machine learns nothing about whether the id it named exists (Constitution I), and
        an ask that names one is not wrong — a daemon mid-upgrade may still be carrying a
        stale list.
        """
        rows = await session.execute(
            select(WorkplaceModel.id).where(
                WorkplaceModel.machine_id == machine.machine_id,
                WorkplaceModel.workspace_id == machine.workspace_id,
            )
        )
        mine = set(rows.scalars())
        if not asked_for:
            return sorted(mine)
        return sorted(mine & set(asked_for))

    async def _ceiling(self, session: AsyncSession, machine: MachineIdentity) -> int:
        """The server's word on how much this machine may run at once, taken under lock.

        The lock is the point of the method existing at all — see `claim`. Reading the
        number is incidental; holding the row until this ask commits is what makes the
        number mean anything (FR-008d).
        """
        row = (
            await session.execute(
                select(MachineModel)
                .where(MachineModel.id == machine.machine_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        return row.max_concurrent if row is not None else 0

    async def _allowance(
        self,
        session: AsyncSession,
        machine: MachineIdentity,
        free_slots: int,
        ceiling: int,
    ) -> int:
        """How many runs this machine may be given: the **smaller** of the two numbers.

        The machine's own count is the freshest reading of what it can actually take, and
        the ceiling is the server's word on what it is allowed to take (FR-008d). Trusting
        only the machine lets a wrong or stale report flood it; trusting only the ceiling
        hands work to a machine that just told us it has no room. Neither number alone is
        the answer, so the answer is the lower one.
        """
        held = await session.execute(
            select(RunClaimModel.run_id)
            .join(RunModel, RunModel.id == RunClaimModel.run_id)
            # A finished run stops occupying its machine here, before anyone gets around to
            # tidying its claim row away. Counting the row instead of the run would let a
            # machine fill up permanently with work that ended hours ago.
            .where(
                RunClaimModel.workspace_id == machine.workspace_id,
                RunClaimModel.machine_id == machine.machine_id,
                RunModel.status.in_(_HOLDING_STATUSES),
            )
        )
        room = ceiling - len(held.scalars().all())
        return max(0, min(free_slots, room))

    async def _swap(
        self,
        session: AsyncSession,
        machine: MachineIdentity,
        mine: Sequence[UUID],
        allowance: int,
        now: datetime,
    ) -> list[UUID]:
        """The compare-and-swap itself: choose and take in one statement (FR-054, FR-055e).

        `machine_id IS NULL` is both the test and the thing being changed, and it is read
        *inside* the update rather than in an earlier query. That is the whole guarantee:
        taking several runs at once is the same statement as taking one, so asking for
        three does not reopen the race that asking for one closed.
        """
        free = (
            select(RunClaimModel.run_id)
            .join(RunModel, RunModel.id == RunClaimModel.run_id)
            .outerjoin(ProjectModel, ProjectModel.id == RunModel.project_id)
            .where(
                RunClaimModel.machine_id.is_(None),
                RunClaimModel.workspace_id == machine.workspace_id,
                RunClaimModel.workplace_id.in_(list(mine)),
                RunModel.status == RunStatus.QUEUED.value,
                # A closed project is history, and history does not start new work. The check
                # belongs here rather than at the door: an ask is not about one project, it
                # is one machine asking about everything it hosts, and refusing the whole ask
                # because one waiting run belongs to a closed project would freeze unrelated
                # work on the same machine. Nothing new reaches this shelf for a closed
                # project — the wake path already refuses that — so what this catches is work
                # offered *before* the project closed and never taken.
                or_(
                    RunModel.project_id.is_(None),
                    ProjectModel.status != ProjectStatus.CLOSED.value,
                ),
            )
            .order_by(RunModel.created_at)
            .limit(allowance)
        )
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            # Two asks landing together must not queue behind each other — the second
            # would wait for the first and then find the same rows gone anyway. Skipping
            # locked rows lets it walk past them to the next free ones instead. SQLite has
            # no such clause and needs none: it admits one writer at a time, which is the
            # same outcome by a blunter route.
            free = free.with_for_update(skip_locked=True, of=RunClaimModel)

        taken = await session.execute(
            update(RunClaimModel)
            .where(RunClaimModel.run_id.in_(free))
            .values(
                machine_id=machine.machine_id,
                claimed_at=now,
                claim_expires_at=now + timedelta(seconds=settings.run_claim_hold_seconds),
            )
            .returning(RunClaimModel.run_id)
            .execution_options(synchronize_session=False)
        )
        return list(taken.scalars())

    async def _hand_over(
        self, session: AsyncSession, taken: Sequence[UUID], now: datetime
    ) -> list[GrantedRun]:
        """Stamp `runs.accepted_at`, mint one token per run, and describe what was given.

        `accepted_at` is written in the same transaction as the swap, which is the whole
        point of it: a run held by a machine but not yet marked accepted is a run with no
        drive on the board, and the sweep would wake the task a second time while the first
        was already being set up (FR-056).
        """
        if not taken:
            return []
        await session.execute(
            update(RunModel)
            .where(RunModel.id.in_(list(taken)))
            .values(accepted_at=now)
            .execution_options(synchronize_session=False)
        )
        rows = (
            await session.execute(
                select(RunClaimModel, RunModel.task_id)
                .join(RunModel, RunModel.id == RunClaimModel.run_id)
                .where(RunClaimModel.run_id.in_(list(taken)))
            )
        ).all()

        granted: list[GrantedRun] = []
        for claim, task_id in rows:
            token = f"{_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
            claim.run_token_hash = _hash_token(token)
            granted.append(
                GrantedRun(
                    run_id=claim.run_id,
                    task_id=task_id,
                    workplace_id=claim.workplace_id,
                    run_token=token,
                    claim_expires_at=claim.claim_expires_at or now,
                )
            )
        return granted

    # ── saying it started ────────────────────────────────────────────────────────

    async def start(self, machine: MachineIdentity, run_id: UUID) -> None:
        """The machine reports the agent is up. Refuses anything it no longer holds.

        *Not yours* and *not there* are the same answer here, and deliberately so: a machine
        whose hold ran out while it was setting up is a machine that must stop and clean up,
        and telling it apart from a run that never existed would only teach it to argue
        (FR-058, FR-059, Constitution I).
        """
        now = self._clock()
        async with self._sessions()() as session:
            claim = await session.get(RunClaimModel, run_id)
            if (
                claim is None
                or claim.workspace_id != machine.workspace_id
                or claim.machine_id != machine.machine_id
                or not self._still_held(claim, now)
            ):
                raise NotFound("run_not_found")
            await session.execute(
                update(RunModel)
                .where(RunModel.id == run_id, RunModel.status == RunStatus.QUEUED.value)
                .values(status=RunStatus.RUNNING.value, started_at=now)
                .execution_options(synchronize_session=False)
            )
            # The countdown ends here, and the hold does not. FR-056a times the *setting
            # up* — the minutes between a machine taking work and an agent existing — and
            # once the agent is up there is something real to watch instead: the run goes
            # quiet, and the hung-run reaper answers for it. Leaving the countdown running
            # would take a healthy run away from the machine two minutes in.
            claim.claim_expires_at = None
            await session.commit()

    @staticmethod
    def _still_held(claim: RunClaimModel, now: datetime) -> bool:
        """Whether this machine's grip on the run is still good.

        No deadline means a hold that has stopped counting down, not a hold that never
        began — `start` clears it. So the same machine reporting twice, because its first
        reply went missing, is told yes both times rather than being sent to clean up a run
        that is running perfectly well.
        """
        deadline = as_utc(claim.claim_expires_at)
        return deadline is None or deadline > now

    # ── giving it back ───────────────────────────────────────────────────────────

    async def _release_expired(
        self,
        session: AsyncSession,
        workspace_id: UUID,
        now: datetime,
        *,
        machine_id: UUID | None = None,
    ) -> list[UUID]:
        """Put back every run whose holder ran out of time (FR-056a, FR-007d).

        The token goes with it. A machine that woke up late still has the string it was
        given, and the point of expiry is that the string stops opening anything — otherwise
        the very run just put back can still be written to by the machine that lost it.

        `runs.accepted_at` is cleared because it answers *is a runtime holding this right
        now*, and after this write nothing is. What survives is `claimed_at`: that one is a
        fact about the past, and it is the only evidence left that this task was taken once
        already — which is what keeps its wait from being read as a wait that never started
        (FR-056b).

        `machine_id` narrows this to one machine's own holds. An ask uses it, and must: a
        machine reaching into another machine's rows mid-ask is how two asks from two
        machines end up waiting on each other. The sweep passes nothing and covers everyone,
        which is the case an ask can never reach anyway.
        """
        held_by = (
            RunClaimModel.machine_id == machine_id
            if machine_id is not None
            else RunClaimModel.machine_id.is_not(None)
        )
        rows = await session.execute(
            update(RunClaimModel)
            .where(
                RunClaimModel.workspace_id == workspace_id,
                held_by,
                RunClaimModel.claim_expires_at.is_not(None),
                RunClaimModel.claim_expires_at <= now,
            )
            .values(machine_id=None, claim_expires_at=None, run_token_hash=None)
            .returning(RunClaimModel.run_id)
            .execution_options(synchronize_session=False)
        )
        released = list(rows.scalars())
        if not released:
            return []
        # Only runs that never got going come back. One that is already running was
        # accepted, started, and is producing events — its hold lapsing is a bookkeeping
        # slip, not a reason to offer live work to a second machine.
        await session.execute(
            update(RunModel)
            .where(RunModel.id.in_(released), RunModel.status == RunStatus.QUEUED.value)
            .values(accepted_at=None)
            .execution_options(synchronize_session=False)
        )
        return released

    async def reap(self) -> list[UUID]:
        """Sweep every workspace for holds that ran out, whoever is or is not asking.

        The lazy release inside `claim` covers the machine that comes back. This covers the
        one that does not: an agent is bound to a single place (FR-007), so if that machine
        stays dark nobody else will ever ask, and without this the run would sit marked
        *taken* by a machine that is gone.
        """
        now = self._clock()
        async with self._sessions()() as session:
            spaces = await session.execute(
                select(RunClaimModel.workspace_id)
                .where(
                    RunClaimModel.machine_id.is_not(None),
                    RunClaimModel.claim_expires_at.is_not(None),
                    RunClaimModel.claim_expires_at <= now,
                )
                .distinct()
            )
            released: list[UUID] = []
            for workspace_id in list(spaces.scalars()):
                released += await self._release_expired(session, workspace_id, now)
            await session.commit()
        await self._announce(released)
        return released

    async def _announce(self, released: Sequence[UUID]) -> None:
        if not released or self._on_release is None:
            return
        async with self._sessions()() as session:
            rows = await session.execute(
                select(RunModel.task_id).where(RunModel.id.in_(list(released)))
            )
            tasks = {task_id for task_id in rows.scalars() if task_id is not None}
        for task_id in tasks:
            with contextlib.suppress(Exception):
                await self._on_release(task_id)

    # ── background lifecycle ─────────────────────────────────────────────────────

    def start_sweep(self) -> None:
        """Spawn the background reaper (idempotent)."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._sweep())

    async def stop_sweep(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _sweep(self) -> None:
        while True:
            try:
                await self.reap()
            except Exception:  # pragma: no cover - a bad tick must not kill the loop
                logger.exception("could not sweep expired run claims")
            await asyncio.sleep(settings.run_claim_reap_interval_seconds)
