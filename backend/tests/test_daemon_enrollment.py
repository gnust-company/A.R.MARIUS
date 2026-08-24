"""Linking a machine to a workspace, end to end over the real app (T071, FR-001, FR-014a/d).

Three things have to hold, and the tests below are grouped by which one they defend:

  1. Nobody joins a workspace without a person saying so. A code by itself opens nothing.
  2. A code is good once and for ten minutes — after that it is dead in every direction.
  3. The token that comes out speaks for one machine in one workspace, and the server, not
     the machine, decides when it is renewed (FR-014d).

The clock is swapped rather than waited on: an expiry test that sleeps ten minutes is a
test that gets skipped. Everything else runs against the real app — real router, real
container, real error handlers — so a route wired up wrongly fails here rather than on the
first real machine.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.main import app
from armarius.shared.clock import utcnow

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(c: AsyncClient, email: str) -> tuple[str, str]:
    """A signed-in person and the workspace they own — the only one who may approve."""
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    token = r.json()["tokens"]["access_token"]
    ws = await c.get("/v1/workspaces", headers={"Authorization": f"Bearer {token}"})
    return token, ws.json()[0]["id"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _start(c: AsyncClient, hostname: str = "gnust-thinkpad") -> dict:
    r = await c.post(
        "/daemon/link/start",
        json={"platform": "linux", "daemon_version": "0.1.0", "hostname": hostname},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _shift_clock(offset: timedelta) -> None:
    """Move the enrollment service's own clock, leaving the rest of the app alone."""
    app.state.container.daemon_enrollment._clock = lambda: utcnow() + offset


# ── 1. a person decides ───────────────────────────────────────────────────────


async def test_a_machine_gets_a_code_and_nothing_else_until_someone_approves() -> None:
    async with _client() as c:
        started = await _start(c)
        assert started["code"]
        assert started["verify_url"].endswith("/link")
        assert started["expires_in"] == 600
        assert started["interval"] > 0

        polled = await c.post("/daemon/link/poll", json={"code": started["code"]})
        assert polled.status_code == 202
        assert polled.json() == {
            "status": "pending",
            "machine_id": None,
            "workspace_id": None,
            "token": None,
        }


async def test_the_whole_link_happens_the_way_a_person_walks_through_it() -> None:
    async with _client() as c:
        user, workspace = await _register(c, "link-happy@example.com")
        started = await _start(c)

        # The screen shows what is being approved, so nobody admits a machine they cannot name.
        shown = await c.get(f"/v1/machines/link/{started['code']}", headers=_auth(user))
        assert shown.status_code == 200, shown.text
        assert shown.json()["hostname"] == "gnust-thinkpad"
        assert shown.json()["platform"] == "linux"

        approved = await c.post(
            f"/v1/machines/link/{started['code']}/approve",
            json={"workspace_id": workspace},
            headers=_auth(user),
        )
        assert approved.status_code == 200, approved.text

        got = await c.post("/daemon/link/poll", json={"code": started["code"]})
        assert got.status_code == 200, got.text
        body = got.json()
        assert body["status"] == "approved"
        assert body["workspace_id"] == workspace
        assert body["token"].startswith("armd_")
        assert body["machine_id"]


async def test_a_stranger_cannot_approve_a_machine_into_a_workspace_they_do_not_own() -> None:
    """Not-yours reads exactly like not-there (Constitution I) — a 404, never a 403."""
    async with _client() as c:
        _, workspace = await _register(c, "link-owner@example.com")
        stranger, _ = await _register(c, "link-stranger@example.com")
        started = await _start(c)

        refused = await c.post(
            f"/v1/machines/link/{started['code']}/approve",
            json={"workspace_id": workspace},
            headers=_auth(stranger),
        )
        assert refused.status_code == 404

        # And the code is still waiting, not spent by the failed attempt.
        still_waiting = await c.post("/daemon/link/poll", json={"code": started["code"]})
        assert still_waiting.status_code == 202


