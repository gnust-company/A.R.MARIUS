"""An agent is put somewhere when it is created, and it stays there (T039–T041, FR-007, FR-007f).

This is the join the whole feature hangs off. A run is handed to a machine because an agent
was assigned it, and the machine is found by asking where that agent works — so an agent with
nowhere to work is an agent no work can ever reach. The requirement closes that by refusing
to create one at all: the attachment is written in the same transaction as the agent, and the
create flow has no path that leaves it blank.

Two rules the tests below circle:

  * **Chosen once.** There is no route, use case or repository method that moves an agent
    afterwards (FR-007). Replacing the agent is a person's decision, not the system's.
  * **Shared, not owned.** One workplace holds as many agents as the patron wants (FR-007a) —
    a machine has one copy of each CLI, so the opposite rule would cap a machine at one agent
    per CLI kind.

Everything runs against the real app: real routes, real container, real error handlers.
"""

from __future__ import annotations

import inspect
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from armarius.domain.repositories.repositories import PlacementRepository
from armarius.infrastructure.daemon.models import (
    AgentWorkplaceBindingModel,
    MachineModel,
    WorkplaceModel,
)
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.main import app
from tests.support.agents import (
    GATEWAY_KEY,
    GATEWAY_URL,
    invite_agent,
    ready_workplace,
)

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _patron(c: AsyncClient, email: str) -> tuple[dict, str]:
    """One signed-in person with their own workspace. Returns their headers and workspace."""
    registered = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    assert registered.status_code == 201, registered.text
    headers = {"Authorization": f"Bearer {registered.json()['tokens']['access_token']}"}
    workspaces = await c.get("/v1/workspaces", headers=headers)
    return headers, workspaces.json()[0]["id"]


async def _invite_raw(
    c: AsyncClient, ws_id: str, h: dict, body: dict
) -> tuple[int, dict]:
    """Post an invite exactly as given — no helper filling anything in."""
    r = await c.post(f"/v1/workspaces/{ws_id}/mariuses", headers=h, json=body)
    return r.status_code, (r.json() if r.content else {})


async def _binding_of(marius_id: str) -> AgentWorkplaceBindingModel | None:
    async with get_sessionmaker()() as s:
        return await s.get(AgentWorkplaceBindingModel, UUID(marius_id))


# ── the attachment is written, once, with the agent ──────────────────────────


async def test_creating_an_agent_attaches_it_to_the_chosen_workplace() -> None:
    async with _client() as c:
        h, ws = await _patron(c, "bind-basic@armarius.dev")
        workplace = await ready_workplace(ws, cli_kind="claude_code")

        agent = await invite_agent(c, ws, h, name="Marin", workplace_id=workplace)

    row = await _binding_of(agent["id"])
    assert row is not None, "an agent was created with nowhere to work"
    assert str(row.workplace_id) == workplace
    assert str(row.workspace_id) == ws


async def test_an_invite_with_no_workplace_is_refused_and_creates_nothing() -> None:
    """The field has no default. Leaving it out is the state FR-007f abolishes."""
    async with _client() as c:
        h, ws = await _patron(c, "bind-blank@armarius.dev")
        await ready_workplace(ws)

        status, _ = await _invite_raw(
            c,
            ws,
            h,
            {
                "name": "Nowhere",
                "adapter_type": "echo",
                "gateway_url": GATEWAY_URL,
                "api_key": GATEWAY_KEY,
            },
        )
        assert status == 422, "an agent with no workplace was accepted"

        directory = await c.get(f"/v1/workspaces/{ws}/mariuses", headers=h)
        assert directory.json() == [], "a refused invite still left an agent behind"


async def test_another_workspaces_workplace_reads_as_not_there() -> None:
    """404 and not 403: confirming the id exists is itself the leak (Constitution I)."""
    async with _client() as c:
        stranger_h, stranger_ws = await _patron(c, "bind-stranger@armarius.dev")
        theirs = await ready_workplace(stranger_ws)

        h, ws = await _patron(c, "bind-mine@armarius.dev")
        status, body = await _invite_raw(
            c,
            ws,
            h,
            {
                "name": "Trespasser",
                "adapter_type": "echo",
                "gateway_url": GATEWAY_URL,
                "api_key": GATEWAY_KEY,
                "workplace_id": theirs,
            },
        )

        assert status == 404, body
        assert body.get("code") == "placement_not_found"
        # The same answer an id that never existed gets — that is the point.
        missing = await _invite_raw(
            c,
            ws,
            h,
            {
                "name": "Ghost",
                "adapter_type": "echo",
                "gateway_url": GATEWAY_URL,
                "api_key": GATEWAY_KEY,
                "workplace_id": str(uuid4()),
            },
        )
        assert missing == (404, body)

        directory = await c.get(f"/v1/workspaces/{ws}/mariuses", headers=h)
        assert directory.json() == []


