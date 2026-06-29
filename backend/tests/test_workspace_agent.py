"""WorkspaceAgentService — host agent designation + onboarder skill link (LLD §3.1, §6)."""

from __future__ import annotations

import pytest

from armarius.application.use_cases.workspace_agent import (
    ONBOARDER_SKILL_SLUG,
    WORKSPACE_AGENT_ROLE,
    WorkspaceAgentService,
)
from armarius.domain.entities.workspace import Workspace
from tests.support.fakes import FakeUowFactory


def _factory_with_workspace() -> tuple[FakeUowFactory, Workspace]:
    factory = FakeUowFactory()
    ws = Workspace(name="Studio", slug="studio", owner_user_id="u1")
    factory.store.workspaces[ws.id] = ws
    return factory, ws


def _onboarder(factory: FakeUowFactory):
    return next(
        s for s in factory.store.skills.values() if s.slug == ONBOARDER_SKILL_SLUG
    )


async def test_designates_agent_linked_to_onboarder_skill() -> None:
    factory, ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)

    agent = await svc.ensure_workspace_agent(ws.id)

    assert agent.role == WORKSPACE_AGENT_ROLE
    assert agent.workspace_id == ws.id
    onboarder = _onboarder(factory)
    assert str(onboarder.id) in agent.skill_ids


async def test_onboarder_skill_tree_round_trips() -> None:
    factory, ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)

    await svc.ensure_workspace_agent(ws.id)

    onboarder = _onboarder(factory)
    assert onboarder.slug == ONBOARDER_SKILL_SLUG
    assert "SKILL.md" in onboarder.files
    assert "Armarius Onboarder" in onboarder.files["SKILL.md"]


async def test_designation_is_idempotent() -> None:
    factory, ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)

    first = await svc.ensure_workspace_agent(ws.id)
    second = await svc.ensure_workspace_agent(ws.id)

    assert first.id == second.id
    agents = [
        m for m in factory.store.mariuses.values() if m.role == WORKSPACE_AGENT_ROLE
    ]
    assert len(agents) == 1
    skills = [s for s in factory.store.skills.values() if s.slug == ONBOARDER_SKILL_SLUG]
    assert len(skills) == 1


async def test_missing_workspace_is_rejected() -> None:
    factory, ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)
    from uuid import uuid4

    with pytest.raises(LookupError):
        await svc.ensure_workspace_agent(uuid4())
