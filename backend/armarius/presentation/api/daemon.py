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
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

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


class GrantedRunOut(BaseModel):
    run_id: UUID
    task_id: UUID | None
    workplace_id: UUID
    # The one moment this string exists outside the machine that will use it. Only its hash
    # is kept, and it dies with the run (FR-014, FR-014a).
    run_token: str
    claim_expires_at: datetime


class ClaimOut(BaseModel):
    runs: list[GrantedRunOut]


class StartIn(BaseModel):
    session_handle: str = ""


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
                workplace_id=g.workplace_id,
                run_token=g.run_token,
                claim_expires_at=g.claim_expires_at,
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
