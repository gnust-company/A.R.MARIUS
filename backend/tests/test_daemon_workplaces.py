"""A machine says what it can run, and keeps saying it is there (T082a, FR-002…FR-004, FR-033).

Two doors, one subject. `PUT /daemon/workplaces` is the machine's whole list of agent CLIs,
resent every time rather than diffed — which is the only way a CLI that *left* is ever visible.
`POST /daemon/heartbeat` is the beat that keeps the machine reachable, and the answer that
tells it where to look next.

The rule the whole file circles is that **nothing is deleted**. An agent is bound to its
workplace for life (FR-007), so a CLI someone uninstalled turns the workplace not-ready with a
reason and keeps the row. Deleting it would leave every agent that lived there pointing at
nothing, offline for a reason nobody could name.

Everything runs against the real app — real routes, real container, real error handlers — so a
route wired up wrongly fails here and not on the first real machine.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from armarius.infrastructure.daemon.models import RunClaimModel, WorkplaceModel
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import RunModel
from armarius.main import app
from armarius.shared.clock import utcnow

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _linked_machine(
    c: AsyncClient, email: str, hostname: str = "gnust-thinkpad"
) -> tuple[str, str]:
    """One machine admitted to one workspace, the way a person actually does it.

    Returns the machine's own token and the workspace it landed in. Nothing here shortcuts
    the device flow: the token this hands back is the one a real daemon would be holding.
    """
    registered = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    person = registered.json()["tokens"]["access_token"]
    workspaces = await c.get("/v1/workspaces", headers=_auth(person))
    workspace = workspaces.json()[0]["id"]

    started = await c.post(
        "/daemon/link/start",
        json={"platform": "linux", "daemon_version": "0.1.0", "hostname": hostname},
    )
    code = started.json()["code"]
    approved = await c.post(
        f"/v1/machines/link/{code}/approve",
        json={"workspace_id": workspace},
        headers=_auth(person),
    )
    assert approved.status_code == 200, approved.text
    polled = await c.post("/daemon/link/poll", json={"code": code})
    assert polled.status_code == 200, polled.text
    return polled.json()["token"], workspace


def _cli(kind: str, **overrides: object) -> dict:
    body: dict = {
        "cli_kind": kind,
        "cli_version": "1.0.0",
        "protocol_family": "one_shot",
        "capabilities": {
            "resumable": True,
            "exposes_tool_args": True,
            "exposes_tool_result": True,
        },
    }
    body.update(overrides)
    return body


async def _sync(c: AsyncClient, token: str, *clis: dict, symlink: bool = True):
    return await c.put(
        "/daemon/workplaces",
        json={"workplaces": list(clis), "symlink_capable": symlink},
        headers=_auth(token),
    )


# ── 1. what a machine offers ──────────────────────────────────────────────────


async def test_a_machine_registers_the_clis_it_found() -> None:
    async with _client() as c:
        machine, _ = await _linked_machine(c, "wp-register@example.com")

        answered = await _sync(c, machine, _cli("claude_code"), _cli("gemini"))

        assert answered.status_code == 200, answered.text
        offered = answered.json()["workplaces"]
        assert [w["cli_kind"] for w in offered] == ["claude_code", "gemini"]
        assert all(w["ready"] for w in offered)
        assert all(w["not_ready_reason"] is None for w in offered)
        assert all(UUID(w["id"]) for w in offered)


# Two of a person's machines both run Claude Code, and the workplaces have to be tellable
# apart on sight (FR-003). The name is the machine's, carried onto every workplace on it.
async def test_every_workplace_carries_the_machines_readable_name() -> None:
    async with _client() as c:
        machine, _ = await _linked_machine(
            c, "wp-name@example.com", hostname="gnust-thinkpad"
        )

        answered = await _sync(c, machine, _cli("claude_code"))

        assert answered.json()["workplaces"][0]["machine_name"] == "gnust-thinkpad"


# The whole point of asking a CLI what it can do is that the answer is kept as given (FR-017).
# A stored capability set that is not what the machine reported is a guess wearing an answer's
# clothes — including the part that says a question could not be asked at all.
async def test_the_capabilities_stored_are_the_ones_the_machine_reported() -> None:
    async with _client() as c:
        machine, _ = await _linked_machine(c, "wp-caps@example.com")
        unasked = {
            "resumable": False,
            "exposes_tool_args": False,
            "exposes_tool_result": False,
            "unanswered": [
                {"capability": "resumable", "reason": "no_probe_for_family"},
            ],
        }

        await _sync(
            c,
            machine,
            _cli("gemini", protocol_family="acp", capabilities=unasked),
        )

        async with get_sessionmaker()() as session:
            stored = await session.execute(
                select(WorkplaceModel).where(WorkplaceModel.cli_kind == "gemini")
            )
            row = stored.scalar_one()
        assert row.capabilities == unasked
        assert row.protocol_family == "acp"


# ── 2. a CLI that leaves ──────────────────────────────────────────────────────


# FR-033, and the reason this file exists. The row survives, keeps its id, and says why it
# stopped being offered work — because agents are bound to it and the binding never moves.
async def test_a_cli_that_disappears_turns_not_ready_and_keeps_its_row() -> None:
    async with _client() as c:
        machine, _ = await _linked_machine(c, "wp-gone@example.com")
        before = await _sync(c, machine, _cli("claude_code"), _cli("codex"))
        ids = {w["cli_kind"]: w["id"] for w in before.json()["workplaces"]}

        after = await _sync(c, machine, _cli("claude_code"))

        offered = {w["cli_kind"]: w for w in after.json()["workplaces"]}
        assert set(offered) == {"claude_code", "codex"}, "the row must not be deleted"
        assert offered["codex"]["id"] == ids["codex"], "and it must keep its identity"
        assert offered["codex"]["ready"] is False
        assert offered["codex"]["not_ready_reason"] == "cli_removed"
        assert offered["claude_code"]["ready"] is True


async def test_a_cli_that_comes_back_is_offered_work_again() -> None:
    async with _client() as c:
        machine, _ = await _linked_machine(c, "wp-back@example.com")
        before = await _sync(c, machine, _cli("codex"))
        was = before.json()["workplaces"][0]["id"]
        await _sync(c, machine, _cli("claude_code"))

        after = await _sync(c, machine, _cli("claude_code"), _cli("codex"))

        offered = {w["cli_kind"]: w for w in after.json()["workplaces"]}
        assert offered["codex"]["id"] == was, "the same workplace, not a second one"
        assert offered["codex"]["ready"] is True
        assert offered["codex"]["not_ready_reason"] is None


# research.md §5: a machine that cannot make a symbolic link cannot keep an agent's session
# state, and a copy would lose it silently. So it says so, loudly, on every workplace it has.
async def test_a_machine_that_cannot_link_offers_nothing_ready() -> None:
    async with _client() as c:
        machine, _ = await _linked_machine(c, "wp-nolink@example.com")

        answered = await _sync(
            c, machine, _cli("claude_code"), _cli("gemini"), symlink=False
        )

        offered = answered.json()["workplaces"]
        assert all(w["ready"] is False for w in offered)
        assert all(w["not_ready_reason"] == "link_unsupported" for w in offered)


# A machine sweeps one PATH and cannot find the same CLI twice. Collapsing the duplicate would
# mean deciding, for the caller, which of two disagreeing entries was meant.
async def test_the_same_cli_reported_twice_is_refused_with_a_code() -> None:
    async with _client() as c:
        machine, _ = await _linked_machine(c, "wp-twice@example.com")

        refused = await _sync(
            c, machine, _cli("claude_code"), _cli("claude_code", cli_version="2.0.0")
        )

        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "workplace_reported_twice"
        assert refused.json()["params"]["cli_kind"] == "claude_code"


# ── 3. who is allowed to see any of this ──────────────────────────────────────


async def test_a_machine_only_ever_sees_its_own_workplaces() -> None:
    async with _client() as c:
        mine, _ = await _linked_machine(c, "wp-mine@example.com", hostname="mine")
        theirs, _ = await _linked_machine(c, "wp-theirs@example.com", hostname="theirs")

        await _sync(c, mine, _cli("claude_code"), _cli("codex"))
        answered = await _sync(c, theirs, _cli("gemini"))

        offered = answered.json()["workplaces"]
        assert [w["cli_kind"] for w in offered] == ["gemini"]
        assert offered[0]["machine_name"] == "theirs"


async def test_neither_door_opens_without_a_machine_token() -> None:
    async with _client() as c:
        assert (
            await c.put("/daemon/workplaces", json={"workplaces": []})
        ).status_code == 401
        assert (await c.post("/daemon/heartbeat", json={})).status_code == 401


# ── 4. the beat ───────────────────────────────────────────────────────────────


async def _beat(c: AsyncClient, token: str, *, free_slots: int = 3, running=()):
    return await c.post(
        "/daemon/heartbeat",
        json={"free_slots": free_slots, "running": [str(r) for r in running]},
        headers=_auth(token),
    )


async def _put_claim(*, run_id: UUID, workspace: str, workplace: UUID, machine) -> None:
    """A claim row of the shape the claim door will write (T045), placed by hand.

    `runs` carries no foreign keys to project or agent, so a bare run row is enough to hang a
    claim on — which keeps this file about workplaces and beats rather than about planning.
    """
    async with get_sessionmaker()() as session:
        session.add(RunModel(id=run_id, status="queued", created_at=utcnow()))
        await session.flush()
        session.add(
            RunClaimModel(
                run_id=run_id,
                workspace_id=UUID(workspace),
                workplace_id=workplace,
                machine_id=machine,
                claimed_at=utcnow() if machine else None,
            )
        )
        await session.commit()


async def test_a_beat_with_nothing_waiting_says_there_is_nothing_waiting() -> None:
    async with _client() as c:
        machine, _ = await _linked_machine(c, "hb-quiet@example.com")
        await _sync(c, machine, _cli("claude_code"))

        beat = await _beat(c, machine)

        assert beat.status_code == 200, beat.text
        assert beat.json() == {"pending_work": False, "cancel": []}


async def test_work_waiting_on_this_machines_workplace_is_announced() -> None:
    async with _client() as c:
        machine, workspace = await _linked_machine(c, "hb-work@example.com")
        synced = await _sync(c, machine, _cli("claude_code"))
        workplace = UUID(synced.json()["workplaces"][0]["id"])
        await _put_claim(
            run_id=uuid4(), workspace=workspace, workplace=workplace, machine=None
        )

        beat = await _beat(c, machine)

        assert beat.json()["pending_work"] is True


# FR-008d: telling a full machine that work is waiting is noise. It cannot take the work, and
# the ask it would prompt comes back empty. The number is used where it is freshest and stored
# nowhere, because a stored copy is wrong from the next beat onwards.
async def test_a_full_machine_is_not_told_to_come_and_ask() -> None:
    async with _client() as c:
        machine, workspace = await _linked_machine(c, "hb-full@example.com")
        synced = await _sync(c, machine, _cli("claude_code"))
        workplace = UUID(synced.json()["workplaces"][0]["id"])
        await _put_claim(
            run_id=uuid4(), workspace=workspace, workplace=workplace, machine=None
        )

        beat = await _beat(c, machine, free_slots=0)

        assert beat.json()["pending_work"] is False


# FR-059's net, moved one step earlier. A machine whose lease was taken away will have every
# write refused anyway; being told now saves it producing them.
async def test_a_machine_is_told_to_stop_a_run_it_no_longer_holds() -> None:
    async with _client() as c:
        machine, workspace = await _linked_machine(c, "hb-stop@example.com")
        synced = await _sync(c, machine, _cli("claude_code"))
        workplace = UUID(synced.json()["workplaces"][0]["id"])

        held = uuid4()
        taken_back = uuid4()
        unknown = uuid4()
        mine = await _machine_id(machine)
        await _put_claim(
            run_id=held, workspace=workspace, workplace=workplace, machine=mine
        )
        await _put_claim(
            run_id=taken_back, workspace=workspace, workplace=workplace, machine=None
        )

        beat = await _beat(c, machine, running=[held, taken_back, unknown])

        assert beat.json()["cancel"] == [str(taken_back), str(unknown)]


async def _machine_id(token: str) -> UUID:
    """The id behind a machine token, resolved the way every `/daemon/*` route resolves it."""
    identity = await app.state.container.daemon_enrollment.authenticate(token)
    assert identity is not None
    return identity.machine_id


async def test_a_beat_records_that_the_machine_is_still_there() -> None:
    async with _client() as c:
        machine, _ = await _linked_machine(c, "hb-alive@example.com")
        before = await _last_beat(machine)
        assert before is None

        await _beat(c, machine)

        assert await _last_beat(machine) is not None


async def _last_beat(token: str):
    from armarius.infrastructure.daemon.models import MachineModel

    machine_id = await _machine_id(token)
    async with get_sessionmaker()() as session:
        row = await session.get(MachineModel, machine_id)
        assert row is not None
        return row.last_heartbeat_at
