"""Workspace Agent designation (LLD §3.1, §6) — a workspace's host agent.

The Workspace Agent is the Marius that greets owners and runs onboarding. Who holds the
seat is recorded on ``workspace.workspace_agent_id`` — the single source of truth (#32);
the "Workspace Agent" role string is display-only. The onboarding playbook is no longer a
granted skill: it is injected into the agent's prompt when a project-setup chat starts (#61).

Under operator-invite (issue #63) the host is **never auto-created**: it only exists if the
operator invited an agent and ticked "Make Workspace Agent". `ensure_workspace_agent` is now
lookup-only — it returns the designated host or ``None`` (no config-less, token-less shell
that can neither wake nor authenticate its callbacks).
"""

from __future__ import annotations

from uuid import UUID

from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.marius import Marius
from armarius.shared.clock import utcnow

WORKSPACE_AGENT_ROLE = "Workspace Agent"


class WorkspaceAgentService:
    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow = uow_factory

    async def ensure_workspace_agent(self, workspace_id: UUID) -> Marius | None:
        """The workspace's designated host agent, or ``None`` if none was set up.

        Lookup-only under operator-invite (#63): the host must have been invited by the
        operator with gateway creds (and seated via `designate`). Backfills the pointer for
        workspaces designated before it was wired (#32), but never creates a host itself.
        """
        async with self._uow() as uow:
            ws = await uow.workspaces.get(workspace_id)
            if ws is None:
                raise LookupError("workspace not found")
            if ws.workspace_agent_id is not None:
                host = await uow.mariuses.get(ws.workspace_agent_id)
                if host is not None:
                    return host
            # Backfill: workspaces designated before the pointer was wired (#32)
            # identified their host by the role string alone.
            legacy = [
                m
                for m in await uow.mariuses.list_by_workspace(workspace_id)
                if m.role == WORKSPACE_AGENT_ROLE
            ]
            if legacy:
                ws.workspace_agent_id = legacy[0].id
                await uow.workspaces.update(ws)
                await uow.commit()
                return legacy[0]
            return None

    async def designate(self, workspace_id: UUID, marius_id: UUID) -> Marius:
        """Hand the host seat to this Marius. Any sitting host is demoted to a plain
        agent — role cleared, token/tasks untouched — never revoked (#32). Idempotent
        when the Marius already holds the seat.

        Read-modify-write without row locking: two concurrent designates can both see
        the same sitting host and the pointer goes to whichever commits last. Since the
        pointer is the source of truth the seat stays consistent; the loser is only
        left with a stale "Workspace Agent" role string. Same deferral as the #27
        delete guard — SELECT ... FOR UPDATE once Postgres is in prod."""
        now = utcnow()
        async with self._uow() as uow:
            ws = await uow.workspaces.get(workspace_id)
            if ws is None:
                raise LookupError("workspace not found")
            marius = await uow.mariuses.get(marius_id)
            if marius is None or marius.workspace_id != workspace_id:
                raise LookupError("marius not found")
            if ws.workspace_agent_id == marius.id:
                return marius

            sitting = None
            if ws.workspace_agent_id is not None:
                sitting = await uow.mariuses.get(ws.workspace_agent_id)
            if sitting is None:  # pre-#32 workspace: the host is known by role only
                sitting = next(
                    (
                        m
                        for m in await uow.mariuses.list_by_workspace(workspace_id)
                        if m.role == WORKSPACE_AGENT_ROLE and m.id != marius.id
                    ),
                    None,
                )
            if sitting is not None:
                sitting.role = ""
                sitting.updated_at = now
                await uow.mariuses.update(sitting)

            marius.role = WORKSPACE_AGENT_ROLE
            marius.updated_at = now
            await uow.mariuses.update(marius)
            ws.workspace_agent_id = marius.id
            await uow.workspaces.update(ws)
            await uow.commit()
            return marius
