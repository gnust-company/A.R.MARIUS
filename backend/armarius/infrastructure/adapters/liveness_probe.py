"""Gateway-health liveness probe (issue #66).

When a Marius goes quiet past T1 the `LivenessEngine` fires one bounded probe (LLD §10).
Instead of *waking the agent* (which spends tokens on an LLM turn), we ask its **gateway**
whether it is still healthy via the adapter's `test_environment(adapter_config)`. A healthy
gateway (Hermes/OpenClaw) is a cheap, no-token proxy for "the agent is still reachable",
which keeps an idle-but-alive agent ONLINE instead of falsely decaying it to OFFLINE.

Model: a signal (`/agent/me`, a task reply) *establishes* presence; this gateway-health
check *sustains* it across idle gaps. Only a gateway that stops answering (3 spaced misses)
lets the agent decay OFFLINE.

Caveat (accepted): a healthy gateway proves the *gateway* is up, not that this specific
agent behind it is alive. We trade that residual risk for not paying tokens to ping the
agent; a real task-wake failure corrects the state out-of-band.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from datetime import datetime, timedelta

from armarius.application.ports.adapter import AdapterRegistry
from armarius.application.ports.liveness_probe import LivenessProbe
from armarius.domain.entities.marius import Marius
from armarius.shared.clock import utcnow
from armarius.shared.logging import get_logger

logger = get_logger(__name__)


class GatewayHealthLivenessProbe(LivenessProbe):
    """Probe that reports an agent's gateway health via the adapter registry.

    Probes to the *same* gateway (identical adapter type + config) within
    ``cache_ttl_seconds`` are de-duplicated, so N agents behind one Hermes cost one
    health call per cycle, not N. The TTL is kept below the FSM's probe window (T2) so a
    single agent's 3-miss cadence is never distorted — only the concurrent burst collapses.
    """

    def __init__(
        self,
        registry: AdapterRegistry,
        *,
        cache_ttl_seconds: float = 15.0,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._registry = registry
        self._ttl = timedelta(seconds=cache_ttl_seconds)
        self._clock = clock
        # gateway key -> (expiry, ok)
        self._cache: dict[Hashable, tuple[datetime, bool]] = {}

    async def probe(self, marius: Marius) -> bool:
        """Fire one bounded gateway health-check; True iff the gateway answered healthy.

        Any inability to verify — unknown adapter, unreachable gateway, or a raised error —
        counts as a miss (`False`); this must never propagate an exception into the tick.
        """
        try:
            adapter = self._registry.get(marius.adapter_type)
        except LookupError:
            return False  # no adapter registered → cannot verify → miss

        config = marius.adapter_config or {}
        key: Hashable = (marius.adapter_type, tuple(sorted(config.items(), key=lambda kv: kv[0])))
        now = self._clock()
        cached = self._cache.get(key)
        if cached is not None and cached[0] > now:
            return cached[1]

        try:
            diagnostics = await adapter.test_environment(config)
            ok = bool(diagnostics.ok)
        except Exception:  # bounded: any failure is a miss, never crash the watchdog tick
            logger.warning("liveness gateway probe failed for marius %s", marius.id, exc_info=True)
            ok = False

        self._cache[key] = (now + self._ttl, ok)
        return ok
