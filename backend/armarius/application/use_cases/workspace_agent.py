"""Workspace Agent designation (LLD §3.1, §6) — every workspace has one host agent.

The Workspace Agent is the Marius that greets owners and runs onboarding. Who holds the
seat is recorded on ``workspace.workspace_agent_id`` — the single source of truth (#32);
the "Workspace Agent" role string is display-only. The built-in ``armarius-onboarder``
skill is materialised into the workspace's Skill Shop but never linked to a Marius:
being the host IS the grant (``onboarder_skill_for``), so designating a new host moves
the playbook with the seat and needs no link bookkeeping.
"""

from __future__ import annotations

from uuid import UUID

from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.marius import Marius
from armarius.domain.entities.skill import Skill
from armarius.shared.clock import utcnow

WORKSPACE_AGENT_ROLE = "Workspace Agent"
WORKSPACE_AGENT_NAME = "Workspace Agent"
ONBOARDER_SKILL_SLUG = "armarius-onboarder"
ONBOARDER_SKILL_NAME = "Armarius Onboarder"
ONBOARDER_SKILL_DESCRIPTION = (
    "Greet the owner, gather the project brief, and stand up the roster — the Workspace "
    "Agent's onboarding playbook."
)

_ONBOARDER_SKILL_MD = """---
name: Armarius Onboarder
description: Greet the owner, gather the project brief, and stand up the roster.
---

# Armarius Onboarder

You are the Workspace Agent. When an owner arrives, run the onboarding conversation:

## When to use

- A new owner opens the workspace with no project yet.
- The owner asks to start a new project or assemble a team.

## How it works

1. Greet the owner and ask what they want to build (objective, success metrics, target date).
2. Propose a roster: exactly one Project Leader (one seat) plus one or more worker roles.
3. On confirmation, create the project in SETUP and seat agents into the roster.
4. Hand off to the Project Leader once every seat is granted and online.
"""


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

        await self._ensure_onboarder_skill(workspace_id)

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
        when the Marius already holds the seat."""
        onboarder = await self._ensure_onboarder_skill(workspace_id)
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
                # Pre-#32 hosts carried the onboarder in skill_ids; the grant is
                # seat-derived now, so drop the stale link with the seat.
                sitting.skill_ids = [
                    s for s in sitting.skill_ids if s != str(onboarder.id)
                ]
                sitting.updated_at = now
                await uow.mariuses.update(sitting)

            marius.role = WORKSPACE_AGENT_ROLE
            marius.updated_at = now
            await uow.mariuses.update(marius)
            ws.workspace_agent_id = marius.id
            await uow.workspaces.update(ws)
            await uow.commit()
            return marius

    async def onboarder_skill_for(self, marius: Marius) -> Skill | None:
        """The onboarding playbook, iff this Marius holds its workspace's host seat."""
        async with self._uow() as uow:
            ws = await uow.workspaces.get(marius.workspace_id)
            if ws is None or ws.workspace_agent_id != marius.id:
                return None
            return await uow.skills.get_by_slug(marius.workspace_id, ONBOARDER_SKILL_SLUG)

    async def _ensure_onboarder_skill(self, workspace_id: UUID) -> Skill:
        async with self._uow() as uow:
            existing = await uow.skills.get_by_slug(workspace_id, ONBOARDER_SKILL_SLUG)
            if existing is not None:
                return existing
            skill = Skill(
                workspace_id=workspace_id,
                slug=ONBOARDER_SKILL_SLUG,
                name=ONBOARDER_SKILL_NAME,
                description=ONBOARDER_SKILL_DESCRIPTION,
                source="builtin",
                files={"SKILL.md": _ONBOARDER_SKILL_MD},
                created_at=utcnow(),
            )
            created = await uow.skills.add(skill)
            await uow.commit()
            return created
