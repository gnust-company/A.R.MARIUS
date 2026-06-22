"""In-process event bus backing the live trace SSE (§8.1).

Single-process Phase-0 implementation. For multi-instance deployments this is the
seam to swap for Redis pub/sub — the `EventBus` port stays the same.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from armarius.application.ports.event_bus import EventBus

_TERMINAL_TYPES = {"run.finished"}


class InMemoryEventBus(EventBus):
    def __init__(self) -> None:
        self._subs: dict[UUID, set[asyncio.Queue[dict]]] = {}

    async def publish(self, run_id: UUID, event: dict) -> None:
        for queue in list(self._subs.get(run_id, set())):
            queue.put_nowait(event)

    async def subscribe(self, run_id: UUID) -> AsyncIterator[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue()
        self._subs.setdefault(run_id, set()).add(queue)
        try:
            while True:
                event = await queue.get()
                yield event
                if event.get("type") in _TERMINAL_TYPES:
                    return
        finally:
            subs = self._subs.get(run_id)
            if subs is not None:
                subs.discard(queue)
                if not subs:
                    self._subs.pop(run_id, None)