async def test_a_workplace_that_cannot_work_is_refused_with_its_reason() -> None:
    """Different from *not found*: this one is the patron's, and they can go and fix it."""
    async with _client() as c:
        h, ws = await _patron(c, "bind-notready@armarius.dev")
        workplace = await ready_workplace(ws)
        async with get_sessionmaker()() as s:
            row = await s.get(WorkplaceModel, UUID(workplace))
            assert row is not None
            row.ready = False
            row.not_ready_reason = "cli_removed"
            await s.commit()

        status, body = await _invite_raw(
            c,
            ws,
            h,
            {
                "name": "Stillborn",
                "adapter_type": "echo",
                "gateway_url": GATEWAY_URL,
                "api_key": GATEWAY_KEY,
                "workplace_id": workplace,
            },
        )

        assert status == 400, body
        assert body.get("code") == "placement_not_ready"
        # The reason travels as a code the screen can word, never as a finished sentence.
        assert body.get("params", {}).get("reason") == "cli_removed"

        directory = await c.get(f"/v1/workspaces/{ws}/mariuses", headers=h)
        assert directory.json() == []


async def test_many_agents_share_one_workplace() -> None:
    """FR-007a. A machine holds one copy of each CLI; one agent per CLI would be the cap."""
    async with _client() as c:
        h, ws = await _patron(c, "bind-shared@armarius.dev")
        workplace = await ready_workplace(ws)

        first = await invite_agent(c, ws, h, name="Alice", workplace_id=workplace)
        second = await invite_agent(c, ws, h, name="Bob", workplace_id=workplace)

    for agent in (first, second):
        row = await _binding_of(agent["id"])
        assert row is not None and str(row.workplace_id) == workplace


# ── the attachment cannot be changed ─────────────────────────────────────────


def test_nothing_in_the_port_can_move_an_agent() -> None:
    """FR-007 says the attachment is fixed, so the port offers no way to change it.

    A shape check rather than a behaviour one, because the behaviour being asserted is the
    absence of a behaviour: the day someone adds `move`, this is what says no.
    """
    offered = {
        name
        for name, _ in inspect.getmembers(PlacementRepository, inspect.isfunction)
        if not name.startswith("_")
    }
    assert offered == {"get", "attach"}, (
        "PlacementRepository grew a method. If it moves an agent between workplaces it "
        "breaks FR-007; if it does not, add it here on purpose."
    )


async def test_a_second_attachment_for_the_same_agent_is_refused() -> None:
    async with _client() as c:
        h, ws = await _patron(c, "bind-twice@armarius.dev")
        elsewhere = await ready_workplace(ws, cli_kind="gemini", machine_name="other-box")
        agent = await invite_agent(c, ws, h, name="Marin")

    from armarius.shared.errors import Conflict

    async with app.state.container.uow_factory() as uow:
        with pytest.raises(Conflict):
            await uow.placements.attach(UUID(agent["id"]), UUID(ws), UUID(elsewhere))


async def test_the_attachment_survives_the_cli_being_uninstalled() -> None:
    """The workplace turns not-ready and keeps its id, so the attachment still points home.

    This is why a vanished CLI is never a deleted row (FR-033): deleting it would leave every
    agent that lived there attached to nothing, and nothing can never be repaired.
    """
    async with _client() as c:
        h, ws = await _patron(c, "bind-uninstall@armarius.dev")
        workplace = await ready_workplace(ws, cli_kind="claude_code")
        agent = await invite_agent(c, ws, h, name="Marin", workplace_id=workplace)

    async with get_sessionmaker()() as s:
        row = await s.get(WorkplaceModel, UUID(workplace))
        assert row is not None
        row.ready = False
        row.not_ready_reason = "cli_removed"
        await s.commit()

    kept = await _binding_of(agent["id"])
    assert kept is not None and str(kept.workplace_id) == workplace


