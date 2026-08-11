"""Concrete workspace-channel publisher — binds the port to the in-process topic bus."""

from __future__ import annotations

from uuid import UUID

from armarius.application.ports.workspace_trace import WorkspaceTracePublisher
from armarius.infrastructure.events.topic_bus import TopicEventBus


class ControlBusWorkspaceTrace(WorkspaceTracePublisher):
    def __init__(self, control_bus: TopicEventBus) -> None:
        self._bus = control_bus

    async def publish(
        self, workspace_id: UUID, type: str, data: dict[str, object]
    ) -> None:
        await self._bus.publish(f"ws:{workspace_id}", type, data)
