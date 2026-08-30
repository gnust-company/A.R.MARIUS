"""The doors a machine running the daemon knocks on, plus the one a person answers with.

Two audiences, two authentications, deliberately in one module because they are two halves
of a single handshake (contracts/daemon-api.md §1):

  * `/daemon/*` is called by a machine and authenticated by its own token. Every route
    under it is scoped to the workspace that token belongs to; reaching across answers 404
    and never 403, so a machine cannot learn what exists elsewhere (Constitution I).
  * `/v1/machines/link/*` is called by a signed-in person from the approval screen. It is the
    only place a machine is ever admitted to a workspace, and it is guarded by the same
    ownership check every other workspace door uses.

`POST /daemon/link/start` and `POST /daemon/link/poll` are the two exceptions to the first
rule: a machine that has not been approved yet has no token to present. Neither route
gives anything away — start hands back a code that is worthless without a person, and poll
answers *pending* until one has acted.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from armarius.domain.entities.run import RunStatus
from armarius.infrastructure.daemon.claim import ReportedEvent
from armarius.infrastructure.daemon.enrollment import MachineIdentity
from armarius.infrastructure.daemon.workplaces import ReportedWorkplace
from armarius.infrastructure.events.topic_bus import machine_topic
from armarius.presentation.api.auth import CurrentUser
from armarius.presentation.deps import ContainerDep
from armarius.shared.config import settings
from armarius.shared.errors import Conflict, NotFound, Unauthorized

router = APIRouter(prefix="/daemon", tags=["daemon"])
# The person's side of the same handshake. Separate router because it is a different
# audience with a different credential, not because it is a different feature.
people_router = APIRouter(prefix="/v1/machines", tags=["daemon"])


# ── who is calling ────────────────────────────────────────────────────────────


async def get_current_machine(
    container: ContainerDep,
    authorization: Annotated[str | None, Header()] = None,
) -> MachineIdentity:
    """Resolve the calling machine from its bearer token.

    An expired token is indistinguishable from a wrong one here, on purpose: both mean the
    machine must link again, and telling the two apart at the door would let anyone holding
    a revoked string confirm it once existed.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("missing_bearer_token")
    token = authorization.split(" ", 1)[1].strip()
    machine = await container.daemon_enrollment.authenticate(token)
    if machine is None:
        raise Unauthorized("invalid_machine_token")
    return machine


CurrentMachine = Annotated[MachineIdentity, Depends(get_current_machine)]


# ── schemas ───────────────────────────────────────────────────────────────────


class LinkStartIn(BaseModel):
    """What a machine says about itself before anyone has agreed to believe it."""

    platform: str = Field(default="", max_length=20)
    daemon_version: str = Field(default="", max_length=40)
    hostname: str = Field(default="", max_length=200)


class LinkStartOut(BaseModel):
    code: str
    verify_url: str
    expires_in: int
    interval: int


class LinkPollIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)


class LinkPollOut(BaseModel):
    """One shape for all three answers; `status` says which one this is.

    Not an error body for the *expired* case, even though it carries a 410: the daemon is
    polling on a schedule and needs to tell "keep waiting" from "stop waiting" without
    parsing a refusal.
    """

    status: str
    machine_id: UUID | None = None
    workspace_id: UUID | None = None
    token: str | None = None


class PendingLinkOut(BaseModel):
    """What the approval screen renders. Every field is a claim the machine made."""

    code: str
    hostname: str
    platform: str
    daemon_version: str
    expires_at: str | None = None


class ApproveLinkIn(BaseModel):
    workspace_id: UUID


class RenewOut(BaseModel):
    renewed: bool
    expires_at: str | None = None


class WorkplaceIn(BaseModel):
    """One agent CLI as the machine found it.

    `capabilities` is what the CLI answered when it was asked, never what its kind implies
    (FR-017). It is carried as an open object because the daemon knows what it asked and the
    server does not need to: the server stores the answer and hands it back to the layers that
    do. A capability the daemon could not ask about travels inside it, marked.
    """

    cli_kind: str = Field(min_length=1, max_length=40)
    cli_version: str = Field(default="", max_length=40)
    protocol_family: str = Field(default="", max_length=20)
    capabilities: dict[str, object] = Field(default_factory=dict)


