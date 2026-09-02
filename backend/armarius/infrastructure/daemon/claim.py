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

**Why only *offer* sends a nudge.** Putting work on the shelf is the one moment a machine
that is up has something new it does not know about, so that is where the push road is used
(FR-055). Handing work *back* is not such a moment: the in-ask release happens inside the
asking machine's own call and is re-offered to it in the same breath, and the sweep's release
only ever concerns a machine that has gone quiet — which is why the hold ran out. Nudging a
machine that is not listening buys nothing; when it comes back, it asks.

**Why the message is written here.** A run leaves the shelf dressed: the message the agent
will read is assembled at this moment and recorded at this moment, and the machine is handed
a copy rather than asked to send one back (FR-011a, FR-012a). Recording it anywhere later
means the one case where the record matters most — a machine that took work and was never
heard from again — is the one case with nothing written down. A run that cannot be dressed
is put straight back on the shelf instead of being handed over half-ready: a machine holding
a run with no message would sit on the slot until its grip ran out, and then hand back
exactly what it was given.

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
import json
import secrets
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from armarius.application.ports.work_packet import SkillBundle, WorkPacket
from armarius.domain.entities.project import ProjectStatus
from armarius.domain.entities.run import RunStatus
from armarius.domain.services.failure_kind import QUOTA_EXHAUSTED
from armarius.infrastructure.daemon import event_blobs
from armarius.infrastructure.daemon.enrollment import MachineIdentity
from armarius.infrastructure.daemon.models import (
    MachineModel,
    RunClaimModel,
    RunEventBlobModel,
    WorkplaceModel,
)
from armarius.infrastructure.daemon.run_auth import hash_run_token
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import (
    MariusModel,
    ProjectModel,
    RunEventModel,
    RunModel,
    SessionModel,
)
from armarius.shared.clock import as_utc, utcnow
from armarius.shared.config import settings
from armarius.shared.credentials import RUN_TOKEN_PREFIX, carries_our_credential
from armarius.shared.errors import BadRequest, NotFound
from armarius.shared.logging import get_logger

logger = get_logger(__name__)

# The durable record of what an agent was told (FR-012a, FR-042). Its own event type rather
# than a field on the lifecycle event beside it: this is the one thing in a run's log that
# was written before the agent existed, and folding it into an event about the run starting
# would make it look like something the run produced.
PROMPT_EVENT = "run.prompt"

# The run statuses that actually occupy a slot on a machine.
_HOLDING_STATUSES = (RunStatus.QUEUED.value, RunStatus.RUNNING.value)




@dataclass(frozen=True)
class GrantedRun:
    """One run handed to a machine, and the only moment its token exists in the clear."""

    run_id: UUID
    task_id: UUID | None
    # Which task and which project this run is about, and either may be empty. The pair is
    # what says what kind of run it is (FR-013d), and the machine needs it for one reason: it
    # decides which commands the agent is handed. A machine told only the run's id would have
    # to ask what the run is about, and a machine that has to ask is one that can be told
    # about something else.
    project_id: UUID | None
    workplace_id: UUID
    run_token: str
    claim_expires_at: datetime
    # What the agent is to read, in English, assembled on this side (FR-011a). Empty only
    # where nothing composes packets at all, which is a service wired for the shelf and
    # nothing else; whoever receives an empty one must refuse the run rather than start an
    # agent in front of a blank page.
    prompt: str = ""
    # The agent's own skills, whole, so nothing has to be fetched before it can begin
    # (FR-011b).
    skills: tuple[SkillBundle, ...] = ()
    # What this agent was set to, out of what its workplace offers (FR-007k). Carried through
    # unread: nothing on this side knows what any of these mean to the tool that will use them.
    runtime_options: tuple[tuple[str, str], ...] = ()
    # Where this machine's own numbering starts (FR-045). The machine numbers the events it
    # produces as it produces them — no round trip per event to agree on the next number — and
    # this is the number that makes those numbers unique for the run: everything already
    # written sits below it. Not always the same value twice, because a run put back on the
    # shelf is handed out again with a message composed afresh, and that message is written
    # down too.
    first_seq: int = 1


