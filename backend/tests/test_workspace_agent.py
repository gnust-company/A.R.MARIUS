"""WorkspaceAgentService — host seat via workspace.workspace_agent_id (#32).

The onboarding playbook is no longer a granted skill — it is injected into the agent's prompt
when a project-setup chat starts (#61), so designation is purely about who holds the seat.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from armarius.application.use_cases.workspace_agent import (
    WORKSPACE_AGENT_ROLE,
    WorkspaceAgentService,
)
from armarius.domain.entities.marius import Marius
from armarius.domain.entities.workspace import Workspace
from tests.support.fakes import FakeUowFactory


def _factory_with_workspace() -> tuple[FakeUowFactory, Workspace]:
    factory = FakeUowFactory()
    ws = Workspace(name="Studio", slug="studio", owner_user_id="u1")
    factory.store.workspaces[ws.id] = ws
    return factory, ws


def _add_marius(factory: FakeUowFactory, ws: Workspace, name: str, role: str = "") -> Marius:
    m = Marius(workspace_id=ws.id, name=name, role=role, adapter_type="echo")
    factory.store.mariuses[m.id] = m
    return m


async def test_ensure_creates_host_and_records_the_seat() -> None:
    factory, ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)

    agent = await svc.ensure_workspace_agent(ws.id)

    assert agent.role == WORKSPACE_AGENT_ROLE
    assert agent.workspace_id == ws.id
    # The pointer — not the role string — is the source of truth (#32).
    assert factory.store.workspaces[ws.id].workspace_agent_id == agent.id
    # A fresh host runs on the real gateway adapter so it can drive onboarding.
    assert agent.adapter_type == "hermes_gateway"


async def test_ensure_backfills_the_pointer_for_a_legacy_host() -> None:
    factory, ws = _factory_with_workspace()
    legacy = _add_marius(factory, ws, "Old Host", role=WORKSPACE_AGENT_ROLE)
    svc = WorkspaceAgentService(factory)

    agent = await svc.ensure_workspace_agent(ws.id)

    assert agent.id == legacy.id
    assert factory.store.workspaces[ws.id].workspace_agent_id == legacy.id


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


async def test_designate_swaps_and_keeps_the_old_host_as_plain_agent() -> None:
    factory, ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)
    old = await svc.ensure_workspace_agent(ws.id)
    new = _add_marius(factory, ws, "Fresh")

    promoted = await svc.designate(ws.id, new.id)

    assert promoted.id == new.id
    assert promoted.role == WORKSPACE_AGENT_ROLE
    assert factory.store.workspaces[ws.id].workspace_agent_id == new.id
    # The old host survives as a plain agent — demoted, not revoked (#32).
    demoted = factory.store.mariuses[old.id]
    assert demoted.role == ""
    # Idempotent: designating the sitting host again changes nothing.
    again = await svc.designate(ws.id, new.id)
    assert again.id == new.id
    assert factory.store.workspaces[ws.id].workspace_agent_id == new.id


async def test_designate_rejects_a_marius_from_another_workspace() -> None:
    factory, ws = _factory_with_workspace()
    other = Workspace(name="Elsewhere", slug="elsewhere", owner_user_id="u2")
    factory.store.workspaces[other.id] = other
    stranger = _add_marius(factory, other, "Stranger")
    svc = WorkspaceAgentService(factory)

    with pytest.raises(LookupError):
        await svc.designate(ws.id, stranger.id)


async def test_missing_workspace_is_rejected() -> None:
    factory, _ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)

    with pytest.raises(LookupError):
        await svc.ensure_workspace_agent(uuid4())