class WorkplacesIn(BaseModel):
    """The machine's whole list, every time — not a difference.

    Sending everything is what makes a *missing* CLI visible at all: there is no message for
    "gemini is gone", only a list that no longer mentions it.
    """

    workplaces: list[WorkplaceIn] = Field(default_factory=list, max_length=50)
    # Whether this machine can make a real symbolic link, established by making one at startup
    # rather than guessed from the operating system (research.md §5).
    symlink_capable: bool = False


class WorkplaceOut(BaseModel):
    id: UUID
    cli_kind: str
    ready: bool
    not_ready_reason: str | None = None
    # The machine's readable name, so the same CLI on two of a person's machines is two
    # distinguishable workplaces (FR-003).
    machine_name: str


class WorkplacesOut(BaseModel):
    workplaces: list[WorkplaceOut]


class HeartbeatIn(BaseModel):
    free_slots: int = Field(default=0, ge=0, le=10_000)
    running: list[UUID] = Field(default_factory=list, max_length=10_000)


class HeartbeatOut(BaseModel):
    pending_work: bool
    cancel: list[UUID]


class ClaimIn(BaseModel):
    """What a machine says when it comes asking for work.

    `max` is the machine's own count of what it can take right now, and it is advice: the
    server takes the smaller of it and the ceiling it holds for that machine (FR-008d). So a
    machine reporting a wrong or stale number cannot be flooded, and cannot talk its way
    past the ceiling either.
    """

    workplace_ids: list[UUID] = Field(default_factory=list, max_length=1_000)
    max: int = Field(default=1, ge=0, le=1_000)


class SkillOut(BaseModel):
    """One skill, whole: the directory to make and everything to put in it (FR-011b).

    Sent with the work rather than fetched afterwards, and sent as contents rather than as
    links, so the agent is equipped before it reads its first line.
    """

    name: str
    files: dict[str, str]


class GrantedRunOut(BaseModel):
    run_id: UUID
    # What this run is about. Both may be empty, and which of them is filled is what says
    # whether it is a task-level run, a project-level one, or the workspace-level interview
    # (FR-013d) — which in turn decides the set of commands the machine hands its agent.
    task_id: UUID | None
    project_id: UUID | None
    workplace_id: UUID
    # The one moment this string exists outside the machine that will use it. Only its hash
    # is kept, and it dies with the run (FR-014, FR-014a).
    run_token: str
    claim_expires_at: datetime
    # The message the agent reads, assembled on this side and in English (FR-011a,
    # Constitution VII). The machine writes it into the file its CLI already reads; it does
    # not compose any of it, and it does not send it back.
    prompt: str = ""
    skills: list[SkillOut] = Field(default_factory=list)
    # What this agent was set to, out of what its workplace said its tool takes (FR-007k).
    # The machine turns these into whatever its CLI wants; this side never learns how.
    runtime_options: dict[str, str] = Field(default_factory=dict)
    # Where this machine numbers its own events from (FR-045). Everything already written for
    # this run sits below it — the message above all — so the pair (run, number) stays unique
    # even for a run that was put back and handed out a second time.
    first_seq: int = 1


class ClaimOut(BaseModel):
    runs: list[GrantedRunOut]


class StartIn(BaseModel):
    session_handle: str = ""


class EventIn(BaseModel):
    """One thing a machine says happened during a run (FR-015, FR-045).

    `seq` is assigned on the machine, in the order the agent produced things, starting from
    the `first_seq` it was handed with the work — above whatever was already written for this
    run, which is at least the message the agent was given. Numbering on that side is what
    lets a machine send events as it makes them without a round trip each to agree on the next
    number, and it is what makes a re-sent batch harmless: a number already written is left
    alone.
    """

    seq: int = Field(ge=1, le=1_000_000)
    type: str = Field(min_length=1, max_length=60)
    payload: dict[str, object] = Field(default_factory=dict)


