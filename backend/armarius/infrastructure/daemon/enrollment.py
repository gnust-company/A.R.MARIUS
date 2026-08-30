"""Linking a machine to a workspace, and keeping its token alive (FR-001, FR-014a/d).

The shape is the device flow argued for in research.md §1: the daemon prints a short code
and waits; a person opens Armarius in whatever browser they already have and approves it;
the daemon's next poll comes back with its token. Nobody copies a secret through a
clipboard, and a machine reachable only over SSH links exactly as easily as a laptop.

Everything here is infrastructure and stays there (Constitution III). A machine and its
token are facts about *where* work runs, and no rule above the adapter contract is allowed
to know that such a place exists — so this service talks to its own tables through its own
session rather than joining the unit of work, whose port lives in the application layer
and may not learn these words.

Two secrets pass through this module and neither is ever stored in the clear:

  * the **link code** is short because a person retypes it, and therefore lives only ten
    minutes, is good for exactly one use, and grants nothing by itself — approving it
    still requires a signed-in human who owns the workspace.
  * the **machine token** is long, is shown once at the moment it is minted, and is kept
    only as a hash. A leaked one speaks for the whole machine (FR-014c), which is why the
    run tokens handed to agents are a different thing entirely.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import CursorResult, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from armarius.infrastructure.daemon.models import DaemonLinkCodeModel, MachineModel
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.shared.clock import as_utc, utcnow
from armarius.shared.config import settings
from armarius.shared.errors import Conflict, NotFound

# Digits and letters minus the two pairs a person copying off a screen gets wrong: 0/O
# and 1/I. A code is typed by hand, so an alphabet that cannot be misread is worth more
# than the handful of extra combinations the excluded characters would buy.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_HALF = 4

# How many times a collision on the unique index is worth retrying before giving up. With
# a 32-character alphabet over 8 positions a clash is already vanishingly unlikely; the
# retry exists so that the unlikely case is a second draw rather than a 500.
_CODE_ATTEMPTS = 5

#: How a machine token starts. Public because the run door has to recognise one arriving
#: somewhere it never belongs (FR-048), and a second copy of this string is a second copy
#: to drift.
MACHINE_TOKEN_PREFIX = "armd_"


def _hash_token(token: str) -> str:
    """The only form of a machine token this system keeps."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_code() -> str:
    """A short code in the `KQ7F-M2XD` shape — grouped so it is read and typed in halves."""
    draw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_HALF * 2))
    return f"{draw[:_CODE_HALF]}-{draw[_CODE_HALF:]}"


def _normalise_code(typed: str) -> str:
    """Read a hand-typed code the way it was meant, not the way it was punctuated.

    The dash is a reading aid this end put in; someone typing `kq7fm2xd`, or pasting it with
    a space, means the same code and should not be told there is no such thing. Anything
    outside the alphabet is dropped rather than rejected, and the canonical dash is put back
    so the lookup has one shape to match.
    """
    kept = [ch for ch in typed.upper() if ch in _CODE_ALPHABET]
    if len(kept) != _CODE_HALF * 2:
        # Not a code-shaped string at all. Hand it back roughly as typed so the refusal is
        # about the code that was entered rather than about some cleaned-up version of it.
        return typed.strip().upper()
    return f"{''.join(kept[:_CODE_HALF])}-{''.join(kept[_CODE_HALF:])}"


@dataclass(frozen=True)
class LinkStarted:
    """What the daemon is told when it asks to be linked. Carries no secret but the code."""

    code: str
    expires_in_seconds: int
    poll_interval_seconds: int


@dataclass(frozen=True)
class PendingLink:
    """What the approval screen shows about the machine asking to join.

    All three values are what the machine *claimed* about itself, and the screen should say
    so: they are how a person recognises their own laptop, not an identity check.
    """

    code: str
    hostname: str
    platform: str
    daemon_version: str
    expires_at: datetime | None


@dataclass(frozen=True)
class LinkIssued:
    """The one moment the plaintext token exists outside the daemon. Never stored, never logged."""

    machine_id: UUID
    workspace_id: UUID
    token: str


@dataclass(frozen=True)
class MachineIdentity:
    """Who a `/daemon/*` call is, resolved from its bearer token."""

    machine_id: UUID
    workspace_id: UUID
    owner_user_id: UUID
    token_expires_at: datetime | None


@dataclass(frozen=True)
class Renewal:
    """The answer to "is it time yet" — which is the server's to give (FR-014d)."""

    renewed: bool
    expires_at: datetime | None


