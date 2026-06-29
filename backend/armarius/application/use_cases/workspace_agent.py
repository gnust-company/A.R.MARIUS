"""Workspace Agent designation (LLD §3.1, §6) — every workspace has one host agent.

The Workspace Agent is a special Marius that greets owners and runs onboarding. It is
designated once per workspace and carries the built-in `armarius-onboarder` skill, which
is materialised into the workspace's Skill Shop and linked to the agent. Idempotent:
re-designating returns the existing agent and reuses the existing skill.
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
        """Designate (idempotently) the workspace's host agent, linked to the onboarder."""
        async with self._uow() as uow:
            if await uow.workspaces.get(workspace_id) is None:
                raise LookupError("workspace not found")
            existing = [
                m
                for m in await uow.mariuses.list_by_workspace(workspace_id)
                if m.role == WORKSPACE_AGENT_ROLE
            ]
            if existing:
                return existing[0]

        skill = await self._ensure_onboarder_skill(workspace_id)

        now = utcnow()
        async with self._uow() as uow:
            agent = Marius(
                workspace_id=workspace_id,
                name=WORKSPACE_AGENT_NAME,
                role=WORKSPACE_AGENT_ROLE,
                skill_ids=[str(skill.id)],
                adapter_type="hermes_gateway",
                created_at=now,
                updated_at=now,
            )
            created = await uow.mariuses.add(agent)
            await uow.commit()
            return created

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
