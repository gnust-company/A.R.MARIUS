"""WorkspaceAgentService — host seat via workspace.workspace_agent_id (#32).

Under operator-invite (#63) the host is NEVER auto-created: it only exists if the operator
invited an agent and seated it. `ensure_workspace_agent` is lookup-only — it returns the
designated host or None (no config-less, token-less shell). The onboarding playbook is
injected into the agent's prompt when a project-setup chat starts (#61), so designation is
purely about who holds the seat.
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


async def test_ensure_returns_none_when_no_host_designated() -> None:
    """No operator invited+seated a host → ensure does not conjure one (#63)."""
    factory, ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)

    assert await svc.ensure_workspace_agent(ws.id) is None
    assert factory.store.workspaces[ws.id].workspace_agent_id is None
    assert not factory.store.mariuses  # nothing was created


async def test_ensure_returns_the_designated_host() -> None:
    factory, ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)
    host = _add_marius(factory, ws, "Host")
    await svc.designate(ws.id, host.id)

    found = await svc.ensure_workspace_agent(ws.id)
    assert found is not None
    assert found.id == host.id


async def test_ensure_backfills_the_pointer_for_a_legacy_host() -> None:
    factory, ws = _factory_with_workspace()
    legacy = _add_marius(factory, ws, "Old Host", role=WORKSPACE_AGENT_ROLE)
    svc = WorkspaceAgentService(factory)

    agent = await svc.ensure_workspace_agent(ws.id)

    assert agent is not None
    assert agent.id == legacy.id
    assert factory.store.workspaces[ws.id].workspace_agent_id == legacy.id


async def test_designation_is_idempotent() -> None:
    factory, ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)
    host = _add_marius(factory, ws, "Host")
    await svc.designate(ws.id, host.id)

    first = await svc.ensure_workspace_agent(ws.id)
    second = await svc.ensure_workspace_agent(ws.id)
    assert first is not None and second is not None
    assert first.id == second.id == host.id


async def test_designate_swaps_and_keeps_the_old_host_as_plain_agent() -> None:
    factory, ws = _factory_with_workspace()
    svc = WorkspaceAgentService(factory)
    old = _add_marius(factory, ws, "Old")
    await svc.designate(ws.id, old.id)  # seat the first host
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