class EventsIn(BaseModel):
    events: list[EventIn] = Field(default_factory=list, max_length=500)


class FinishIn(BaseModel):
    """How a run ended, said as a code (Constitution VII).

    Four endings and no others. *Completed* says the turn ran to its end and says nothing
    about whether the agent did the job — an agent that reports it could not finish still
    ran. The other three are the ways a turn does not reach its end, and they are kept apart
    because what happens to the task afterwards differs: a run that was cut for silence is
    resumed, a run nobody could start is not the same failure.
    """

    status: Literal["completed", "failed", "timed_out", "stopped"]
    error: str = Field(default="", max_length=4_000)
    usage: dict[str, object] = Field(default_factory=dict)


# The wire code for each ending, and the status it means. A table rather than a cast, so a
# code the server does not know is refused at the door instead of stored.
_ENDINGS: dict[str, RunStatus] = {
    "completed": RunStatus.COMPLETED,
    "failed": RunStatus.FAILED,
    "timed_out": RunStatus.TIMED_OUT,
    "stopped": RunStatus.STOPPED,
}


# ── the machine's half ────────────────────────────────────────────────────────


@router.post("/link/start", response_model=LinkStartOut)
async def start_link(body: LinkStartIn, container: ContainerDep) -> LinkStartOut:
    started = await container.daemon_enrollment.start_link(
        platform=body.platform,
        daemon_version=body.daemon_version,
        hostname=body.hostname,
    )
    return LinkStartOut(
        code=started.code,
        verify_url=f"{settings.web_base_url.rstrip('/')}/link",
        expires_in=started.expires_in_seconds,
        interval=started.poll_interval_seconds,
    )


@router.post("/link/poll", response_model=LinkPollOut)
async def poll_link(
    body: LinkPollIn, container: ContainerDep, response: Response
) -> LinkPollOut:
    """202 while waiting, 200 with the token once, 410 when the code is dead.

    The three dead ways — never existed, ran out, already spent — collapse to one answer
    because the daemon does the same thing for all of them: stop polling and tell the
    person to run `login` again.
    """
    try:
        issued = await container.daemon_enrollment.poll_link(body.code)
    except NotFound:
        response.status_code = 410
        return LinkPollOut(status="expired")
    if issued is None:
        response.status_code = 202
        return LinkPollOut(status="pending")
    return LinkPollOut(
        status="approved",
        machine_id=issued.machine_id,
        workspace_id=issued.workspace_id,
        token=issued.token,
    )


@router.post("/token/renew", response_model=RenewOut)
async def renew_token(machine: CurrentMachine, container: ContainerDep) -> RenewOut:
    """`renewed: false` is a normal answer, not a refusal (FR-014d)."""
    renewal = await container.daemon_enrollment.renew_token(machine.machine_id)
    return RenewOut(
        renewed=renewal.renewed,
        expires_at=renewal.expires_at.isoformat() if renewal.expires_at else None,
    )


@router.put("/workplaces", response_model=WorkplacesOut)
async def sync_workplaces(
    body: WorkplacesIn, machine: CurrentMachine, container: ContainerDep
) -> WorkplacesOut:
    """Register what this machine can run right now (FR-002, FR-003, FR-033).

    Scoped to the calling machine by its own token, so there is no machine id in the path and
    no way to describe someone else's machine.
    """
    seen: set[str] = set()
    for one in body.workplaces:
        if one.cli_kind in seen:
            raise Conflict("workplace_reported_twice", cli_kind=one.cli_kind)
        seen.add(one.cli_kind)

    synced = await container.daemon_workplaces.sync(
        machine,
        reported=[
            ReportedWorkplace(
                cli_kind=one.cli_kind,
                cli_version=one.cli_version,
                protocol_family=one.protocol_family,
                capabilities=one.capabilities,
            )
            for one in body.workplaces
        ],
        symlink_capable=body.symlink_capable,
    )
    return WorkplacesOut(
        workplaces=[
            WorkplaceOut(
                id=row.id,
                cli_kind=row.cli_kind,
                ready=row.ready,
                not_ready_reason=row.not_ready_reason,
                machine_name=row.machine_name,
            )
            for row in synced
        ]
    )