class DaemonEnrollmentService:
    """Owns `daemon_link_codes` and the token column of `machines`.

    The clock is injected for the same reason it is everywhere else in this codebase: every
    rule here is a comparison against a timestamp, and a test that has to sleep ten minutes
    to check a ten-minute expiry is a test nobody runs.
    """

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._clock = clock

    def _sessions(self) -> async_sessionmaker[AsyncSession]:
        # Resolved on use, not in __init__: the container is built before the engine has
        # necessarily been pointed at its database, and binding early would pin this
        # service to whichever engine happened to exist first.
        return self._sessionmaker or get_sessionmaker()

    # ── the daemon's half ────────────────────────────────────────────────────

    async def start_link(
        self, *, platform: str, daemon_version: str, hostname: str
    ) -> LinkStarted:
        """Open a link attempt. Unauthenticated on purpose — the machine has no credential yet.

        What the machine says about itself is written down as *claims*, because the row that
        would make them facts (`machines`) does not exist until a person approves.
        """
        now = self._clock()
        expires_at = now + timedelta(seconds=settings.daemon_link_code_ttl_seconds)
        async with self._sessions()() as session:
            for _ in range(_CODE_ATTEMPTS):
                code = _new_code()
                session.add(
                    DaemonLinkCodeModel(
                        id=uuid4(),
                        code=code,
                        reported_platform=platform[:20],
                        reported_daemon_version=daemon_version[:40],
                        reported_hostname=hostname[:200],
                        expires_at=expires_at,
                        created_at=now,
                    )
                )
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    continue
                return LinkStarted(
                    code=code,
                    expires_in_seconds=settings.daemon_link_code_ttl_seconds,
                    poll_interval_seconds=settings.daemon_link_poll_interval_seconds,
                )
        raise Conflict("daemon_link_code_unavailable")

    async def poll_link(self, code: str) -> LinkIssued | None:
        """Ask whether a person has approved yet; mint the token the first time they have.

        Returns `None` while nobody has approved. Raises `NotFound` for a code that never
        existed, an expired one, or one already spent — three ways of saying *this code will
        never work*, which is the only distinction the waiting daemon can act on.

        The token is minted **here** rather than at approval, so the secret is created at
        the one instant it can be handed straight to the machine that will hold it. That
        also makes `consumed_at` mean exactly what it says.
        """
        now = self._clock()
        async with self._sessions()() as session:
            row = await self._live_code(session, code, now)
            if row.approved_by_user_id is None or row.workspace_id is None:
                return None

            token = f"{MACHINE_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
            machine = MachineModel(
                id=uuid4(),
                workspace_id=row.workspace_id,
                owner_user_id=row.approved_by_user_id,
                display_name=row.reported_hostname,
                token_hash=_hash_token(token),
                token_expires_at=now + timedelta(days=settings.daemon_token_ttl_days),
                daemon_version=row.reported_daemon_version,
                platform=row.reported_platform,
                created_at=now,
                updated_at=now,
            )
            session.add(machine)
            # Flushed before the code row points at it. The code carries a foreign key to
            # `machines`, and the unit of work is free to order an update to an already
            # persistent row ahead of an insert it has not seen yet — which the deployed
            # database refuses outright, as does SQLite here with its FK pragma on.
            await session.flush()

            # Spending the code is a conditional update, not an assignment, because the
            # check above and the write here are not one instant. A daemon that retried a
            # poll it thought had timed out has two calls in flight over the same code, and
            # two `read NULL → write` pairs both succeed: two tokens minted, one of them
            # belonging to a machine row nobody will ever heartbeat for. `WHERE consumed_at
            # IS NULL` collapses that to one winner on either engine — no row locking, no
            # dialect that has to support it.
            spent = cast(
                CursorResult[Any],
                await session.execute(
                    update(DaemonLinkCodeModel)
                    .where(
                        DaemonLinkCodeModel.id == row.id,
                        DaemonLinkCodeModel.consumed_at.is_(None),
                    )
                    .values(machine_id=machine.id, consumed_at=now),
                ),
            )
            if spent.rowcount != 1:
                await session.rollback()
                raise NotFound("daemon_link_code_already_used")
            await session.commit()
            return LinkIssued(
                machine_id=machine.id,
                workspace_id=machine.workspace_id,
                token=token,
            )

    # ── the person's half ────────────────────────────────────────────────────

    async def describe_link(self, code: str) -> PendingLink:
        """What is behind this code, so the screen can say which machine is being approved."""
        now = self._clock()
        async with self._sessions()() as session:
            row = await self._live_code(session, code, now)
            return PendingLink(
                code=row.code,
                hostname=row.reported_hostname,
                platform=row.reported_platform,
                daemon_version=row.reported_daemon_version,
                expires_at=as_utc(row.expires_at),
            )

    async def approve_link(
        self, code: str, *, workspace_id: UUID, approved_by_user_id: UUID
    ) -> PendingLink:
        """Bind a waiting code to a workspace. The caller must already have checked ownership.

        Approving twice is refused rather than ignored: the second approver would be handing
        a machine they cannot see to a workspace they did not choose.

        Claiming the code is a conditional update for the same reason spending it is. A
        double-click, a client retry, or two people who both know the code put two approvals
        in flight, and both read *nobody has approved yet* before either writes. Assigning
        the fields would let the later commit win in silence: the first approver is told 200
        while their machine goes to somebody else's workspace. `WHERE approved_by_user_id IS
        NULL` makes exactly one of them the approver and the other a refusal.
        """
        now = self._clock()
        async with self._sessions()() as session:
            row = await self._live_code(session, code, now)
            claimed = cast(
                CursorResult[Any],
                await session.execute(
                    update(DaemonLinkCodeModel)
                    .where(
                        DaemonLinkCodeModel.id == row.id,
                        # Unapproved implies unspent: nothing consumes a code that no one
                        # has approved, so this single condition covers both.
                        DaemonLinkCodeModel.approved_by_user_id.is_(None),
                    )
                    .values(
                        workspace_id=workspace_id, approved_by_user_id=approved_by_user_id
                    ),
                ),
            )
            if claimed.rowcount != 1:
                await session.rollback()
                raise Conflict("daemon_link_code_already_approved")
            await session.commit()
            return PendingLink(
                code=row.code,
                hostname=row.reported_hostname,
                platform=row.reported_platform,
                daemon_version=row.reported_daemon_version,
                expires_at=as_utc(row.expires_at),
            )

    # ── the token, afterwards ────────────────────────────────────────────────

    async def authenticate(self, token: str) -> MachineIdentity | None:
        """Resolve a bearer token to its machine, or `None` for anything unusable.

        An expired token resolves to nothing at all rather than to a machine with a note
        attached: every `/daemon/*` route would otherwise have to remember to check, and
        the one that forgot would be the interesting one.
        """
        now = self._clock()
        async with self._sessions()() as session:
            row = await session.scalar(
                select(MachineModel).where(MachineModel.token_hash == _hash_token(token))
            )
            if row is None:
                return None
            expires_at = as_utc(row.token_expires_at)
            if expires_at is not None and expires_at <= now:
                return None
            return MachineIdentity(
                machine_id=row.id,
                workspace_id=row.workspace_id,
                owner_user_id=row.owner_user_id,
                token_expires_at=expires_at,
            )

    async def renew_token(self, machine_id: UUID) -> Renewal:
        """Answer *not yet* or extend the token — the decision is the server's (FR-014d).

        The daemon may ask at any rhythm; it never computes its own expiry. `renewed=False`
        is a normal answer, not a refusal, so a machine asking hourly costs one comparison.

        Renewal deliberately keeps the same secret and only moves its expiry. Rotating the
        string would mean the reply carries a new token that the machine must persist before
        the old one dies — a write that can fail, on a path that runs unattended.

        This is the one read-then-write here that does *not* need the conditional update the
        other two use. Two renewals racing both compute the same `now + ttl` and write it;
        whichever lands second leaves the row saying what the first one meant. There is no
        invariant for the loser to break, because there is no loser — unlike approving or
        spending a code, where the whole point is that exactly one caller may win.
        """
        now = self._clock()
        async with self._sessions()() as session:
            row = await session.get(MachineModel, machine_id)
            if row is None:
                raise NotFound("machine_not_found")
            expires_at = as_utc(row.token_expires_at)
            window = timedelta(days=settings.daemon_token_renew_within_days)
            if expires_at is not None and expires_at - now > window:
                return Renewal(renewed=False, expires_at=expires_at)
            renewed_to = now + timedelta(days=settings.daemon_token_ttl_days)
            row.token_expires_at = renewed_to
            row.updated_at = now
            await session.commit()
            return Renewal(renewed=True, expires_at=renewed_to)

    # ── shared ───────────────────────────────────────────────────────────────

    async def _live_code(
        self, session: AsyncSession, code: str, now: datetime
    ) -> DaemonLinkCodeModel:
        """The one place a code is looked up, so no caller can skip one of the three checks."""
        row = await session.scalar(
            select(DaemonLinkCodeModel).where(DaemonLinkCodeModel.code == _normalise_code(code))
        )
        if row is None:
            raise NotFound("daemon_link_code_not_found")
        if row.consumed_at is not None:
            raise NotFound("daemon_link_code_already_used")
        expires_at = as_utc(row.expires_at)
        if expires_at is not None and expires_at <= now:
            raise NotFound("daemon_link_code_expired")
        return row
