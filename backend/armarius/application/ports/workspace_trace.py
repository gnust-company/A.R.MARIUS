"""Workspace-channel publisher port — the workspace-wide half of the §8.1 live tee.

A run already announces itself on two channels: the per-*run* ``EventBus`` (whoever is
watching that one execution) and the per-*task* channel (the Room that task is open in).
Both require the watcher to already know which run or which task it cares about.

The agent detail screen does not. It asks a different question — "has anything happened
to *this agent*?" — and no channel could answer it, so the screen fell back to asking the
server again every fifteen seconds, which Constitution IV forbids (FR-080). This port is
the channel that answers it: a run's lifecycle, announced on the workspace the agent
belongs to, carrying ids only (contracts/push-events.md, principle 4).

Same shape as :class:`TaskTracePublisher` and for the same reason — the application layer
states *what* it wants announced and stays ignorant of the concrete ``TopicEventBus``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from armarius.domain.entities.marius import Marius
from armarius.domain.entities.run import Run

# The events a screen keyed by agent listens for. Named here, beside the port, because the
# name is part of the push contract rather than an implementation detail of whoever emits
# it — and two separate callers emit it (the wake engine and the hung-run reaper).
EVENT_RUN_STATE_CHANGED = "run.status_changed"

# The missing half of the pair. `marius.online` (published by /agent/me on first contact
# after silence) said an agent came back; nothing said one had gone. The directory's status
# dot could therefore only ever move one way, and the direction it could not move is the one
# a patron needs to see. Emitted on the *edge* into offline, never on every idle tick.
EVENT_MARIUS_OFFLINE = "marius.offline"


class WorkspaceTracePublisher(ABC):
    @abstractmethod
    async def publish(
        self, workspace_id: UUID, type: str, data: dict[str, object]
    ) -> None:
        """Publish one event onto a workspace's control-plane channel."""


async def announce_run_state(
    trace: WorkspaceTracePublisher | None, run: Run, marius: Marius
) -> None:
    """Announce a run's state on the agent's workspace channel (no-op if not wired).

    Both the name and the payload shape are the contract, so both live here: the wake
    engine emits this for the transitions it drives, the hung-run reaper for the one it
    declares, and a listener cannot be asked to handle two different shapes of the same
    event.

    Ids and a status label only, never prompt or output text — the workspace channel is the
    one stream a browser holds open for a whole session, and principle 4 of
    ``contracts/push-events.md`` keeps content off it. A listener treats this as a signal
    and re-reads.

    Call it after every commit that moves a run's status. Miss one and the screen shows
    that run frozen at its previous status until the page is reloaded — which is exactly
    the failure the fifteen-second poll used to paper over.
    """
    if trace is None or marius.workspace_id is None:
        return
    await trace.publish(
        marius.workspace_id,
        EVENT_RUN_STATE_CHANGED,
        {
            "run_id": str(run.id),
            "marius_id": str(marius.id),
            "task_id": str(run.task_id) if run.task_id is not None else None,
            "project_id": str(run.project_id) if run.project_id is not None else None,
            "status": str(run.status),
        },
    )


async def announce_agent_offline(
    trace: WorkspaceTracePublisher | None, marius: Marius
) -> None:
    """Announce that an agent crossed into offline (no-op if not wired).

    Deliberately carries an id and nothing else — no liveness value. This is a *signal*
    under principle 1 of ``contracts/push-events.md``: the listener re-reads the agent
    rather than believing the event. Putting the new state in the payload is the tempting
    shortcut and it is the one that rots — the moment an event is the source of truth, a
    listener that misses it (replay window overflow, a reconnect gap) shows a wrong value
    with no way to notice, and every later event on this channel inherits the pattern.

    Matches ``marius.online``, which is emitted the same way on the opposite edge.
    """
    if trace is None or marius.workspace_id is None:
        return
    await trace.publish(
        marius.workspace_id,
        EVENT_MARIUS_OFFLINE,
        {"marius_id": str(marius.id)},
    )