@router.post("/heartbeat", response_model=HeartbeatOut)
async def heartbeat(
    body: HeartbeatIn, machine: CurrentMachine, container: ContainerDep
) -> HeartbeatOut:
    """Say this machine is still here, and hear what to do next (FR-004).

    `pending_work` is a nudge to go and ask, never an instruction to run something (FR-055a) —
    which is what keeps two nudges arriving at once from producing two runs.
    """
    beat = await container.daemon_workplaces.heartbeat(
        machine, free_slots=body.free_slots, running=body.running
    )
    return HeartbeatOut(pending_work=beat.pending_work, cancel=list(beat.cancel))


@router.post("/runs/claim", response_model=ClaimOut)
async def claim_runs(
    body: ClaimIn, machine: CurrentMachine, container: ContainerDep
) -> ClaimOut:
    """The only way a run begins (FR-053, FR-054).

    An empty list is the ordinary answer and carries no complaint: most asks land on an
    empty shelf, which is exactly what lets the asking rhythm stay slow (FR-055d). Work the
    machine has no room for is left where it is — not cancelled, not re-queued, not booked
    for a retry. It comes back the next time the machine asks with room, and that is the
    whole of the retry mechanism (FR-008c).
    """
    granted = await container.daemon_claims.claim(
        machine, workplace_ids=body.workplace_ids, free_slots=body.max
    )
    return ClaimOut(
        runs=[
            GrantedRunOut(
                run_id=g.run_id,
                task_id=g.task_id,
                project_id=g.project_id,
                workplace_id=g.workplace_id,
                run_token=g.run_token,
                claim_expires_at=g.claim_expires_at,
                prompt=g.prompt,
                skills=[SkillOut(name=b.name, files=b.files) for b in g.skills],
                runtime_options=dict(g.runtime_options),
                first_seq=g.first_seq,
            )
            for g in granted
        ]
    )


@router.post("/runs/{run_id}/start")
async def start_run(
    run_id: UUID, body: StartIn, machine: CurrentMachine, container: ContainerDep
) -> dict[str, object]:
    """The machine says the agent is up. 404 means *stop and clean up* (FR-058, FR-059).

    A machine whose hold ran out while it was setting up gets the same answer as one asking
    about a run that never existed, and it is the right answer to both: whatever it has
    started is no longer this system's run, and the only useful thing left to do with it is
    put it down.
    """
    await container.daemon_claims.start(machine, run_id)
    return {}


@router.post("/runs/{run_id}/events")
async def record_run_events(
    run_id: UUID, body: EventsIn, machine: CurrentMachine, container: ContainerDep
) -> dict[str, object]:
    """What the agent is doing, while it is still doing it (FR-015, FR-045, FR-046).

    Authenticated by the **machine's** token like every other call a daemon makes, not by the
    run's. The run's token was minted for the agent and never comes back out of it (FR-014a);
    what ties a batch to a run is the id in the path, and a batch about a run this machine no
    longer holds is refused (FR-059).

    404 rather than 403 for a run belonging to another machine, matching every other door
    here: not yours and not there are the same answer, and the daemon does the same thing
    with either — stop, and clean up (Constitution I, FR-058).
    """
    await container.daemon_claims.record(
        machine,
        run_id,
        [
            ReportedEvent(seq=e.seq, type=e.type, payload=dict(e.payload))
            for e in body.events
        ],
    )
    return {}