async def test_the_approval_screen_is_for_signed_in_people_only() -> None:
    """A short code is guessable given time; this route is what would confirm a guess."""
    async with _client() as c:
        started = await _start(c)
        assert (await c.get(f"/v1/machines/link/{started['code']}")).status_code == 401


async def test_the_code_is_read_the_way_it_was_meant_not_the_way_it_was_punctuated() -> None:
    """The dash is a reading aid this end added; someone retyping it should not be punished."""
    async with _client() as c:
        user, workspace = await _register(c, "link-typing@example.com")
        started = await _start(c)
        typed = started["code"].replace("-", "").lower()

        shown = await c.get(f"/v1/machines/link/{typed}", headers=_auth(user))
        assert shown.status_code == 200, shown.text
        assert shown.json()["code"] == started["code"]

        approved = await c.post(
            f"/v1/machines/link/{typed}/approve",
            json={"workspace_id": workspace},
            headers=_auth(user),
        )
        assert approved.status_code == 200, approved.text


# ── 2. once, and for ten minutes ──────────────────────────────────────────────


async def test_a_code_is_spent_the_moment_it_hands_over_a_token() -> None:
    async with _client() as c:
        user, workspace = await _register(c, "link-once@example.com")
        started = await _start(c)
        await c.post(
            f"/v1/machines/link/{started['code']}/approve",
            json={"workspace_id": workspace},
            headers=_auth(user),
        )

        first = await c.post("/daemon/link/poll", json={"code": started["code"]})
        assert first.status_code == 200
        second = await c.post("/daemon/link/poll", json={"code": started["code"]})
        assert second.status_code == 410
        assert second.json()["status"] == "expired"
        assert second.json()["token"] is None


async def test_two_polls_at_once_still_mint_exactly_one_token() -> None:
    """A daemon retrying a poll it thought had timed out has two calls in flight at once.

    Reading *not spent yet* and writing *spent* are not one instant, so both calls can pass
    the check. Exactly one may come away with a token: a second one would belong to a
    machine row nobody ever heartbeats for, which shows up on the board as a dead machine
    the operator never installed.
    """
    async with _client() as c:
        user, workspace = await _register(c, "link-race@example.com")
        started = await _start(c)
        await c.post(
            f"/v1/machines/link/{started['code']}/approve",
            json={"workspace_id": workspace},
            headers=_auth(user),
        )

        both = await asyncio.gather(
            c.post("/daemon/link/poll", json={"code": started["code"]}),
            c.post("/daemon/link/poll", json={"code": started["code"]}),
        )
        issued = [r for r in both if r.status_code == 200]
        refused = [r for r in both if r.status_code == 410]
        assert len(issued) == 1, [r.status_code for r in both]
        assert len(refused) == 1, [r.status_code for r in both]
        assert issued[0].json()["token"]


async def test_ten_minutes_later_the_code_is_dead_in_both_directions() -> None:
    """Dead for the daemon polling on it *and* for the person who finally opens the screen."""
    async with _client() as c:
        user, workspace = await _register(c, "link-expiry@example.com")
        started = await _start(c)
        try:
            _shift_clock(timedelta(seconds=601))

            polled = await c.post("/daemon/link/poll", json={"code": started["code"]})
            assert polled.status_code == 410
            assert polled.json()["status"] == "expired"

            assert (
                await c.get(f"/v1/machines/link/{started['code']}", headers=_auth(user))
            ).status_code == 404
            assert (
                await c.post(
                    f"/v1/machines/link/{started['code']}/approve",
                    json={"workspace_id": workspace},
                    headers=_auth(user),
                )
            ).status_code == 404
        finally:
            _shift_clock(timedelta(0))


async def test_a_code_nobody_issued_answers_the_same_way_an_expired_one_does() -> None:
    """The three dead ways collapse to one answer: stop polling, run login again."""
    async with _client() as c:
        dead = await c.post("/daemon/link/poll", json={"code": "ZZZZ-ZZZZ"})
        assert dead.status_code == 410
        assert dead.json()["status"] == "expired"


