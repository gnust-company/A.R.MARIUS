"""Adapts the per-task SSE `TopicEventBus` to the `TaskTracePublisher` port.

Publishing run-trace events onto the `task:{task_id}` topic makes them appear on the
Sprint-4 per-task stream (`GET /v1/tasks/{id}/stream`) that a Room already subscribes to.
"""

from __future__ import annotations

from uuid import UUID

from armarius.application.ports.task_trace import TaskTracePublisher
from armarius.infrastructure.events.topic_bus import TopicEventBus


class ControlBusTaskTrace(TaskTracePublisher):
    def __init__(self, control_bus: TopicEventBus) -> None:
        self._bus = control_bus

    async def publish(self, task_id: UUID, type: str, data: dict) -> None:
        await self._bus.publish(f"task:{task_id}", type, data)
