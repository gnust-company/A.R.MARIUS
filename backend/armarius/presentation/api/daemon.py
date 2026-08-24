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

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, Field

from armarius.infrastructure.daemon.enrollment import MachineIdentity
from armarius.presentation.api.auth import CurrentUser
from armarius.presentation.deps import ContainerDep
from armarius.shared.config import settings
from armarius.shared.errors import NotFound, Unauthorized

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
