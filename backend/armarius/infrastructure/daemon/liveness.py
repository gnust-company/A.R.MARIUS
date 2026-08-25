"""Is this agent alive? Answered from our own tables, not from anyone's health endpoint.

The layer above asks exactly one question and is told exactly one thing (FR-006). Below
that question sit three separate ways for an agent to be unreachable — it was never put
anywhere, the CLI it was put on is gone from the machine, or the machine itself stopped
beating — and all three collapse into the same verdict here (FR-006a). None of them
reaches the business layers as a branch, because a business layer that can tell them
apart is one that has to be reopened the day work runs somewhere else (Constitution III).

Two things this probe deliberately does **not** do:

  * It does not touch the agent. Waking an agent to ask whether it is awake spends a real
    LLM turn on a question we can answer from three columns.
  * It does not trust a beat as proof the agent can work. A beat proves the daemon can be
    reached; whether an agent CLI on that machine can still run is a different fact,
    recorded by a different call, and merging the two would leave a machine whose CLI was
    uninstalled looking healthy forever (FR-055b).

Armarius owns this verdict outright — no external runtime's heartbeat is consulted, and
none can overrule it (FR-006d).
"""

from __future__ import annotations

from armarius.application.ports.liveness_probe import LivenessProbe
from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.marius import Marius


class DaemonLivenessProbe(LivenessProbe):
    """Reports whether the place this agent was put can take work right now."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow = uow_factory

    async def probe(self, marius: Marius) -> bool:
        """True iff this agent sits somewhere that is open for work.

        Failures are **not** swallowed into a miss, which is where this parts company with
        the gateway probe it replaces. There, an unreachable gateway was the very thing
        being measured, so a failed call was a real answer. Here the read is against our
        own database, and a database we cannot read is not evidence that every agent in
        the workspace died — it is evidence that we cannot tell. Letting it raise keeps
        that distinction: the watchdog logs the tick and moves on, and nobody is declared
        offline on the strength of our own outage.
        """
        async with self._uow() as uow:
            placed = await uow.placements.placed_at([marius.id])
        placement = placed.get(marius.id)
        # Missing means the agent was never put anywhere. It is offline, and saying so is
        # the point: an agent with nowhere to work must never be a silent nothing (FR-007f).
        return placement is not None and placement.ready
