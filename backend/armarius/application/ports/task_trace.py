"""Task-trace publisher port — the per-task half of the §8.1 live tee.

The wake engine already persists a durable run log AND publishes to the per-*run*
`EventBus`. This port lets it ALSO tee each traced event onto the per-*task* SSE channel
(the Sprint-4 `task:{task_id}` stream a Room subscribes to), so a task's live run trace
shows up on the channel the Web App already watches — without the application layer
depending on the concrete `TopicEventBus`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class TaskTracePublisher(ABC):
    @abstractmethod
    async def publish(self, task_id: UUID, type: str, data: dict) -> None:
        """Publish one traced event onto a task's live channel."""
