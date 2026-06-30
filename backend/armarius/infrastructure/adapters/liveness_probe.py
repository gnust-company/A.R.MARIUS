"""Liveness probe seam.

The *real* probe (Sprint 5 watchdog) sends a light "reply OK" turn through the adapter
registry and reports whether the agent answered. Until that loop exists this placeholder
never answers — which is inert, because no watchdog tick runs yet. Liveness still moves
to ONLINE through `LivenessEngine.record_signal` on any real contact (e.g. `/agent/me`),
independent of this probe.
"""

from __future__ import annotations

from armarius.application.ports.liveness_probe import LivenessProbe
from armarius.domain.entities.marius import Marius


class PlaceholderLivenessProbe(LivenessProbe):
    """No-op probe used until the Sprint-5 watchdog wires a registry-backed probe."""

    async def probe(self, marius: Marius) -> bool:  # pragma: no cover - inert in Sprint 4
        return False
