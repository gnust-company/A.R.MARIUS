"""GatewayHealthLivenessProbe — a healthy gateway sustains liveness without waking the
agent; any inability to verify is a miss; same-gateway probes de-dup within the TTL (#66)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from armarius.application.ports.adapter import (
    AdapterCapabilities,
    Diagnostics,
    ExecContext,
    ExecResult,
    MariusAdapter,
)
from armarius.domain.entities.marius import Marius
from armarius.domain.entities.run import RunStatus
from armarius.infrastructure.adapters.liveness_probe import GatewayHealthLivenessProbe
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


class _CountingAdapter(MariusAdapter):
    """A gateway whose ``test_environment`` verdict is scripted and whose calls are counted."""

    type = "hermes_gateway"
    capabilities = AdapterCapabilities(resumable=True, streaming=False, transport="http")

    def __init__(self, *, ok: bool = True, raises: BaseException | None = None) -> None:
        self.ok = ok
        self.raises = raises
        self.calls = 0

    async def execute(self, ctx: ExecContext) -> ExecResult:  # pragma: no cover - unused here
        return ExecResult(status=RunStatus.COMPLETED)

    async def test_environment(self, config: dict) -> Diagnostics:
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return Diagnostics(ok=self.ok)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _registry(adapter: MariusAdapter) -> InMemoryAdapterRegistry:
    reg = InMemoryAdapterRegistry()
    reg.register(adapter)
    return reg


def _marius(api_key: str = "k") -> Marius:
    return Marius(
        name="Marin",
        adapter_type="hermes_gateway",
        adapter_config={"base_url": "http://hermes:8642", "api_key": api_key},
    )


async def test_probe_true_when_gateway_healthy() -> None:
    adapter = _CountingAdapter(ok=True)
    probe = GatewayHealthLivenessProbe(_registry(adapter))

    assert await probe.probe(_marius()) is True
    assert adapter.calls == 1


async def test_probe_false_when_gateway_unhealthy() -> None:
    adapter = _CountingAdapter(ok=False)
    probe = GatewayHealthLivenessProbe(_registry(adapter))

    assert await probe.probe(_marius()) is False


async def test_probe_false_when_adapter_unknown() -> None:
    # Empty registry → no adapter for "hermes_gateway": cannot verify ⇒ miss.
    probe = GatewayHealthLivenessProbe(InMemoryAdapterRegistry())

    assert await probe.probe(_marius()) is False


async def test_probe_false_and_swallows_adapter_error() -> None:
    adapter = _CountingAdapter(raises=RuntimeError("gateway blew up"))
    probe = GatewayHealthLivenessProbe(_registry(adapter))

    # A raising gateway must be folded into a miss, never propagated into the tick.
    assert await probe.probe(_marius()) is False


async def test_probe_dedups_same_gateway_within_ttl() -> None:
    adapter = _CountingAdapter(ok=True)
    probe = GatewayHealthLivenessProbe(
        _registry(adapter), cache_ttl_seconds=15.0, clock=_Clock(T0)
    )

    # Two distinct agents behind the same gateway (same type + config) at the same instant.
    first = await probe.probe(_marius())
    second = await probe.probe(_marius())

    assert first is True and second is True
    assert adapter.calls == 1  # one health call covered both agents


async def test_probe_reprobes_after_ttl_expires() -> None:
    adapter = _CountingAdapter(ok=True)
    clock = _Clock(T0)
    probe = GatewayHealthLivenessProbe(_registry(adapter), cache_ttl_seconds=15.0, clock=clock)

    await probe.probe(_marius())
    clock.now = T0 + timedelta(seconds=16)  # past the TTL
    await probe.probe(_marius())

    assert adapter.calls == 2  # cache expired → re-checked the gateway


async def test_probe_keys_cache_per_config() -> None:
    adapter = _CountingAdapter(ok=True)
    probe = GatewayHealthLivenessProbe(
        _registry(adapter), cache_ttl_seconds=15.0, clock=_Clock(T0)
    )

    # Same gateway URL but different api_key ⇒ different auth context ⇒ not de-duped.
    await probe.probe(_marius(api_key="k1"))
    await probe.probe(_marius(api_key="k2"))

    assert adapter.calls == 2
