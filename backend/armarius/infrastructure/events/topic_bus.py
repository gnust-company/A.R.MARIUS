"""Topic-keyed in-process pub/sub backing the Hybrid SSE channels (API_CONTRACT §2, §8).

Two server→browser streams ride this bus, distinguished only by topic string:
  - workspace control-plane — topic ``ws:{workspace_id}``  (always-on; light events)
  - per-task run trace      — topic ``task:{task_id}``      (opened while a Room is on screen)

Each event carries a process-monotonic ``seq`` used as the SSE event id, and every topic
keeps a bounded replay buffer so a reconnecting client can resume from ``Last-Event-ID``
(re-delivering everything it missed, then live-tailing). Single-process Phase-0: the seam
to swap for Redis pub/sub is this class; the stream endpoints stay the same. Web-App-only —
agents never read SSE.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class StreamEvent:
    seq: int
    type: str
    data: dict


class TopicEventBus:
    def __init__(self, replay_size: int = 256) -> None:
        self._seq = 0
        self._buffers: dict[str, deque[StreamEvent]] = defaultdict(
            lambda: deque(maxlen=replay_size)
        )
        self._subs: dict[str, set[asyncio.Queue[StreamEvent]]] = defaultdict(set)

    async def publish(self, topic: str, type: str, data: dict) -> int:
        """Append an event to a topic and fan it out to live subscribers. Returns its seq."""
        self._seq += 1
        event = StreamEvent(seq=self._seq, type=type, data=dict(data))
        self._buffers[topic].append(event)
        for queue in list(self._subs.get(topic, ())):
            queue.put_nowait(event)
        return event.seq

    def register(
        self, topic: str
    ) -> tuple[asyncio.Queue[StreamEvent], Callable[[], None]]:
        """Attach a live queue to a topic; returns it with its unregister callback.

        Register *before* reading :meth:`backlog` so an event published during hand-off
        lands in the queue (de-duplicate by seq on the consumer side) — no gap, no loss.
        """
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        self._subs[topic].add(queue)

        def unregister() -> None:
            subs = self._subs.get(topic)
            if subs is not None:
                subs.discard(queue)
                if not subs:
                    self._subs.pop(topic, None)

        return queue, unregister

    def backlog(self, topic: str, *, after_seq: int = 0) -> list[StreamEvent]:
        """Buffered events after ``after_seq`` (the Last-Event-ID resume window)."""
        return [e for e in list(self._buffers.get(topic, ())) if e.seq > after_seq]

    async def subscribe(
        self, topic: str, *, after_seq: int = 0
    ) -> AsyncIterator[StreamEvent]:
        """Replay everything after ``after_seq``, then live-tail. (Used directly in tests;
        the SSE endpoint drives :meth:`register`/:meth:`backlog` so it can poll for client
        disconnect while a topic is idle.)"""
        queue, unregister = self.register(topic)
        try:
            last = after_seq
            for event in self.backlog(topic, after_seq=last):
                last = event.seq
                yield event
            while True:
                event = await queue.get()
                if event.seq <= last:
                    continue
                last = event.seq
                yield event
        finally:
            unregister()
