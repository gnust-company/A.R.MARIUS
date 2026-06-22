"""Live event bus port — pushes traced run events to subscribers (SSE) in realtime.

This is the "live" half of the §8.1 tee: as the adapter streams events, the wake
engine persists them (durable trace) AND publishes them here (live dashboard).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from uuid import UUID


class EventBus(ABC):
    @abstractmethod
    async def publish(self, run_id: UUID, event: dict) -> None:
        """Publish a single traced event for a run."""

    @abstractmethod
    def subscribe(self, run_id: UUID) -> AsyncIterator[dict]:
        """Async-iterate live events for a run until the run completes."""
