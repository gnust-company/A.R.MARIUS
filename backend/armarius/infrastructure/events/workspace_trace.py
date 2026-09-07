"""Concrete workspace-channel publisher — binds the port to the in-process topic bus.

One event is named here rather than beside the port, and the reason is a rule, not a
preference. ``machine.linked`` is about a machine, and Constitution III says the business
layers never learn where work runs — a guard enforces it on every identifier under
``domain/`` and ``application/``, and it caught this event's first home. The port stays
generic (``publish(workspace_id, type, data)``), so infrastructure can announce an
infrastructure fact through it without the layers above ever having a word for it.
"""

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


# A machine was admitted to a workspace. The screen that needs it is the last of the three
# first steps (spec 003 FR-106): the daemon opens the approval page in a window of its own, so
# the moment somebody approves there are two windows open — the one that just did the job, and
# the one still standing on step three. Without this the second one learns nothing, and the only
# ways left are asking in a loop, which Constitution IV forbids, or leaving a person with two
# windows and no idea which is theirs.
#
# Emitted when the machine is APPROVED, not when it later spends its code for a token: the step
# asks a person to approve a machine, and that is the act being announced.
EVENT_MACHINE_LINKED = "machine.linked"


async def announce_machine_linked(
    trace: WorkspaceTracePublisher | None, workspace_id: UUID
) -> None:
    """Announce that a machine was approved into a workspace (no-op if not wired).

    Carries the workspace and nothing else. A listener already subscribed to it learns the one
    thing it asked about — *something came in, go and look* — and principle 1 of
    ``contracts/push-events.md`` keeps it that way: the event is a signal, never the state.

    There is deliberately no machine id in here, and no link code. No machine row exists yet at
    approval time; one is written when the daemon spends the code it has now been given. And the
    code is a live credential until that happens, while this channel is the one stream a browser
    holds open for a whole session.
    """
    if trace is None:
        return
    await trace.publish(
        workspace_id,
        EVENT_MACHINE_LINKED,
        {"workspace_id": str(workspace_id)},
    )
