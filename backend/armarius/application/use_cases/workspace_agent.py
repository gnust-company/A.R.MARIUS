"""Workspace Agent designation (LLD §3.1, §6) — every workspace has one host agent.

The Workspace Agent is the Marius that greets owners and runs onboarding. Who holds the
seat is recorded on ``workspace.workspace_agent_id`` — the single source of truth (#32);
the "Workspace Agent" role string is display-only. The onboarding playbook is no longer a
granted skill: it is injected into the agent's prompt when a project-setup chat starts (#61).
"""

from __future__ import annotations

from uuid import UUID

from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.marius import Marius
from armarius.shared.clock import utcnow

WORKSPACE_AGENT_ROLE = "Workspace Agent"
WORKSPACE_AGENT_NAME = "Workspace Agent"


class WorkspaceAgentService:
    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow = uow_factory

    async def ensure_workspace_agent(self, workspace_id: UUID) -> Marius:
        """The workspace's host agent — created lazily on first need (idempotent)."""
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

        now = utcnow()
        async with self._uow() as uow:
            agent = Marius(
                workspace_id=workspace_id,
                name=WORKSPACE_AGENT_NAME,
                role=WORKSPACE_AGENT_ROLE,
                adapter_type="hermes_gateway",
                created_at=now,
                updated_at=now,
            )
            created = await uow.mariuses.add(agent)
            ws = await uow.workspaces.get(workspace_id)
            if ws is not None:
                ws.workspace_agent_id = created.id
                await uow.workspaces.update(ws)
            await uow.commit()
            return created

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
