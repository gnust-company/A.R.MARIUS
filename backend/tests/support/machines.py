"""Helpers for linking a machine in tests.

Unlike ``ready_workplace``, which writes the rows straight to the database for tests that
merely need *a workplace to exist*, this walks the real device flow: the machine asks, a
person approves, the machine collects its token and reports what it found. Anything that
calls a `/daemon/*` route needs it, because those routes authenticate a **token** and a
hand-written row has none.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select

from armarius.infrastructure.daemon.models import MachineModel
from armarius.infrastructure.database.engine import get_sessionmaker


@dataclass
class LinkedMachine:
    """One machine admitted to a workspace, offering one CLI."""

    token: str
    workspace_id: str
    machine_id: UUID
    workplace_id: str
    #: The person who approved it, as an Authorization header.
    headers: dict[str, str]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def link_machine(
    c: AsyncClient,
    email: str,
    *,
    hostname: str = "thinkpad",
    cli_kind: str = "claude_code",
    protocol_family: str = "one_shot",
) -> LinkedMachine:
    """Register a person, link a machine to their workspace, and report one workplace.

    Every step goes through the real routes. A hand-written machine row would prove the
    daemon doors work on rows those doors would never have produced.
    """
    registered = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    assert registered.status_code == 201, registered.text
    person = auth(registered.json()["tokens"]["access_token"])
    workspaces = await c.get("/v1/workspaces", headers=person)
    workspace_id = workspaces.json()[0]["id"]
    return await link_machine_to(
        c,
        person,
        workspace_id,
        hostname=hostname,
        cli_kind=cli_kind,
        protocol_family=protocol_family,
    )


async def link_machine_to(
    c: AsyncClient,
    person: dict[str, str],
    workspace_id: str,
    *,
    hostname: str = "thinkpad",
    cli_kind: str = "claude_code",
    protocol_family: str = "one_shot",
    symlink_capable: bool = True,
) -> LinkedMachine:
    """Link a machine to a workspace somebody already has, and report one workplace.

    For a test that has to do something between registering and linking — which is what a
    real person does: they sign up, look around, and only later install the daemon.

    `symlink_capable=False` reports a machine that cannot link a CLI's home, so the workplace
    exists from the first report but cannot take work.
    """
    started = await c.post(
        "/daemon/link/start",
        json={"platform": "linux", "daemon_version": "0.1.0", "hostname": hostname},
    )
    code = started.json()["code"]
    approved = await c.post(
        f"/v1/machines/link/{code}/approve",
        json={"workspace_id": workspace_id},
        headers=person,
    )
    assert approved.status_code == 200, approved.text
    token = (await c.post("/daemon/link/poll", json={"code": code})).json()["token"]

    synced = await c.put(
        "/daemon/workplaces",
        json={
            "workplaces": [
                {
                    "cli_kind": cli_kind,
                    "cli_version": "1.0.0",
                    "protocol_family": protocol_family,
                    "capabilities": {"resumable": True},
                }
            ],
            "symlink_capable": symlink_capable,
        },
        headers=auth(token),
    )
    assert synced.status_code == 200, synced.text

    async with get_sessionmaker()() as session:
        machine_id = (
            await session.execute(
                select(MachineModel.id).where(
                    MachineModel.workspace_id == UUID(workspace_id),
                    # By name, not just by workspace: a test that links two machines to one
                    # workspace would otherwise get whichever row came back first.
                    MachineModel.display_name == hostname,
                )
            )
        ).scalar_one()
    return LinkedMachine(
        token=token,
        workspace_id=workspace_id,
        machine_id=machine_id,
        workplace_id=synced.json()["workplaces"][0]["id"],
        headers=person,
    )


async def the_host(c: AsyncClient, person: dict[str, str], workspace_id: str) -> dict:
    """The workspace's host as the directory shows it."""
    directory = await c.get(f"/v1/workspaces/{workspace_id}/mariuses", headers=person)
    assert directory.status_code == 200, directory.text
    return next(m for m in directory.json() if m["role"] == "Workspace Agent")


async def put_host_to_work(
    c: AsyncClient,
    person: dict[str, str],
    workspace_id: str,
    workplace_id: str,
    *,
    instructions: str | None = None,
    name: str | None = None,
):
    """Choose where the host works, the way its owner does (spec 003 FR-125, FR-128).

    Linking a machine no longer places the host by itself (FR-112, revised 2026-10-12), so a
    test that needs a host with somewhere to work has to make this choice, like a person.
    Returns the raw response so a test about refusals can read them.
    """
    host = await the_host(c, person, workspace_id)
    body: dict[str, object] = {"workplace_id": workplace_id}
    if instructions is not None:
        body["instructions"] = instructions
    if name is not None:
        body["name"] = name
    return await c.post(
        f"/v1/workspaces/{workspace_id}/mariuses/{host['id']}/placement",
        headers=person,
        json=body,
    )