@router.post("/runs/{run_id}/finish")
async def finish_run(
    run_id: UUID, body: FinishIn, machine: CurrentMachine, container: ContainerDep
) -> dict[str, object]:
    """The run is over — the token dies here, and the task starts moving again.

    Two obligations meet at this one door. The run's token is revoked whether the run went
    well or badly, because a credential minted for one run must stop opening anything the
    moment that run ends (FR-014b). And the task gets something live pushing it again **now**,
    rather than being noticed by a sweep some minutes later: a run can finish cleanly and
    leave the task exactly where it was, with nothing scheduled to look at it again, which is
    the hole FR-030a is written against.

    Calling twice is not an error. A reply lost on the way back is the ordinary reason a
    machine calls again, and the second call finds a run nobody holds and leaves it alone.
    """
    await container.daemon_claims.finish(
        machine,
        run_id,
        status=_ENDINGS[body.status],
        error=body.error,
        usage=dict(body.usage),
    )
    return {}


# ── the push road ─────────────────────────────────────────────────────────────


@router.get("/events")
async def machine_events(
    request: Request, machine: CurrentMachine, container: ContainerDep
) -> EventSourceResponse:
    """The road a nudge travels down (FR-055, FR-055a).

    What goes down here is a **signal**, never work and never an instruction: *there is
    something for you, come and ask*. The machine answers it by calling the same claim door
    it calls on its own rhythm, which is what keeps two nudges arriving together from
    producing two runs — the second ask simply finds an empty shelf.

    **No replay, on purpose.** Every other stream in this system hands a reconnecting client
    what it missed, because those carry news and a gap in news is a gap in the record. A
    nudge is not news; it is only true at the moment it is sent. A machine that reconnects
    asks for work as part of reconnecting, so a backlog of old nudges would buy nothing and
    cost one pointless ask each. Losing this connection entirely loses nothing either — the
    asking rhythm is the fallback, and it is why the rhythm exists (FR-055d).

    It also writes **nothing** about liveness. Holding this connection open proves the
    machine can be reached; it says nothing about whether an agent CLI on it still runs, and
    letting the two blur is exactly how a machine with its CLI uninstalled would look
    healthy forever (FR-055b).
    """
    queue, unregister = container.control_bus.register(
        machine_topic(machine.machine_id)
    )

    async def generator() -> AsyncIterator[dict[str, str]]:
        try:
            while True:
                # A short timeout rather than a plain wait, so a machine that went away
                # while the topic was quiet is noticed instead of holding a slot forever.
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                except TimeoutError:
                    if await request.is_disconnected():
                        break
                    continue
                yield {"event": event.type, "data": json.dumps(event.data)}
        finally:
            unregister()

    return EventSourceResponse(generator())


# ── the person's half ─────────────────────────────────────────────────────────


@people_router.get("/link/{code}", response_model=PendingLinkOut)
async def describe_link(
    code: str, container: ContainerDep, user: CurrentUser
) -> PendingLinkOut:
    """Show what is behind a typed-in code, so nobody approves a machine they cannot name.

    Signed-in only. A code is short enough to guess at eventually, and this route is what
    would tell a guesser whether they had.
    """
    pending = await container.daemon_enrollment.describe_link(code)
    return PendingLinkOut(
        code=pending.code,
        hostname=pending.hostname,
        platform=pending.platform,
        daemon_version=pending.daemon_version,
        expires_at=pending.expires_at.isoformat() if pending.expires_at else None,
    )


@people_router.post("/link/{code}/approve", response_model=PendingLinkOut)
async def approve_link(
    code: str, body: ApproveLinkIn, container: ContainerDep, user: CurrentUser
) -> PendingLinkOut:
    """Admit a machine to a workspace the caller owns.

    The ownership check comes first and answers 404, matching every other workspace door:
    approving into someone else's workspace and naming a workspace that does not exist are
    the same event as far as the caller is allowed to learn.
    """
    workspace = await container.workspaces.get_workspace(body.workspace_id)
    if workspace is None or workspace.owner_user_id != str(user.id):
        raise NotFound("workspace_not_found")
    pending = await container.daemon_enrollment.approve_link(
        code, workspace_id=body.workspace_id, approved_by_user_id=user.id
    )
    return PendingLinkOut(
        code=pending.code,
        hostname=pending.hostname,
        platform=pending.platform,
        daemon_version=pending.daemon_version,
        expires_at=pending.expires_at.isoformat() if pending.expires_at else None,
    )
