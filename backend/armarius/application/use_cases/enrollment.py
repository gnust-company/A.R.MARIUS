"""Enrollment use cases (LLD §3.4, §12) — enroll-and-wait, token minted on approve.

The invite lifecycle is `invited → pending_review → approved`. The agent presents its
`enrollment_code`; the **enroll call then blocks** (it does not return a token) until the
Patron approves, at which point the held call completes with the freshly-minted
`agent_token`. `claim` is the recovery path only: it returns the token iff the Marius is
already approved (e.g. the agent lost the held connection).

The wait is coordinated in-process by a per-Marius `asyncio.Future`: `enroll` awaits it,
`approve` resolves it. The DB transaction is **not** held open across the wait — `enroll`
commits `pending_review` and closes its UoW before awaiting.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable
from uuid import UUID

from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.marius import InviteStatus, Marius
from armarius.shared.clock import utcnow


class EnrollmentError(Exception):
    """Raised on a bad enrollment code or an illegal enrollment step."""


def _default_token() -> str:
    return f"arm_{secrets.token_urlsafe(32)}"


def _default_code() -> str:
    return secrets.token_urlsafe(16)


class EnrollmentService:
    def __init__(
        self,
        uow_factory: UowFactory,
        *,
        token_factory: Callable[[], str] = _default_token,
        code_factory: Callable[[], str] = _default_code,
    ) -> None:
        self._uow = uow_factory
        self._mint_token = token_factory
        self._mint_code = code_factory
        self._pending: dict[UUID, asyncio.Future[str]] = {}

    # ── invite ──────────────────────────────────────────────────────────────────
    async def invite(
        self,
        workspace_id: UUID,
        name: str,
        role: str,
        *,
        skills: list[str] | None = None,
        skill_ids: list[str] | None = None,
        adapter_type: str = "hermes_gateway",
        adapter_config: dict | None = None,
        owner_user_id: str | None = None,
    ) -> Marius:
        """Create an INVITED Marius with an enrollment code and NO token yet."""
        now = utcnow()
        async with self._uow() as uow:
            if await uow.workspaces.get(workspace_id) is None:
                raise LookupError("workspace not found")
            marius = Marius(
                workspace_id=workspace_id,
                name=name,
                role=role,
                skills=skills or [],
                skill_ids=skill_ids or [],
                adapter_type=adapter_type,
                adapter_config=adapter_config or {},
                owner_user_id=owner_user_id,
                invite_status=InviteStatus.INVITED,
                enrollment_code=self._mint_code(),
                agent_token=None,
                created_at=now,
                updated_at=now,
            )
            created = await uow.mariuses.add(marius)
            await uow.commit()
            return created

    # ── enroll-and-wait ─────────────────────────────────────────────────────────
    async def enroll(self, marius_id: UUID, code: str) -> str:
        """Present the code → hold until approved, then return the minted token.

        Idempotent recovery: if the Marius is already approved, returns the token at once.
        """
        future = self._future_for(marius_id)
        async with self._uow() as uow:
            marius = await uow.mariuses.get(marius_id)
            if marius is None:
                raise LookupError("marius not found")
            if not marius.enrollment_code or code != marius.enrollment_code:
                raise EnrollmentError("invalid enrollment code")
            if marius.invite_status == InviteStatus.APPROVED:
                return marius.token_for_claim()  # already approved → recover at once
            marius.begin_enroll()  # invited|pending_review → pending_review (idempotent)
            marius.updated_at = utcnow()
            await uow.mariuses.update(marius)
            await uow.commit()
        return await future

    async def approve(self, marius_id: UUID) -> Marius:
        """Patron approves → mint the token once and complete any held enroll call."""
        async with self._uow() as uow:
            marius = await uow.mariuses.get(marius_id)
            if marius is None:
                raise LookupError("marius not found")
            token = self._mint_token()
            marius.approve(token, utcnow())  # raises InviteError unless pending_review
            await uow.mariuses.update(marius)
            await uow.commit()
        future = self._future_for(marius_id)
        if not future.done():
            future.set_result(token)
        return marius

    async def claim(self, marius_id: UUID, code: str) -> str:
        """Recovery only: return the token iff the Marius is already approved."""
        async with self._uow() as uow:
            marius = await uow.mariuses.get(marius_id)
            if marius is None:
                raise LookupError("marius not found")
            if not marius.enrollment_code or code != marius.enrollment_code:
                raise EnrollmentError("invalid enrollment code")
            return marius.token_for_claim()  # raises InviteError unless approved

    # ── internals ───────────────────────────────────────────────────────────────
    def _future_for(self, marius_id: UUID) -> asyncio.Future[str]:
        """Get-or-create the held-call future for a Marius (bound to the running loop)."""
        future = self._pending.get(marius_id)
        if future is None or future.cancelled():
            future = asyncio.get_running_loop().create_future()
            self._pending[marius_id] = future
        return future
