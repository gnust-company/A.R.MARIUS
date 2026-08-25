"""InviteService — operator-invite: gateway probe, token-at-invite, best-effort push (#63)."""

from __future__ import annotations

import pytest

from armarius.application.ports.adapter import (
    AdapterCapabilities,
    Diagnostics,
    ExecContext,
    ExecResult,
    MariusAdapter,
)
from armarius.application.use_cases.enrollment import (
    GatewayUnreachable,
    InviteService,
    UnknownAdapter,
)
from armarius.domain.entities.marius import InviteStatus
from armarius.domain.entities.placement import Placement
from armarius.domain.entities.run import RunStatus
from armarius.domain.entities.workspace import Workspace
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from tests.support.fakes import FakeAdapter, FakeUowFactory, a_placement


def _factory_with_workspace() -> tuple[FakeUowFactory, Workspace, Placement]:
    """A workspace with somewhere to put an agent.

    The placement comes with it because an agent cannot be created without one (FR-007f) —
    every test here would otherwise have to say so itself.
    """
    factory = FakeUowFactory()
    ws = Workspace(name="Studio", slug="studio", owner_user_id="u1")
    factory.store.workspaces[ws.id] = ws
    return factory, ws, a_placement(factory, ws.id)


async def _invite(svc: InviteService, ws: Workspace, place: Placement, name: str = "Marin"):
    """The one call every test here makes. Named arguments in one place, not nine."""
    return await svc.invite(
        ws.id,
        name,
        adapter_type="fake",
        gateway_url="http://x",
        api_key="k",
        placement_id=place.id,
    )


def _registry(adapter: MariusAdapter) -> InMemoryAdapterRegistry:
    reg = InMemoryAdapterRegistry()
    reg.register(adapter)
    return reg


class _FailProbeAdapter(MariusAdapter):
    """A reachable-in-type adapter whose gateway always fails the probe."""

    type = "fake"
    capabilities = AdapterCapabilities(resumable=True, streaming=False, transport="http")

    async def execute(self, ctx: ExecContext) -> ExecResult:  # pragma: no cover - never reached
        return ExecResult(status=RunStatus.COMPLETED)

    async def test_environment(self, config: dict) -> Diagnostics:
        return Diagnostics(ok=False, detail="no probe endpoint responded")


class _DispatchOnlyAdapter(MariusAdapter):
    """A network-style adapter: ``dispatch`` accepts the run and returns immediately
    (RUNNING) without streaming it; ``execute`` here would report FAILED. Used to prove
    push_setup hands off via dispatch and never waits for the full turn (#63)."""

    type = "fake"
    capabilities = AdapterCapabilities(resumable=True, streaming=True, transport="http")

    def __init__(self) -> None:
        self.executes = 0
        self.dispatches = 0

    async def execute(self, ctx: ExecContext) -> ExecResult:  # pragma: no cover - must not run
        self.executes += 1
        return ExecResult(status=RunStatus.FAILED)

    async def dispatch(self, ctx: ExecContext) -> ExecResult:
        self.dispatches += 1
        return ExecResult(status=RunStatus.RUNNING, external_run_id="run-1")

    async def test_environment(self, config: dict) -> Diagnostics:
        return Diagnostics(ok=True)


async def test_invite_creates_approved_marius_with_token_and_adapter_config() -> None:
    factory, ws, place = _factory_with_workspace()
    svc = InviteService(factory, registry=_registry(FakeAdapter()))

    m = await svc.invite(
        ws.id,
        "Marin",
        adapter_type="fake",
        gateway_url="http://gateway.test:8642",
        api_key="k",
        placement_id=place.id,
    )

    assert m.invite_status == InviteStatus.APPROVED
    assert m.agent_token and m.agent_token.startswith("arm_")
    # The gateway creds are stored exactly where the adapter reads them.
    assert m.adapter_config == {"base_url": "http://gateway.test:8642", "api_key": "k"}


async def test_invite_validates_gateway_before_persisting() -> None:
    factory, ws, place = _factory_with_workspace()
    svc = InviteService(factory, registry=_registry(_FailProbeAdapter()))

    with pytest.raises(GatewayUnreachable):
        await _invite(svc, ws, place)

    # Nothing was written — the probe gated persistence.
    assert not factory.store.mariuses