async def test_approving_twice_is_refused_rather_than_quietly_ignored() -> None:
    """The second approver would be giving away a machine they cannot see."""
    async with _client() as c:
        first_user, first_ws = await _register(c, "link-first@example.com")
        second_user, second_ws = await _register(c, "link-second@example.com")
        started = await _start(c)
        await c.post(
            f"/v1/machines/link/{started['code']}/approve",
            json={"workspace_id": first_ws},
            headers=_auth(first_user),
        )
        again = await c.post(
            f"/v1/machines/link/{started['code']}/approve",
            json={"workspace_id": second_ws},
            headers=_auth(second_user),
        )
        assert again.status_code == 409

        # …and the machine still lands in the workspace that approved it first.
        got = await c.post("/daemon/link/poll", json={"code": started["code"]})
        assert got.json()["workspace_id"] == first_ws


# ── 3. the token afterwards ───────────────────────────────────────────────────


async def _link_a_machine(c: AsyncClient, email: str) -> str:
    user, workspace = await _register(c, email)
    started = await _start(c)
    await c.post(
        f"/v1/machines/link/{started['code']}/approve",
        json={"workspace_id": workspace},
        headers=_auth(user),
    )
    got = await c.post("/daemon/link/poll", json={"code": started["code"]})
    return got.json()["token"]


async def test_the_token_opens_the_daemon_doors_and_a_wrong_one_does_not() -> None:
    async with _client() as c:
        token = await _link_a_machine(c, "link-token@example.com")
        assert (await c.post("/daemon/token/renew", headers=_auth(token))).status_code == 200
        assert (await c.post("/daemon/token/renew", headers=_auth("armd_nope"))).status_code == 401
        assert (await c.post("/daemon/token/renew")).status_code == 401


async def test_the_server_says_when_it_is_time_to_renew_not_the_machine() -> None:
    """FR-014d — a fresh token is told *not yet*, and that is a normal answer, not a refusal."""
    async with _client() as c:
        token = await _link_a_machine(c, "link-renew@example.com")

        early = await c.post("/daemon/token/renew", headers=_auth(token))
        assert early.status_code == 200
        assert early.json()["renewed"] is False
        first_expiry = early.json()["expires_at"]

        # Asking again changes nothing. A daemon polling hourly must not walk its own expiry
        # forward one call at a time.
        again = await c.post("/daemon/token/renew", headers=_auth(token))
        assert again.json()["renewed"] is False
        assert again.json()["expires_at"] == first_expiry

        try:
            # Far enough in that the token is inside the renewal window but not yet dead.
            _shift_clock(timedelta(days=80))
            late = await c.post("/daemon/token/renew", headers=_auth(token))
            assert late.json()["renewed"] is True
            assert late.json()["expires_at"] > first_expiry
        finally:
            _shift_clock(timedelta(0))


async def test_an_expired_token_is_no_more_use_than_a_made_up_one() -> None:
    """Both mean *link this machine again*, and the door must not tell them apart."""
    async with _client() as c:
        token = await _link_a_machine(c, "link-stale@example.com")
        try:
            _shift_clock(timedelta(days=91))
            assert (await c.post("/daemon/token/renew", headers=_auth(token))).status_code == 401
        finally:
            _shift_clock(timedelta(0))


async def test_two_machines_linked_to_the_same_workspace_get_different_tokens() -> None:
    async with _client() as c:
        user, workspace = await _register(c, "link-two@example.com")
        tokens = []
        for hostname in ("laptop", "desktop"):
            started = await _start(c, hostname=hostname)
            await c.post(
                f"/v1/machines/link/{started['code']}/approve",
                json={"workspace_id": workspace},
                headers=_auth(user),
            )
            got = await c.post("/daemon/link/poll", json={"code": started["code"]})
            tokens.append(got.json())
        assert tokens[0]["token"] != tokens[1]["token"]
        assert tokens[0]["machine_id"] != tokens[1]["machine_id"]
        assert tokens[0]["workspace_id"] == tokens[1]["workspace_id"] == workspace