@dataclass(frozen=True)
class ReportedEvent:
    """One thing a machine says happened during a run (FR-015, FR-045)."""

    seq: int
    type: str
    payload: dict
    # What the machine says about the record itself: whether the payload is an opening slice
    # rather than the whole thing, how big the whole thing was, why anything is missing, and
    # whether a secret was masked out before it left (FR-043b, FR-047, FR-048).
    truncated: bool = False
    original_byte_size: int | None = None
    omission_reason: str | None = None
    redacted: bool = False


# The event types whose payload may never carry what a tool returned (FR-043a).
TOOL_RESULT_EVENT = "tool.completed"

# How big a tool-result event may be once it reaches here.
#
# The daemon cuts the result down before it leaves the machine, and this is the check that does
# not take its word for it (FR-043a). Comfortably larger than the daemon's own inline limit, so
# a summary that was cut correctly always fits and only an uncut one can trip it: this refuses
# the mistake, it does not tune the threshold.
MAX_TOOL_RESULT_BYTES = 4096

# Names under which a whole tool result would arrive if the cut had not happened. A summary is
# a size, a type and an opening slice (FR-043b) — none of which is called any of these.
WHOLE_RESULT_KEYS = frozenset(
    {"content", "result", "output", "stdout", "stderr", "body", "data"}
)


def refuse_whole_tool_results(events: Sequence[ReportedEvent]) -> None:
    """Refuse a batch that carries a tool's full output, whatever the daemon believes it sent.

    Checked here rather than trusted from the machine, and that is the whole point of the rule
    existing twice. The cut on the machine is what keeps the bytes at home (FR-043a); this is
    what makes the rule true of the *store* rather than of one program's good behaviour — a
    daemon on an old build, a daemon somebody patched, or a token used by something that is not
    a daemon at all all end up here.

    A refusal takes the whole batch. Writing the acceptable half would leave the run's log with
    a hole at a number that will never be filled, because the machine has no way to send a
    different event under a sequence number it has already used (FR-045).
    """
    for event in events:
        if event.type != TOOL_RESULT_EVENT:
            continue
        named = WHOLE_RESULT_KEYS & set(event.payload)
        if named:
            raise BadRequest("tool_result_not_summarised")
        if len(json.dumps(event.payload, default=str).encode("utf-8")) > MAX_TOOL_RESULT_BYTES:
            raise BadRequest("tool_result_not_summarised")


def refuse_our_own_credentials(events: Sequence[ReportedEvent]) -> None:
    """Refuse a batch carrying one of this system's tokens in the clear (FR-048, SC-015).

    Masking belongs on the machine and stays there: the daemon is handed the run's token and
    the machine's, so it masks those two by **value**, which is exact rather than a guess
    (FR-048). This is the second copy of the rule, in the T098 shape — what makes SC-015 true
    of the **store** rather than of one program's good behaviour. A daemon on an old build, a
    daemon somebody patched, and a machine token used by something that is not a daemon at all
    all arrive here, and none of them masked anything.

    This side cannot do it by value: it keeps only hashes, and there is nothing to compare a
    payload against. So it is done by shape, on the two prefixes it mints itself — the one
    class of secret whose shape this side actually knows.

    Refusing rather than masking, and the difference matters. Masking here would put the rule
    on the server, which FR-048 says it must not be; and a payload quietly rewritten in transit
    makes the log say a thing the agent did not say. A refusal is loud: the machine drops the
    batch for good and confesses `events_refused` (T141), so the run's log carries a line
    saying a batch never arrived rather than a line that has been edited.

    Not the last thing standing between a token and the log, and it was never meant to be:
    every row of a run's log is checked again at the moment it is inserted, by whatever road
    it came (FR-048c). What this door adds is the **name** — a code the machine can act on,
    in time to drop the batch and fix its masking. The net downstairs has nobody to tell.
    """
    for event in events:
        if carries_our_credential(event.payload):
            raise BadRequest("credential_in_the_clear")


