"""LivenessProbe port — the bounded "are you there?" check the engine fires (LLD §10).

The recency+probe model has NO heartbeat endpoint: when a Marius goes quiet past T1 the
`LivenessEngine` asks this port to poke the agent's runtime once. An implementation wraps
the adapter (e.g. a cheap Hermes ping); it must be bounded and return a plain bool —
`True` = the agent answered (a signal), `False` = no answer (counts as a miss).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from armarius.domain.entities.marius import Marius


class LivenessProbe(ABC):
    @abstractmethod
    async def probe(self, marius: Marius) -> bool:
        """Fire one bounded probe; True iff the agent answered."""
        ...
