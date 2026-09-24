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

# The two edges of an agent's liveness, as a screen keyed by agent needs them. Emitted on the
# *edge*, never on every tick.
#
# `marius.offline` came first, as the missing half of a pair: `marius.online` used to be
# published by /agent/me on first contact after silence, so the status dot could only ever move
# one way. Then agents stopped calling /agent/me at all — the work runs on a machine now — and
# the pair flipped: an agent brought back by the liveness clock came back *silently*, and every
# screen that had shown it offline kept showing it offline until somebody reloaded the page.
# The direct chat (FR-007p) is where that bites hardest: its box stays locked for an agent that
# has been reachable for minutes. So the clock announces both edges now.
EVENT_MARIUS_OFFLINE = "marius.offline"
EVENT_MARIUS_ONLINE = "marius.online"

# The team-building interview moved a step: the agent asked its next question, or posted the
# draft it wants confirmed. The screen holding that chat open cannot learn this any other way
# — the turn runs on somebody's machine and the answer arrives by a road the browser is not on
# (FR-040c). Ids only, like the two above: it says *go and read the chat again*, never what the
# agent said (contracts/push-events.md, principle 1 and principle 4).
EVENT_ONBOARDING_CHANGED = "onboarding.changed"


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


async def announce_onboarding_step(
    trace: WorkspaceTracePublisher | None, workspace_id: UUID | None, session_id: UUID
) -> None:
    """Announce that a team-building chat has something new in it (no-op if not wired)."""
    if trace is None or workspace_id is None:
        return
    await trace.publish(
        workspace_id,
        EVENT_ONBOARDING_CHANGED,
        {"session_id": str(session_id)},
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


async def announce_agent_online(
    trace: WorkspaceTracePublisher | None, marius: Marius
) -> None:
    """Announce that an agent crossed back into being able to work (no-op if not wired).

    The opposite edge of ``announce_agent_offline``, and the same shape for the same reason:
    an id, and nothing a listener could mistake for the state itself.
    """
    if trace is None or marius.workspace_id is None:
        return
    await trace.publish(
        marius.workspace_id,
        EVENT_MARIUS_ONLINE,
        {"marius_id": str(marius.id)},
    )

