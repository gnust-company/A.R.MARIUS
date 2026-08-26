"""Nhận việc — the one door, and what it refuses (T045, T046, T047, T048, T050).

Before this, a run started because something reached out and started it. That cannot work
when the thing that will do the work is a laptop behind somebody's home router: it is not
reachable, it is asleep half the time, and during an upgrade there are briefly two of it. So
the direction is reversed. Work is put on a shelf; a machine comes and asks; the server hands
over what it can. There is no second way in (FR-053).

Reversing it moves the hard part to the server, which is where FR-054a insists it belongs.
The race is not two machines fighting over one run — every agent is bound to one place, so no
two machines ever see the same work. It is **one** machine asking twice: a push landing on top
of a poll, a reply lost on the way back, two daemons alive for a moment mid-upgrade. Each of
those asks with the same eyes, and each must come back with the work once and only once.

What this file proves that a unit test cannot: the door works through the real app, with the
real container behind it, and the shelf it reads is the same table the rest of the system
writes. That two asks landing *at the same instant* still yield one grant is a different
question with a different answer — SQLite serialises writers and so cannot even stage it —
and it is asked against a real Postgres in `test_run_claim_races.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from armarius.application.ports.adapter import ExecContext
from armarius.domain.entities.project import ProjectStatus
from armarius.domain.entities.run import RunStatus
from armarius.infrastructure.daemon.models import (
    MachineModel,
    RunClaimModel,
    WorkplaceModel,
)
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import ProjectModel, RunModel
from armarius.main import app
from armarius.shared.clock import utcnow
from tests.support.agents import invite_agent

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@dataclass
class Box:
    """One machine, linked and offering one CLI, with one agent living on it."""

    token: str
    workspace_id: str
    machine_id: UUID
    workplace_id: str
    marius_id: str
    headers: dict


async def _box(c: AsyncClient, email: str, *, hostname: str = "thinkpad") -> Box:
    """The whole chain a real setup goes through, with nothing shortcut.

    Person registers, machine asks to be let in, person approves, machine reports what it
    found, person puts an agent on it. Every later assertion in this file rests on that
    chain being genuine — a hand-written row would prove the door works on rows the door
    itself would never have produced.
    """
    registered = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    person = _auth(registered.json()["tokens"]["access_token"])
    workspaces = await c.get("/v1/workspaces", headers=person)
    workspace_id = workspaces.json()[0]["id"]

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
                    "cli_kind": "claude_code",
                    "cli_version": "1.0.0",
                    "protocol_family": "one_shot",
                    "capabilities": {"resumable": True},
                }
            ],
            "symlink_capable": True,
        },
        headers=_auth(token),
    )
    assert synced.status_code == 200, synced.text
    workplace_id = synced.json()["workplaces"][0]["id"]

    agent = await invite_agent(
        c, workspace_id, person, name=hostname, workplace_id=workplace_id
    )
    async with get_sessionmaker()() as session:
        machine_id = (
            await session.execute(
                select(MachineModel.id).where(
                    MachineModel.workspace_id == UUID(workspace_id)
                )
            )
        ).scalar_one()
    return Box(
        token=token,
        workspace_id=workspace_id,
        machine_id=machine_id,
        workplace_id=workplace_id,
        marius_id=agent["id"],
        headers=person,
    )


async def _project(box: Box, *, closed: bool) -> UUID:
    project_id = uuid4()
    async with get_sessionmaker()() as session:
        session.add(
            ProjectModel(
                id=project_id,
                workspace_id=UUID(box.workspace_id),
                name="Apollo",
                slug=f"apollo-{project_id.hex[:6]}",
                key=project_id.hex[:6].upper(),
                status=ProjectStatus.CLOSED.value
                if closed
                else ProjectStatus.OPERATING.value,
                created_at=utcnow(),
            )
        )
        await session.commit()
    return project_id


async def _close(project_id: UUID) -> None:
    async with get_sessionmaker()() as session:
        await session.execute(
            update(ProjectModel)
            .where(ProjectModel.id == project_id)
            .values(status=ProjectStatus.CLOSED.value)
        )
        await session.commit()


async def _offer(
    box: Box, *, task_id: UUID | None = None, project_id: UUID | None = None
) -> UUID:
    """Put one run on the shelf the way the system does it — through the adapter.

    Writing the shelf row by hand would test the door against rows nothing produces. This
    goes through `DaemonAdapter.dispatch`, which is the only thing that ever writes them.
    """
    run_id = uuid4()
    async with get_sessionmaker()() as session:
        session.add(
            RunModel(
                id=run_id,
                project_id=project_id,
                marius_id=UUID(box.marius_id),
                task_id=task_id,
                adapter_type="daemon",
                status=RunStatus.QUEUED.value,
                created_at=utcnow(),
            )
        )
        await session.commit()
    adapter = app.state.container.registry.get("daemon")
    result = await adapter.dispatch(
        ExecContext(
            prompt="",
            adapter_config={},
            marius_id=UUID(box.marius_id),
            task_id=task_id,
            run_id=run_id,
        )
    )
    assert result.status is RunStatus.QUEUED, "dispatch phải để việc lại, không chạy gì"
    return run_id


async def _claim(c: AsyncClient, box: Box, *, max_runs: int = 1) -> list[dict]:
    answered = await c.post(
        "/daemon/runs/claim",
        json={"workplace_ids": [box.workplace_id], "max": max_runs},
        headers=_auth(box.token),
    )
    assert answered.status_code == 200, answered.text
    return answered.json()["runs"]


async def _ceiling(box: Box, allowed: int) -> None:
    async with get_sessionmaker()() as session:
        await session.execute(
            update(MachineModel)
            .where(MachineModel.id == box.machine_id)
            .values(max_concurrent=allowed)
        )
        await session.commit()


async def _let_the_hold_lapse(run_id: UUID) -> None:
    """Wind this run's deadline into the past rather than waiting two minutes for it.

    The hold is a comparison against a stored moment, so moving the moment tests exactly
    what the passage of time would, and does it in a millisecond.
    """
    async with get_sessionmaker()() as session:
        await session.execute(
            update(RunClaimModel)
            .where(RunClaimModel.run_id == run_id)
            .values(claim_expires_at=utcnow() - timedelta(seconds=1))
        )
        await session.commit()


async def _finish(run_id: UUID) -> None:
    async with get_sessionmaker()() as session:
        await session.execute(
            update(RunModel)
            .where(RunModel.id == run_id)
            .values(status=RunStatus.COMPLETED.value, finished_at=utcnow())
        )
        await session.commit()


async def _claim_row(run_id: UUID) -> RunClaimModel | None:
    async with get_sessionmaker()() as session:
        return await session.get(RunClaimModel, run_id)


async def _run_row(run_id: UUID) -> RunModel | None:
    async with get_sessionmaker()() as session:
        return await session.get(RunModel, run_id)


async def _seen_at(marius_id: str):
    async with app.state.container.uow_factory() as uow:
        marius = await uow.mariuses.get(UUID(marius_id))
    assert marius is not None
    return marius.last_seen_at


# ── 1. the door itself ────────────────────────────────────────────────────────


# Handing work out is putting it down, not calling anybody. Nothing about the run changes at
# dispatch: it is queued, nobody has accepted it, and it stays that way until a machine comes
# and asks. That gap is the whole shape of the path (FR-009, FR-053).
async def test_handing_work_out_starts_nothing() -> None:
    async with _client() as c:
        box = await _box(c, "claim-quiet@example.com")

        run_id = await _offer(box)

        run = await _run_row(run_id)
        assert run is not None
        assert run.status == RunStatus.QUEUED.value
        assert run.accepted_at is None, "chưa máy nào nhận mà đã đánh dấu là có người nhận"
        claim = await _claim_row(run_id)
        assert claim is not None and claim.machine_id is None
        assert claim.workplace_id == UUID(box.workplace_id)


async def test_a_machine_that_asks_is_given_the_work_waiting_for_it() -> None:
    async with _client() as c:
        box = await _box(c, "claim-take@example.com")
        run_id = await _offer(box)

        granted = await _claim(c, box)

        assert [UUID(g["run_id"]) for g in granted] == [run_id]
        assert granted[0]["workplace_id"] == box.workplace_id
        run = await _run_row(run_id)
        assert run is not None and run.accepted_at is not None, (
            "nhận việc rồi thì phải có mốc nhận — động cơ đẩy số 1 bật từ đấy (FR-056)"
        )


# The race FR-054 exists for, in the only form it actually takes: one machine asking twice.
# The second ask has to come back empty-handed. If it came back holding the same run, two
# copies of the same work would start on the same machine.
async def test_asking_twice_takes_the_work_once() -> None:
    async with _client() as c:
        box = await _box(c, "claim-twice@example.com")
        await _ceiling(box, 4)
        run_id = await _offer(box)

        first = await _claim(c, box, max_runs=4)
        second = await _claim(c, box, max_runs=4)

        assert [UUID(g["run_id"]) for g in first] == [run_id]
        assert second == [], "cú xin thứ hai lấy lại đúng việc cú thứ nhất đã cầm"


async def test_an_empty_shelf_is_an_answer_not_a_complaint() -> None:
    async with _client() as c:
        box = await _box(c, "claim-empty@example.com")

        assert await _claim(c, box) == []


# ── 2. how much, and who decides ──────────────────────────────────────────────


async def test_a_machine_is_never_given_more_than_it_said_it_could_take() -> None:
    async with _client() as c:
        box = await _box(c, "claim-slots@example.com")
        await _ceiling(box, 10)
        for _ in range(3):
            await _offer(box)

        granted = await _claim(c, box, max_runs=2)

        assert len(granted) == 2


# The machine's number is advice and the ceiling is the rule (FR-008d). A daemon reporting
# ten free slots on a machine allowed one gets one — otherwise a wrong or stale report from
# the machine is enough to bury it.
async def test_the_ceiling_wins_when_the_machine_claims_more_room_than_it_has() -> None:
    async with _client() as c:
        box = await _box(c, "claim-ceiling@example.com")
        await _ceiling(box, 1)
        for _ in range(3):
            await _offer(box)

        granted = await _claim(c, box, max_runs=10)

        assert len(granted) == 1


# What happens to the work that did not fit is the whole of FR-008a/FR-008c: nothing. It is
# not cancelled, not re-queued, not booked for a retry. It sits where it was, and the next
# ask with room takes it. That last sentence is the behaviour — the two before it are only
# the absence of behaviour, which is easy to claim and easy to get wrong.
async def test_work_that_did_not_fit_is_waiting_at_the_next_ask() -> None:
    async with _client() as c:
        box = await _box(c, "claim-overflow@example.com")
        await _ceiling(box, 1)
        first_id = await _offer(box)
        second_id = await _offer(box)

        taken = await _claim(c, box, max_runs=10)
        assert [UUID(g["run_id"]) for g in taken] == [first_id]

        left = await _claim_row(second_id)
        assert left is not None, "việc quá trần bị xoá mất"
        assert left.machine_id is None and left.claimed_at is None
        overflowed = await _run_row(second_id)
        assert overflowed is not None and overflowed.status == RunStatus.QUEUED.value

        # The machine finishes the first and comes back. This is the only retry there is.
        await _finish(first_id)
        again = await _claim(c, box, max_runs=10)
        assert [UUID(g["run_id"]) for g in again] == [second_id]


# ── 3. whose work it is ───────────────────────────────────────────────────────


async def test_work_waiting_at_another_machine_is_not_offered_here() -> None:
    async with _client() as c:
        mine = await _box(c, "claim-mine@example.com", hostname="mine")
        theirs = await _box(c, "claim-theirs@example.com", hostname="theirs")
        await _offer(theirs)

        assert await _claim(c, mine) == []


# A workplace id the machine names but does not own is dropped rather than refused. The
# machine learns nothing about whether the id is real (Constitution I), and naming one is not
# even wrong — a daemon mid-upgrade may still be carrying a stale list.
async def test_naming_a_workplace_that_is_not_yours_simply_finds_nothing() -> None:
    async with _client() as c:
        mine = await _box(c, "claim-stale@example.com", hostname="mine")
        theirs = await _box(c, "claim-stale2@example.com", hostname="theirs")
        await _offer(theirs)

        answered = await c.post(
            "/daemon/runs/claim",
            json={"workplace_ids": [theirs.workplace_id], "max": 5},
            headers=_auth(mine.token),
        )

        assert answered.status_code == 200
        assert answered.json()["runs"] == []


# ── 4. saying it started ──────────────────────────────────────────────────────


async def test_the_machine_holding_the_work_may_say_it_started() -> None:
    async with _client() as c:
        box = await _box(c, "start-ok@example.com")
        run_id = await _offer(box)
        await _claim(c, box)

        answered = await c.post(
            f"/daemon/runs/{run_id}/start",
            json={"session_handle": "sess-1"},
            headers=_auth(box.token),
        )

        assert answered.status_code == 200, answered.text
        run = await _run_row(run_id)
        assert run is not None and run.status == RunStatus.RUNNING.value
        assert run.started_at is not None


# FR-058 and FR-059 in one answer. A machine whose grip lapsed while it was setting up has to
# be told to stop, and *not found* is the right way to tell it: whatever it started is no
# longer this system's run, and there is nothing to negotiate.
async def test_a_machine_that_lost_the_work_cannot_say_it_started() -> None:
    async with _client() as c:
        box = await _box(c, "start-lost@example.com")
        run_id = await _offer(box)
        await _claim(c, box)
        await _let_the_hold_lapse(run_id)
        await app.state.container.daemon_claims.reap()

        answered = await c.post(
            f"/daemon/runs/{run_id}/start", json={}, headers=_auth(box.token)
        )

        assert answered.status_code == 404, answered.text


# The window between a hold running out and the sweep noticing is up to one sweep long, and a
# machine that finishes setting up inside it must still be refused. Otherwise it starts an
# agent on work the sweep is about to put back, and the same run goes out a second time — the
# exact double-run FR-058 exists to prevent. The hold is the answer here, not the sweep: the
# grip is over the moment the deadline passes, whether or not anybody has tidied up yet.
async def test_a_hold_that_ran_out_refuses_the_start_before_the_sweep_has_run() -> None:
    async with _client() as c:
        box = await _box(c, "start-lapsed@example.com")
        run_id = await _offer(box)
        await _claim(c, box)
        await _let_the_hold_lapse(run_id)

        answered = await c.post(
            f"/daemon/runs/{run_id}/start", json={}, headers=_auth(box.token)
        )

        assert answered.status_code == 404, answered.text
        still_ours = await _claim_row(run_id)
        assert still_ours is not None and still_ours.machine_id == box.machine_id, (
            "cửa này chỉ từ chối, việc dọn là của vòng quét"
        )


async def test_a_machine_cannot_say_a_run_it_never_held_has_started() -> None:
    async with _client() as c:
        mine = await _box(c, "start-other@example.com", hostname="mine")
        theirs = await _box(c, "start-other2@example.com", hostname="theirs")
        run_id = await _offer(theirs)
        await _claim(c, theirs)

        answered = await c.post(
            f"/daemon/runs/{run_id}/start", json={}, headers=_auth(mine.token)
        )

        assert answered.status_code == 404, answered.text


# A reply that never arrived is the second of FR-054b's three races. The machine repeats
# itself, and repeating has to be safe — being sent to clean up a healthy run because the
# first answer was lost would be the very failure the retry was trying to avoid.
async def test_saying_it_started_twice_is_not_an_error() -> None:
    async with _client() as c:
        box = await _box(c, "start-again@example.com")
        run_id = await _offer(box)
        await _claim(c, box)

        first = await c.post(
            f"/daemon/runs/{run_id}/start", json={}, headers=_auth(box.token)
        )
        second = await c.post(
            f"/daemon/runs/{run_id}/start", json={}, headers=_auth(box.token)
        )

        assert (first.status_code, second.status_code) == (200, 200), second.text


# ── 5. losing the work again ──────────────────────────────────────────────────


# FR-056a. A machine that took work and died while getting ready must not hold it forever —
# and FR-007d says the token dies with the hold, or a machine that wakes up late can still
# write to work it no longer owns.
async def test_a_hold_that_ran_out_puts_the_work_back_and_kills_the_token() -> None:
    async with _client() as c:
        box = await _box(c, "reap-back@example.com")
        run_id = await _offer(box)
        granted = await _claim(c, box)
        assert granted[0]["run_token"]

        await _let_the_hold_lapse(run_id)
        await app.state.container.daemon_claims.reap()

        claim = await _claim_row(run_id)
        assert claim is not None
        assert claim.machine_id is None, "hết hạn giữ mà việc vẫn mang tên máy cũ"
        assert claim.run_token_hash is None, "thu hồi việc mà không thu hồi token"
        run = await _run_row(run_id)
        assert run is not None and run.accepted_at is None
        assert run.status == RunStatus.QUEUED.value


async def test_work_put_back_can_be_taken_again() -> None:
    async with _client() as c:
        box = await _box(c, "reap-retake@example.com")
        run_id = await _offer(box)
        first = await _claim(c, box)
        await _let_the_hold_lapse(run_id)

        again = await _claim(c, box)

        assert [UUID(g["run_id"]) for g in again] == [run_id]
        assert again[0]["run_token"] != first[0]["run_token"], (
            "lượt giữ mới phải có token mới — token cũ đã bị thu hồi cùng lượt giữ cũ"
        )


# The countdown covers getting ready and nothing else (FR-056a). Once the agent is up there
# is something real watching the run — its own silence — and a countdown still ticking would
# take a perfectly healthy run away from the machine two minutes in.
async def test_a_started_run_is_not_taken_back_by_the_clock() -> None:
    async with _client() as c:
        box = await _box(c, "reap-running@example.com")
        run_id = await _offer(box)
        await _claim(c, box)
        await c.post(f"/daemon/runs/{run_id}/start", json={}, headers=_auth(box.token))

        released = await app.state.container.daemon_claims.reap()

        assert run_id not in released
        claim = await _claim_row(run_id)
        assert claim is not None and claim.machine_id == box.machine_id


# The sweep exists for the machine that never comes back. Every agent is bound to one place,
# so if that machine stays dark nobody else will ever ask on this task's behalf, and the
# release that happens inside an ask would never happen at all.
async def test_a_machine_that_never_asks_again_still_loses_the_work() -> None:
    async with _client() as c:
        box = await _box(c, "reap-sweep@example.com")
        run_id = await _offer(box)
        await _claim(c, box)
        await _let_the_hold_lapse(run_id)

        released = await app.state.container.daemon_claims.reap()

        assert released == [run_id]


# ── 6. the token ──────────────────────────────────────────────────────────────


# FR-014a: the run's token is minted at the moment the work is handed over, shown once, and
# kept only as a hash. Anything else stored would be a second copy of a secret whose whole
# value is that there is only one.
async def test_the_run_token_is_shown_once_and_kept_only_as_a_hash() -> None:
    async with _client() as c:
        box = await _box(c, "token-once@example.com")
        run_id = await _offer(box)

        granted = await _claim(c, box)

        token = granted[0]["run_token"]
        assert token.startswith("armr_run_")
        claim = await _claim_row(run_id)
        assert claim is not None and claim.run_token_hash
        assert claim.run_token_hash != token
        assert token not in claim.run_token_hash


async def test_every_run_gets_a_token_of_its_own() -> None:
    async with _client() as c:
        box = await _box(c, "token-each@example.com")
        await _ceiling(box, 3)
        for _ in range(3):
            await _offer(box)

        granted = await _claim(c, box, max_runs=3)

        tokens = {g["run_token"] for g in granted}
        assert len(tokens) == 3, (
            "ba lượt chạy dùng chung một token là ba lượt mở chung một cửa"
        )


# ── 7. what asking does not prove ─────────────────────────────────────────────


# FR-055b, one layer further down than where it was proved for the beat. Asking for work
# proves the *machine* is reachable. It proves nothing about whether an agent CLI on that
# machine can run, and an agent left online by an ask is an agent that stays online forever
# after somebody uninstalls its CLI.
async def test_asking_for_work_does_not_make_the_agent_look_alive() -> None:
    async with _client() as c:
        box = await _box(c, "claim-liveness@example.com")
        await _offer(box)
        before = await _seen_at(box.marius_id)

        await _claim(c, box)

        assert await _seen_at(box.marius_id) == before


# ── 8. the place an agent was put in decides where its work waits ─────────────


async def test_work_waits_at_the_place_its_agent_was_put_in() -> None:
    async with _client() as c:
        box = await _box(c, "claim-place@example.com")

        run_id = await _offer(box)

        async with get_sessionmaker()() as session:
            workplace = await session.get(WorkplaceModel, UUID(box.workplace_id))
        claim = await _claim_row(run_id)
        assert workplace is not None and claim is not None
        assert claim.workplace_id == workplace.id
        assert claim.workspace_id == UUID(box.workspace_id)


# ── 9. a closed project is history, and history starts nothing ────────────────


# The freeze normally lives at the door, and this door cannot carry it: an ask is one machine
# asking about everything it hosts, so refusing the whole ask over one closed project would
# freeze unrelated work on the same machine. It lives in the statement instead — and a rule
# that lives somewhere unusual is a rule that has to be shown working.
async def test_work_left_over_from_a_project_that_has_since_closed_is_not_handed_out() -> (
    None
):
    async with _client() as c:
        box = await _box(c, "claim-closed@example.com")
        await _ceiling(box, 4)
        project_id = await _project(box, closed=False)
        stranded = await _offer(box, project_id=project_id)
        live = await _offer(box)

        await _close(project_id)
        granted = await _claim(c, box, max_runs=4)

        assert [UUID(g["run_id"]) for g in granted] == [live]
        left = await _claim_row(stranded)
        assert left is not None and left.machine_id is None, (
            "việc của dự án đã đóng không được trao, nhưng cũng không bị xoá"
        )
