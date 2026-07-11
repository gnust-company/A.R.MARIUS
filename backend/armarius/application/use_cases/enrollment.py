"""Invite use cases (LLD §3.4, issue #63) — operator-invite, token minted at invite.

The operator enters the agent's gateway URL + api_key when inviting; that IS the approval,
so the service mints the `agent_token` immediately, persists the agent as APPROVED, and the
route pushes a one-time setup prompt to the agent via its adapter (no manual copy-paste, no
enroll/approve gate). `adapter_config` is populated at the source — that is what lets a
later wake (`HermesGatewayAdapter.execute` → `POST {base_url}/v1/runs`) actually reach the
agent, and what lets the agent authenticate its callbacks.

`push_setup` sends (or re-sends) the setup prompt. A failed send is NOT fatal: the row is
already approved, so the operator can retry. The route surfaces `send_status` so the UI can
offer a Retry. The send itself runs outside the persistence UoW, mirroring the onboarding
wake (issue #61).
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from armarius.application.ports.adapter import AdapterRegistry, ExecContext
from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.marius import InviteStatus, Marius
from armarius.domain.entities.run import RunStatus
from armarius.shared.clock import utcnow

# Upper bound on the dispatch hand-off. A network dispatch returns as soon as the gateway
# accepts the run, so this only bounds the fallback (fast in-process) adapters.
_SETUP_TIMEOUT_SECONDS = 120


class StatusNotifier(Protocol):
    """Publishes a workspace control-plane event (structurally the TopicEventBus).

    Typed here as a Protocol so the application layer stays decoupled from the concrete
    SSE bus — the route publishes the `approved`/`send_status` hops itself.
    """

    async def publish(self, topic: str, type: str, data: dict) -> int: ...


class GatewayUnreachable(ValueError):
    """The operator-supplied gateway did not pass the adapter's reachability probe."""


class UnknownAdapter(ValueError):
    """The operator selected an adapter type no registry knows about."""


def _default_token() -> str:
    return f"arm_{secrets.token_urlsafe(32)}"


class InviteService:
    """Operator-driven agent invite — gateway+key at invite, system-pushed setup (#63)."""

    def __init__(
        self,
        uow_factory: UowFactory,
        *,
        registry: AdapterRegistry,
        token_factory: Callable[[], str] = _default_token,
    ) -> None:
        self._uow = uow_factory
        self._registry = registry
        self._mint_token = token_factory

    async def invite(
        self,
        workspace_id: UUID,
        name: str,
        *,
        gateway_url: str,
        api_key: str,
        skills: list[str] | None = None,
        skill_ids: list[str] | None = None,
        adapter_type: str = "hermes_gateway",
        owner_user_id: str | None = None,
    ) -> Marius:
        """Create an APPROVED Marius wired to the operator's gateway, token already minted.

        The gateway is probed before anything is persisted: a bad URL/key raises
        `GatewayUnreachable` (→ 422) and nothing is written. On success the agent is live
        (APPROVED) and ready to receive its setup prompt via `push_setup`.

        Role is deliberately NOT taken here — it is a project-roster concept, assigned later
        (e.g. by Workspace Agent designation). A freshly invited agent has no role (#63).
        """
        try:
            adapter = self._registry.get(adapter_type)
        except LookupError as exc:
            raise UnknownAdapter(f"unknown adapter type '{adapter_type}'") from exc
        probe = await adapter.test_environment({"base_url": gateway_url, "api_key": api_key})
        if not probe.ok:
            raise GatewayUnreachable(probe.detail or "gateway unreachable")

        now = utcnow()
        async with self._uow() as uow:
            if await uow.workspaces.get(workspace_id) is None:
                raise LookupError("workspace not found")
            marius = Marius(
                workspace_id=workspace_id,
                name=name,
                skills=skills or [],
                skill_ids=skill_ids or [],
                adapter_type=adapter_type,
                adapter_config={"base_url": gateway_url, "api_key": api_key},
                owner_user_id=owner_user_id,
                invite_status=InviteStatus.INVITED,
                agent_token=None,
                created_at=now,
                updated_at=now,
            )
            marius.activate(self._mint_token(), now)
            created = await uow.mariuses.add(marius)
            await uow.commit()
            return created

    async def push_setup(self, marius_id: UUID, *, prompt: str) -> str:
        """Push the one-time setup prompt to an agent via its adapter (best-effort).

        "Sent" means the gateway *accepted* the setup dispatch — NOT that the agent
        finished its turn. We deliberately do not wait for the run to complete: the agent
        proves it is alive out-of-band by calling ``/agent/me`` (→ ONLINE), and blocking
        the invite on a full agent turn would spin for up to the watchdog and falsely
        report failure for a run that landed fine (issue #63).

        Returns ``"sent"`` when the dispatch was accepted, ``"send_failed"`` otherwise. A
        failure is not fatal — the row is already approved — so this never raises on a
        send problem; the caller surfaces the status and may retry by calling again.
        """
        async with self._uow() as uow:
            marius = await uow.mariuses.get(marius_id)
            if marius is None:
                raise LookupError("marius not found")
            adapter_type = marius.adapter_type
            adapter_config = dict(marius.adapter_config or {})
        try:
            adapter = self._registry.get(adapter_type)
        except LookupError:
            return "send_failed"
        ctx = ExecContext(
            prompt=prompt,
            adapter_config=adapter_config,
            session_params={
                "session_id": f"armarius:setup:{marius_id}",
                "session_key": f"armarius:setup:{marius_id}",
            },
            marius_id=marius_id,
            timeout_seconds=_SETUP_TIMEOUT_SECONDS,
        )
        try:
            result = await adapter.dispatch(ctx)
        except Exception:
            return "send_failed"
        # Anything the gateway accepted (RUNNING/QUEUED, or COMPLETED for instant local
        # adapters) counts as sent; only an outright reject/timeout is a send failure.
        failed = {RunStatus.FAILED, RunStatus.TIMED_OUT}
        return "send_failed" if result.status in failed else "sent"