def _about_the_record(event: ReportedEvent, apart: tuple[str, int] | None = None) -> dict:
    """What a live viewer needs to draw *something is missing here* as it happens (FR-046).

    The same four facts the stored row keeps in columns, carried under underscored names because
    a viewer reads the same run from two places — this stream while it runs, the stored log
    afterwards — and a screen that could only say *why* on one of them would show the same run
    two different ways.

    Left out when there is nothing to say, so an ordinary event is not made bigger to carry four
    denials.
    """
    said = {}
    if event.truncated:
        said["_truncated"] = True
    if event.original_byte_size is not None:
        said["_original_byte_size"] = event.original_byte_size
    if event.omission_reason:
        said["_omission_reason"] = event.omission_reason
    if event.redacted:
        said["_redacted"] = True
    if apart is not None:
        # Said here too, and not only in the stored row, for the reason the whole function
        # exists: a run watched live and the same run read afterwards must not offer different
        # things. Without this the *open the whole of it* handle appears only on reload, which
        # reads as the text having arrived late rather than as it having been there all along.
        said["_full_field"], said["_full_byte_size"] = apart
    return said


class DaemonClaimService:
    """Owns `run_claims`, and the one neutral column of `runs` that pairs with it."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        *,
        clock: Callable[[], datetime] = utcnow,
        on_release: Callable[[UUID], Awaitable[None]] | None = None,
        on_offer: Callable[[UUID, UUID], Awaitable[None]] | None = None,
        compose: Callable[[UUID], Awaitable[WorkPacket | None]] | None = None,
        on_recorded: Callable[[UUID, str, dict], Awaitable[None]] | None = None,
        on_run_event: Callable[[UUID, int, str, dict], Awaitable[None]] | None = None,
        on_finish: Callable[..., Awaitable[None]] | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._clock = clock
        # Told which task just lost its run, so the board stops saying a run is live on it
        # without waiting for the next sweep. A callback rather than a call into the
        # business layer: nothing under `daemon/` may reach upwards (Constitution III).
        self._on_release = on_release
        # Told which machine has something new waiting, and at which workplace. This is the
        # push road (FR-055): the machine is nudged to come and ask, and nothing else is
        # sent. A callback for the same reason as above — and because a nudge that fails to
        # go out must not be able to undo work that has already been shelved.
        self._on_offer = on_offer
        # Asked what one run's agent should be given. A callback for the same reason as the
        # two above: assembling that message reads a project's brief and an agent's own
        # instructions, and nothing down here may reach up for those (Constitution III).
        self._compose = compose
        # Told about each event as it is written, so a screen watching the task sees the run
        # move rather than finding out when it ends (FR-046). A callback for the same reason
        # as the others: publishing to a channel is not this layer's business, and nothing
        # under `daemon/` may reach upwards (Constitution III).
        self._on_recorded = on_recorded
        self._on_run_event = on_run_event
        # Told that a run is over, so the task gets a live drive again without waiting for a
        # sweep (FR-030a). What *closing a run* means — the follow-up wake, the pair handed
        # back, the recovery ladder — is entirely the business layer's, and none of it can be
        # decided from down here.
        self._on_finish = on_finish
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

        The read cannot rule out a second call arriving between it and the write, so the
        primary key is what actually settles it: whichever caller lands first owns the row,
        and the other is told so by the database and returns just as quietly.
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
            try:
                await session.commit()
            except IntegrityError:
                # Somebody else's insert won. The shelf is in the state this call wanted it
                # in, and they will have sent the nudge that goes with it.
                await session.rollback()
                return
            workplace = await session.get(WorkplaceModel, workplace_id)
            machine_id = workplace.machine_id if workplace is not None else None

        # Outside the transaction: the work is on the shelf whatever happens next, and a
        # nudge is only ever an invitation to come and look at it.
        if machine_id is not None:
            await self._nudge(machine_id, workplace_id)

    async def _nudge(self, machine_id: UUID, workplace_id: UUID) -> None:
        """Tell one machine there is something to come and ask for (FR-055a).

        Failure here is deliberately swallowed. The nudge is the fast road, not the only
        one: a machine that never hears it asks on its own rhythm a few seconds later and
        finds the same work (FR-055d). Letting a broken push road throw would turn a slower
        start into a lost run.
        """
        if self._on_offer is None:
            return
        try:
            await self._on_offer(machine_id, workplace_id)
        except Exception:  # pragma: no cover - the shelf is already correct
            logger.exception("could not nudge machine %s about new work", machine_id)

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
        # Outside the swap on purpose. Dressing a run reads half a dozen other tables, and
        # doing it under the machine's lock would hold every other ask from that machine for
        # the length of the read. Out here the swap has already committed, so the worst a
        # slow or failing dress can do is give a run back — never hand the same one out
        # twice.
        return await self._dress(granted, machine.workspace_id)

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
                select(RunClaimModel, RunModel.task_id, RunModel.project_id)
                .join(RunModel, RunModel.id == RunClaimModel.run_id)
                .where(RunClaimModel.run_id.in_(list(taken)))
            )
        ).all()

        granted: list[GrantedRun] = []
        for claim, task_id, project_id in rows:
            token = f"{RUN_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
            claim.run_token_hash = hash_run_token(token)
            granted.append(
                GrantedRun(
                    run_id=claim.run_id,
                    task_id=task_id,
                    project_id=project_id,
                    workplace_id=claim.workplace_id,
                    run_token=token,
                    # Read back through `as_utc` rather than handed over as stored. A
                    # timestamp column comes back tz-aware from one database engine and
                    # naive from another, and naive is not a smaller version of aware — it
                    # serialises without an offset, and a machine reading it cannot parse it
                    # at all. The daemon is right to refuse a moment that does not say which
                    # moment it is; what must not vary is what this side sends.
                    claim_expires_at=as_utc(claim.claim_expires_at) or now,
                )
            )
        return granted

    # ── dressing it ──────────────────────────────────────────────────────────────

    async def _dress(
        self, granted: Sequence[GrantedRun], workspace_id: UUID
    ) -> list[GrantedRun]:
        """Give each run its message and its skills, and write the message down.

        Composing and recording are one step with one outcome, because a run is only
        properly handed over when both have happened: a machine holding a message nobody
        recorded leaves the log unable to answer *what was this agent told*, which is the
        first question asked of a run that went wrong (FR-042).
        """
        if self._compose is None:
            return list(granted)
        dressed: list[GrantedRun] = []
        for run in granted:
            made = await self._packet_for(run.run_id, workspace_id)
            if made is None:
                await self._give_back(run.run_id)
                continue
            packet, written_at = made
            dressed.append(
                replace(
                    run,
                    prompt=packet.prompt,
                    skills=tuple(packet.skills),
                    # The place's word for these on the way in, the runtime's on the way
                    # out: this is the boundary, and it is the only place they are renamed.
                    runtime_options=tuple(packet.placement_options),
                    first_seq=written_at + 1,
                )
            )
        return dressed

    async def _packet_for(
        self, run_id: UUID, workspace_id: UUID
    ) -> tuple[WorkPacket, int] | None:
        """One run's packet, written down on the way past. None if either half failed.

        Swallowing the failure and answering None rather than raising: from here there is
        exactly one thing to do about a run that cannot be dressed, whatever went wrong
        with it, and that is to put it back. Letting the exception out would take the whole
        ask down with it — including the other runs in the same answer, which are fine.
        """
        if self._compose is None:
            return None
        try:
            packet = await self._compose(run_id)
        except Exception:
            logger.exception("could not make up the packet for run %s", run_id)
            return None
        if packet is None:
            logger.warning("there is nothing to say to an agent about run %s", run_id)
            return None
        try:
            written_at = await self._record(run_id, packet.prompt, workspace_id)
        except Exception:
            logger.exception("could not write down the message sent for run %s", run_id)
            return None
        return packet, written_at

    async def _record(self, run_id: UUID, prompt: str, workspace_id: UUID) -> int:
        """Keep the message, whole, as the run's first event, and say where it sits.

        Written from here rather than sent back by whoever runs the agent (FR-012a, FR-042):
        this side built the text, so it already has it, and asking for it back would make the
        record depend on a machine still being reachable at exactly the moment it may not be.

        **The number it takes matters to the machine.** Everything the agent then produces is
        numbered by the machine that runs it, starting just after this one, and the pair
        (run, number) is unique — which is what makes a re-sent batch harmless (FR-045). A run
        can be dressed more than once, because work put back on the shelf is offered again with
        a message composed afresh, so *first* is not always one; the number is returned rather
        than assumed for exactly that reason.

        The size is recorded beside it whether or not anything was cut, so that *how long was
        the message* is one column rather than a question about which branch was taken.

        A long message is kept in two pieces (FR-049): an opening slice here, the whole of it
        in `run_event_blobs`. A message is the one thing on this side that is routinely long —
        it carries the task, the skills and the standing instructions — and it is also the one
        thing a person reads in full when they want to know why an agent did what it did.
        """
        async with self._sessions()() as session:
            highest = await session.scalar(
                select(func.max(RunEventModel.seq)).where(RunEventModel.run_id == run_id)
            )
            seq = (highest or 0) + 1
            event_id = uuid4()
            split = event_blobs.split(
                PROMPT_EVENT, {"prompt": prompt}, settings.run_event_inline_bytes
            )
            session.add(
                RunEventModel(
                    id=event_id,
                    run_id=run_id,
                    seq=seq,
                    type=PROMPT_EVENT,
                    payload=split.payload,
                    truncated=split.was_cut,
                    original_byte_size=len(prompt.encode("utf-8")),
                    created_at=self._clock(),
                )
            )
            if split.was_cut:
                # The event row goes down first: see the note in `record` — a foreign key on
                # its own does not make one insert wait for another.
                await session.flush()
                session.add(
                    event_blobs.keeping(
                        run_event_id=event_id, workspace_id=workspace_id, split=split
                    )
                )
            await session.commit()
        return seq

    async def _give_back(self, run_id: UUID) -> None:
        """Put one run back exactly as it was before this ask found it.

        The token goes with it, for the same reason expiry takes it: the machine was told a
        string, and the string must stop opening anything the moment the run stops being
        that machine's. `accepted_at` goes too — it answers *is a runtime holding this right
        now*, and after this nobody is.
        """
        async with self._sessions()() as session:
            await session.execute(
                update(RunClaimModel)
                .where(RunClaimModel.run_id == run_id)
                .values(machine_id=None, claim_expires_at=None, run_token_hash=None)
                .execution_options(synchronize_session=False)
            )
            await session.execute(
                update(RunModel)
                .where(RunModel.id == run_id, RunModel.status == RunStatus.QUEUED.value)
                .values(accepted_at=None)
                .execution_options(synchronize_session=False)
            )
            await session.commit()
        await self._announce([run_id])

    # ── saying it started ────────────────────────────────────────────────────────

    async def start(
        self, machine: MachineIdentity, run_id: UUID, session_handle: str = ""
    ) -> None:
        """The machine reports the agent is up. Refuses anything it no longer holds.

        *Not yours* and *not there* are the same answer here, and deliberately so: a machine
        whose hold ran out while it was setting up is a machine that must stop and clean up,
        and telling it apart from a run that never existed would only teach it to argue
        (FR-058, FR-059, Constitution I).

        `session_handle` is the conversation this run is carrying on, empty when it opened a
        new one. It is written down here for the same reason everything else about a run is:
        the machine holds it, and a claim about the machine's disk is a claim nobody can check
        (FR-023, SC-006). What is stored is the same row the in-process road stores — one
        session per agent, adapter and task — so *the boundary of a conversation is the task*
        is one fact with one place to read it, not a property each road proves separately.
        """
        now = self._clock()
        async with self._sessions()() as db:
            claim = await db.get(RunClaimModel, run_id)
            if (
                claim is None
                or claim.workspace_id != machine.workspace_id
                or claim.machine_id != machine.machine_id
                or not self._still_held(claim, now)
            ):
                raise NotFound("run_not_found")
            await db.execute(
                update(RunModel)
                .where(RunModel.id == run_id, RunModel.status == RunStatus.QUEUED.value)
                .values(status=RunStatus.RUNNING.value, started_at=now)
                .execution_options(synchronize_session=False)
            )
            await self._remember_session(db, run_id, session_handle, now)
            # The countdown ends here, and the hold does not. FR-056a times the *setting
            # up* — the minutes between a machine taking work and an agent existing — and
            # once the agent is up there is something real to watch instead: the run goes
            # quiet, and the hung-run reaper answers for it. Leaving the countdown running
            # would take a healthy run away from the machine two minutes in.
            claim.claim_expires_at = None
            await db.commit()

    async def _remember_session(
        self, db: AsyncSession, run_id: UUID, handle: str, now: datetime
    ) -> None:
        """Write down which conversation this run is carrying on (FR-023, FR-024).

        Nothing is written for a run that opened a new conversation. The machine cannot say
        what a CLI will call a thread until the CLI has said it, so an empty handle here means
        *this run is not carrying anything on* — and overwriting a task's session with that
        would erase the very thread the next wake is meant to find.

        Keyed by agent, adapter and task, which is the boundary itself: FR-024 says two tasks
        are two conversations even for one agent, and this unique triple is where that stops
        being a promise and becomes a row.

        The adapter is read off the **agent**, not off the run, and that is not a detail. It is
        the key every reader looks the row up by, and the layer that closes a run writes it the
        same way. A run carries its own copy, taken when the run was made; deriving the key here
        from that copy would be a second derivation of one key, and a second derivation is a
        second answer waiting to differ — two rows for one task, each written by a different
        road, and whichever road wrote last winning a conversation the other one is still
        looking for.
        """
        if not handle:
            return
        run = await db.get(RunModel, run_id)
        if run is None or run.marius_id is None or run.task_id is None:
            return
        run.session_id_before = handle
        marius = await db.get(MariusModel, run.marius_id)
        if marius is None:
            return

        found = await db.scalar(
            select(SessionModel).where(
                SessionModel.marius_id == run.marius_id,
                SessionModel.adapter_type == marius.adapter_type,
                SessionModel.task_id == run.task_id,
            )
        )
        if found is None:
            found = SessionModel(
                id=uuid4(),
                project_id=run.project_id,
                marius_id=run.marius_id,
                adapter_type=marius.adapter_type,
                task_id=run.task_id,
                created_at=now,
            )
            db.add(found)
        found.session_params_json = {"handle": handle}
        found.session_display_id = handle
        found.last_run_id = run_id
        found.updated_at = now

    # ── what the machine says while the run is going, and when it is over ────────

    async def record(
        self, machine: MachineIdentity, run_id: UUID, events: Sequence[ReportedEvent]
    ) -> None:
        """Write down what an agent did, while it is still doing it (FR-015, FR-045, FR-046).

        **Numbered by the machine, written once here.** The machine numbers its own events as
        it makes them, which is what lets it send them without a round trip per event; this
        side treats a number it already holds as a number already written. That is what makes
        a lost reply cost a repeated call and nothing else — the machine sends the same batch
        again and the store is unchanged (FR-045).

        Refused outright when this machine no longer holds the run (FR-059). That case is not
        rare enough to leave open: the two clocks are not the same clock, so a machine whose
        hold lapsed can still believe it holds the run and still have an agent running. Blocking
        the write is what makes that surplus run leave no trace at all.
        """
        if not events:
            return
        refuse_whole_tool_results(events)
        refuse_our_own_credentials(events)

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

            already = set(
                (
                    await session.execute(
                        select(RunEventModel.seq).where(
                            RunEventModel.run_id == run_id,
                            RunEventModel.seq.in_([e.seq for e in events]),
                        )
                    )
                ).scalars()
            )
            fresh = [event for event in events if event.seq not in already]
            # What has a second half, held back until the rows it hangs off are in. A bare
            # foreign key does not order a flush — only a mapped relationship does, and this
            # schema has none by design — so adding a child beside its parent leaves the order
            # to chance, and chance loses on PostgreSQL every time.
            apart: list[RunEventBlobModel] = []
            #: seq → (which key has more, how much of it there is), for the live push below.
            more: dict[int, tuple[str, int]] = {}
            # What the live push says, which has to be what the stored row says — the opening
            # slice, not the whole. A viewer reads one run from two roads (this push while it
            # runs, the stored log afterwards) and the two must not describe it differently.
            shown: list[ReportedEvent] = []
            for event in fresh:
                event_id = uuid4()
                # Long enough to be worth keeping in two pieces? Only three kinds of event
                # can be, and a tool result is never one of them (FR-049, FR-043a).
                split = event_blobs.split(
                    event.type, dict(event.payload), settings.run_event_inline_bytes
                )
                session.add(
                    RunEventModel(
                        id=event_id,
                        run_id=run_id,
                        seq=event.seq,
                        type=event.type,
                        payload=split.payload,
                        # `or`, not `=`: the machine may already have cut this for its own
                        # reason, and a cut here does not undo one made there.
                        truncated=event.truncated or split.was_cut,
                        # Only when something was actually cut. A size on an event that is
                        # whole would put one on nearly every row, and then *has a size*
                        # stops meaning *there is more of this* — which is the one thing a
                        # reader uses it for.
                        original_byte_size=(
                            event.original_byte_size
                            if event.original_byte_size is not None
                            else (split.byte_size if split.was_cut else None)
                        ),
                        omission_reason=event.omission_reason,
                        redacted=event.redacted,
                        created_at=now,
                    )
                )
                shown.append(replace(event, payload=split.payload))
                if split.was_cut:
                    more[event.seq] = (split.field, split.byte_size)
                    apart.append(
                        event_blobs.keeping(
                            run_event_id=event_id,
                            workspace_id=machine.workspace_id,
                            split=split,
                        )
                    )
            if not fresh:
                return
            if apart:
                await session.flush()
                session.add_all(apart)
            # The one column outside this module's own tables that a run's events touch, and
            # it has to be touched here: it is what the silence rules read to tell a run that
            # is working from one that has stopped (FR-030, FR-056).
            await session.execute(
                update(RunModel)
                .where(RunModel.id == run_id)
                .values(last_output_at=now)
                .execution_options(synchronize_session=False)
            )
            task_id = await session.scalar(
                select(RunModel.task_id).where(RunModel.id == run_id)
            )
            try:
                await session.commit()
            except IntegrityError:
                # Two copies of one batch arriving together. The numbers are the same numbers,
                # so whichever landed first wrote exactly what this one was going to.
                await session.rollback()
                return

        await self._show(task_id, run_id, shown, more)

    async def _show(
        self,
        task_id: UUID | None,
        run_id: UUID,
        events: Sequence[ReportedEvent],
        more: dict[int, tuple[str, int]] | None = None,
    ) -> None:
        """Put what was just written in front of anyone watching (FR-046).

        Best effort, and after the commit. A screen that cannot be told is a screen that
        refreshes a moment later; a write that fails because a screen could not be told is
        work lost. The run's identity travels in the payload so a client that both replays
        the stream and reads the stored log can tell the overlap apart by identity.

        **Two channels, because two screens ask different questions.** The task channel is the
        collaboration room: *what is happening on this piece of work*, across every run it has
        had. The run channel is one run's own log, and it is the one a person opens to answer
        *what did this agent do* — so a run with no task still has to feed it, and a run being
        watched live has to show the same thing the stored log will show afterwards. Wired
        separately for the same reason they are separate: neither may fall silent because the
        other did.
        """
        for event in events:
            said = {
                **event.payload,
                **_about_the_record(event, (more or {}).get(event.seq)),
                "_run_id": str(run_id),
                "_seq": event.seq,
            }
            if task_id is not None and self._on_recorded is not None:
                with contextlib.suppress(Exception):
                    await self._on_recorded(task_id, event.type, said)
            if self._on_run_event is not None:
                with contextlib.suppress(Exception):
                    await self._on_run_event(run_id, event.seq, event.type, said)

    async def finish(
        self,
        machine: MachineIdentity,
        run_id: UUID,
        *,
        status: RunStatus,
        error: str = "",
        usage: dict | None = None,
        session_handle: str = "",
        failure: str = "",
    ) -> None:
        """The machine says the run is over, however it ended (FR-014b, FR-030a).

        Two things happen and they are not the same thing. Here, the run stops being this
        machine's: the hold goes and **the token goes with it**, which is the whole of FR-014b
        — a credential minted for one run must stop opening anything the moment that run ends,
        whether it ended well or badly. Above, the business layer decides what the *task* does
        next, and that is the half FR-030a is about.

        Told twice, this does nothing the second time. A reply lost on the way back makes the
        machine call again, and by then the hold is already gone: there is nothing left to
        release and nothing left to conclude, so the call returns quietly rather than sending
        the task through its ending a second time.

        A run that ended because the workplace has no provider quota left closes **the
        workplace**, not the run's own little corner of it (FR-007c). Quota belongs to the
        login the workplace was set up with, so it is out for every agent working there and
        for the next run as much as this one; closing it here is what stops the next agent
        being sent to the same wall, and every consequence after that — the agents reported
        offline, their tasks parked, the Leader told — is the door that already exists for a
        workplace that stops being usable.
        """
        async with self._sessions()() as session:
            claim = await session.get(RunClaimModel, run_id)
            if claim is None or claim.workspace_id != machine.workspace_id:
                raise NotFound("run_not_found")
            if claim.machine_id is None:
                # Already closed, or taken back while this machine was finishing. Either way
                # nobody holds it, and nothing here has anything left to do.
                return
            if claim.machine_id != machine.machine_id:
                raise NotFound("run_not_found")
            claim.machine_id = None
            claim.claim_expires_at = None
            claim.run_token_hash = None
            if failure == QUOTA_EXHAUSTED:
                await self._close_the_workplace(
                    session, claim.workplace_id, reason=failure
                )
            await session.commit()

        if self._on_finish is not None:
            # The conversation the run *ended* holding travels with the ending rather than being
            # written here: closing a run is one piece of work, and the layer that does it
            # already writes a task's session (FR-023, FR-025). A second writer on this side
            # would be a second answer to the same question — and the losing one, because the
            # ending lands after it.
            await self._on_finish(
                run_id,
                status=status,
                error=error or None,
                usage=usage or {},
                session_handle=session_handle,
                failure=failure,
            )

    async def _close_the_workplace(
        self, session: AsyncSession, workplace_id: UUID, *, reason: str
    ) -> None:
        """Mark a workplace unusable, with the reason, in the caller's transaction.

        Not ready is a single verdict with a code beside it for the screen, exactly as the
        workplace sweep writes it (FR-006c) — nothing above this layer branches on which
        code it is. A workplace already closed keeps the reason it already had: the first
        answer is the measured one, and overwriting it with a later, vaguer one is how a
        reader ends up being sent to fix the wrong thing.
        """
        workplace = await session.get(WorkplaceModel, workplace_id)
        if workplace is None or not workplace.ready:  # pragma: no cover - defensive
            return
        workplace.ready = False
        workplace.not_ready_reason = reason
        workplace.updated_at = self._clock()

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