# ── the list a person picks from ─────────────────────────────────────────────


async def test_the_picker_lists_only_ready_workplaces_with_their_machine() -> None:
    async with _client() as c:
        h, ws = await _patron(c, "list-ready@armarius.dev")
        usable = await ready_workplace(ws, cli_kind="claude_code", machine_name="thinkpad")
        broken = await ready_workplace(ws, cli_kind="gemini", machine_name="desktop")
        async with get_sessionmaker()() as s:
            row = await s.get(WorkplaceModel, UUID(broken))
            assert row is not None
            row.ready = False
            row.not_ready_reason = "link_unsupported"
            await s.commit()

        listed = await c.get(f"/v1/workspaces/{ws}/workplaces", headers=h)

        assert listed.status_code == 200, listed.text
        assert listed.json() == [
            {"id": usable, "cli_kind": "claude_code", "machine_name": "thinkpad"}
        ]


async def test_the_picker_is_empty_rather_than_angry_when_no_machine_is_linked() -> None:
    """Nothing is wrong — there is simply nowhere to put an agent yet. The screen says so."""
    async with _client() as c:
        h, ws = await _patron(c, "list-empty@armarius.dev")

        listed = await c.get(f"/v1/workspaces/{ws}/workplaces", headers=h)

        assert listed.status_code == 200
        assert listed.json() == []


async def test_the_picker_never_shows_another_persons_machines() -> None:
    async with _client() as c:
        _stranger_h, stranger_ws = await _patron(c, "list-theirs@armarius.dev")
        await ready_workplace(stranger_ws, machine_name="not-yours")

        h, _ws = await _patron(c, "list-ours@armarius.dev")
        peeked = await c.get(f"/v1/workspaces/{stranger_ws}/workplaces", headers=h)

        assert peeked.status_code == 404, peeked.text


# ── what a delete takes with it ──────────────────────────────────────────────


async def test_deleting_an_agent_releases_its_workplace_and_leaves_it_standing() -> None:
    """The workplace belongs to the machine and is shared (FR-007a); one agent leaving is
    not a reason to take it away from the others."""
    async with _client() as c:
        h, ws = await _patron(c, "del-agent@armarius.dev")
        workplace = await ready_workplace(ws)
        leaving = await invite_agent(c, ws, h, name="Leaver", workplace_id=workplace)
        staying = await invite_agent(c, ws, h, name="Stayer", workplace_id=workplace)

        removed = await c.delete(
            f"/v1/workspaces/{ws}/mariuses/{leaving['id']}", headers=h
        )
        assert removed.status_code in (200, 204), removed.text

    assert await _binding_of(leaving["id"]) is None
    assert await _binding_of(staying["id"]) is not None
    async with get_sessionmaker()() as s:
        assert await s.get(WorkplaceModel, UUID(workplace)) is not None


async def test_deleting_a_workspace_takes_its_machines_with_it() -> None:
    """A machine is enrolled into exactly one workspace and means nothing outside it."""
    async with _client() as c:
        h, _first = await _patron(c, "del-ws@armarius.dev")
        # A person's last workspace cannot be deleted, so this one is a second.
        made = await c.post("/v1/workspaces", headers=h, json={"name": "Scratch"})
        ws = made.json()["id"]
        workplace = await ready_workplace(ws)
        await invite_agent(c, ws, h, name="Marin", workplace_id=workplace)

        deleted = await c.delete(f"/v1/workspaces/{ws}", headers=h)
        assert deleted.status_code == 204, deleted.text

    async with get_sessionmaker()() as s:
        left_over = {
            "workplaces": (
                await s.execute(
                    select(WorkplaceModel).where(
                        WorkplaceModel.workspace_id == UUID(ws)
                    )
                )
            ).scalars().all(),
            "machines": (
                await s.execute(
                    select(MachineModel).where(MachineModel.workspace_id == UUID(ws))
                )
            ).scalars().all(),
            "bindings": (
                await s.execute(
                    select(AgentWorkplaceBindingModel).where(
                        AgentWorkplaceBindingModel.workspace_id == UUID(ws)
                    )
                )
            ).scalars().all(),
        }
    assert all(not rows for rows in left_over.values()), left_over