async def test_invite_rejects_unknown_adapter_type() -> None:
    factory, ws, place = _factory_with_workspace()
    # Empty registry → no adapter for "fake".
    svc = InviteService(factory, registry=InMemoryAdapterRegistry())

    with pytest.raises(UnknownAdapter):
        await _invite(svc, ws, place)


async def test_invite_rejects_unknown_workspace() -> None:
    from uuid import uuid4

    factory, _ws, place = _factory_with_workspace()
    svc = InviteService(factory, registry=_registry(FakeAdapter()))

    with pytest.raises(LookupError):
        await svc.invite(
            uuid4(),
            "Marin",
            adapter_type="fake",
            gateway_url="http://x",
            api_key="k",
            placement_id=place.id,
        )


async def test_push_setup_sent_on_completed() -> None:
    factory, ws, place = _factory_with_workspace()
    adapter = FakeAdapter()  # execute → COMPLETED
    svc = InviteService(factory, registry=_registry(adapter))
    m = await _invite(svc, ws, place)

    status = await svc.push_setup(m.id, prompt="setup")

    assert status == "sent"
    assert adapter.executes == 1


async def test_push_setup_hands_off_via_dispatch_without_awaiting_the_run() -> None:
    """A gateway that ACCEPTED the run (RUNNING) is already "sent": push_setup must not
    block on the whole agent turn. It dispatches once and never calls execute (which here
    would report FAILED) — guarding against a regression to the old blocking behaviour."""
    factory, ws, place = _factory_with_workspace()
    adapter = _DispatchOnlyAdapter()
    svc = InviteService(factory, registry=_registry(adapter))
    m = await _invite(svc, ws, place)

    status = await svc.push_setup(m.id, prompt="setup")

    assert status == "sent"
    assert adapter.dispatches == 1
    assert adapter.executes == 0  # never streamed the run to completion


async def test_push_setup_send_failed_when_run_not_completed() -> None:
    factory, ws, place = _factory_with_workspace()
    adapter = FakeAdapter(status=RunStatus.FAILED)
    svc = InviteService(factory, registry=_registry(adapter))
    m = await _invite(svc, ws, place)

    assert await svc.push_setup(m.id, prompt="setup") == "send_failed"


async def test_push_setup_send_failed_when_adapter_raises() -> None:
    factory, ws, place = _factory_with_workspace()
    adapter = FakeAdapter(raise_on_execute=RuntimeError("runtime down"))
    svc = InviteService(factory, registry=_registry(adapter))
    m = await _invite(svc, ws, place)

    assert await svc.push_setup(m.id, prompt="setup") == "send_failed"


async def test_push_setup_send_failed_when_adapter_unknown() -> None:
    factory, ws, place = _factory_with_workspace()
    svc = InviteService(factory, registry=_registry(FakeAdapter()))
    m = await _invite(svc, ws, place)
    # The agent's adapter type is no longer registered (e.g. registry reconfigured).
    svc._registry = InMemoryAdapterRegistry()  # type: ignore[method-assign]

    assert await svc.push_setup(m.id, prompt="setup") == "send_failed"


async def test_push_setup_unknown_marius_is_not_found() -> None:
    from uuid import uuid4

    factory, _ws, place = _factory_with_workspace()
    svc = InviteService(factory, registry=_registry(FakeAdapter()))

    with pytest.raises(LookupError):
        await svc.push_setup(uuid4(), prompt="setup")


async def test_push_setup_can_retry_after_a_failure() -> None:
    """A failed push is not fatal — calling again re-sends (the row stayed approved)."""
    factory, ws, place = _factory_with_workspace()
    adapter = FakeAdapter(raise_on_execute=RuntimeError("down"))
    svc = InviteService(factory, registry=_registry(adapter))
    m = await _invite(svc, ws, place)

    assert await svc.push_setup(m.id, prompt="setup") == "send_failed"
    # Runtime recovers on retry.
    adapter.raise_on_execute = None
    assert await svc.push_setup(m.id, prompt="setup") == "sent"
