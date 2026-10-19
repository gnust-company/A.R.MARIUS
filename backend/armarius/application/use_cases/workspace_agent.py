"""Workspace Agent designation (LLD §3.1, §6) — a workspace's host agent.

The Workspace Agent is the Marius that greets owners and runs onboarding. Who holds the
seat is recorded on ``workspace.workspace_agent_id`` — the single source of truth (#32);
the "Workspace Agent" role string is display-only. The onboarding playbook is no longer a
granted skill: it is injected into the agent's prompt when a project-setup chat starts (#61).

Under operator-invite (issue #63) the host was **never auto-created**: it existed only if the
operator invited an agent and ticked "Make Workspace Agent". `ensure_workspace_agent` stays
lookup-only for that reason — it returns the designated host or ``None``.

That rule has been half reversed (FR-110). #63 forbade auto-creation because an agent without
a gateway address and a key was a shell that could neither wake nor authenticate its
callbacks. Since spec 002 an agent has neither of those things at all: what carries its turn
is a **runtime**, and a runtime arrives when the person links a machine — which is after the
workspace exists. So the thing #63 was refusing (a shell that can never work) is not the thing
`provide_host` creates (an agent not placed *yet*), and the second is a state FR-007f already
defined: *an agent bound to no workplace must read as offline, never as a silent failure*.

What #63 decided and still stands: nothing here mints a credential, and the host is a plain
`Marius` pointed at by ``workspace.workspace_agent_id`` (#32) rather than a kind of its own.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from armarius.application.use_cases.enrollment import AgentService, PlacementNotReady
from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.marius import Marius
from armarius.domain.entities.placement import PLACEMENT_CARRIES_NOTHING
from armarius.shared.clock import utcnow
from armarius.shared.errors import Conflict, NotFound

if TYPE_CHECKING:
    from armarius.application.use_cases.liveness import LivenessEngine

WORKSPACE_AGENT_ROLE = "Workspace Agent"

# The display name the host is created with (FR-110). One string, so calling it something else
# is a one-line change. It is a name for people to read; what the agent is *told* is below, in
# English, because that is text the system sends to an agent (Constitution VII).
HOST_NAME = "Livia"

# What the host is told to be, sent to it on every run (FR-007i, FR-115).
#
# Short on purpose. The project-setup interview injects its own playbook when a setup chat
# starts (#61), so repeating any of it here would be two sources for one behaviour, and the one
# that drifts is the one nobody is looking at.
HOST_INSTRUCTIONS = (
    "You are the host of this workspace. You are the first agent its owner talks to: you "
    "greet them, help them shape their first project, and answer questions about what this "
    "workspace can do. You do not carry project work yourself — other agents are hired for "
    "that, and your job is to help decide what to hire and what to ask for."
)

# What the host's *own* instructions start as — the half its owner writes (FR-124, FR-115).
#
# The job lives above, in the system prompt, which no door lets a person touch. This is only how
# the conversation goes, which is exactly the part a person should be free to change: it is shown
# in an editable box on the last first step and on the agent's page, and whatever they leave in
# it is theirs from then on. English because it is sent to the agent, and shown as it is sent —
# the exception Constitution VII (2.1.0) makes for showing what an agent actually receives.
#
# Deliberately silent about the job. Repeating it here would be two places to read one rule, and
# the copy a person edits would be the one that drifts.
HOST_DEFAULT_INSTRUCTIONS = (
    "Reply in the language the owner writes to you in. Keep answers short and concrete. When "
    "something is unclear, ask one question at a time instead of guessing. Before suggesting "
    "which agents to hire, ask what the owner is trying to get done."
)


class WorkspaceAgentService:
    def __init__(
        self,
        uow_factory: UowFactory,
        agents: AgentService | None = None,
        liveness: LivenessEngine | None = None,
    ) -> None:
        self._uow = uow_factory
        # The one thing in the product that builds an agent. Handed in rather than reached for
        # so this service stays about the seat, and so a test can watch what was asked of it.
        self._agents = agents or AgentService(uow_factory)
        # Who measures the host once it has somewhere to work (FR-006e). Optional only so a
        # test about the seat rules need not build a clock; the running service passes it.
        self._liveness = liveness

    async def ensure_workspace_agent(self, workspace_id: UUID) -> Marius | None:
        """The workspace's designated host agent, or ``None`` if none was set up.

        Lookup-only under operator-invite (#63): the host must have been invited by the
        operator with gateway creds (and seated via `designate`). Backfills the pointer for
        workspaces designated before it was wired (#32), but never creates a host itself.
        """
        async with self._uow() as uow:
            ws = await uow.workspaces.get(workspace_id)
            if ws is None:
                raise NotFound("workspace_not_found")
            if ws.workspace_agent_id is not None:
                host = await uow.mariuses.get(ws.workspace_agent_id)
                if host is not None:
                    return host
            # Backfill: workspaces designated before the pointer was wired (#32)
            # identified their host by the role string alone.
            legacy = [
                m
                for m in await uow.mariuses.list_by_workspace(workspace_id)
                if m.role == WORKSPACE_AGENT_ROLE
            ]
            if legacy:
                ws.workspace_agent_id = legacy[0].id
                await uow.workspaces.update(ws)
                await uow.commit()
                return legacy[0]
            return None

    async def provide_host(self, workspace_id: UUID) -> Marius:
        """The workspace's host, created **unplaced** if it does not have one yet (FR-110).

        A door of its own, on purpose (FR-114). The general way to make an agent requires a
        place and has no default for it, and that must not change: an agent a person creates is
        placed by that person, and a default there would quietly abolish the requirement for
        everybody. The host is not that — it exists from the moment the workspace does, and the
        workspace exists before any machine has been linked.

        The agent itself is built by `AgentService.create_unplaced`, not here. This module owns
        *who the host is* and *who holds the seat*; `enrollment.py` owns building agents, and it
        is the only place in the product allowed to — a guard in the test suite enforces that, so
        that reading one file shows every way an agent can come into existence.

        Unplaced means offline with a reason a person can read (FR-111) — machinery that already
        existed, because FR-007f named this state before anything could reach it. `place_host` is
        what ends it.

        Idempotent, and never demotes: a workspace whose owner already invited a host of their
        own keeps that host untouched (FR-113).

        Two transactions, not one: the agent is committed by the call above, the seat is written
        here. Dying in between leaves a host that exists and is not pointed at — and that heals
        itself, because the role is written at creation and `ensure_workspace_agent` seats an
        agent holding the role when the pointer is empty (the #32 backfill).
        """
        existing = await self.ensure_workspace_agent(workspace_id)
        if existing is not None:
            return existing

        async with self._uow() as uow:
            ws = await uow.workspaces.get(workspace_id)
            if ws is None:
                raise NotFound("workspace_not_found")
            taken = await uow.mariuses.list_by_workspace(workspace_id)
            # A host that was made and never seated, if there is one. Three conditions, and
            # together they cannot describe anything else: this name, no seat, and nowhere to
            # work. A person cannot create an agent with nowhere to work — that door requires a
            # place and has no default (FR-007f) — and a place is never taken away from an agent
            # afterwards, so *not placed* is a state only `create_unplaced` can leave behind, and
            # its only caller is four lines below.
            #
            # Why the question is asked of the placement rather than read off the agent: whether
            # an agent has somewhere to work is the placement's answer. This layer is not allowed
            # to know what a place *is*, and reading the field that names the tool would be it
            # knowing (Constitution III, FR-083).
            candidates = [
                one
                for one in taken
                if one.name.strip().lower() == HOST_NAME.lower() and one.role == ""
            ]
            placed = (
                await uow.placements.placed_at([one.id for one in candidates])
                if candidates
                else {}
            )
            orphan = next((one for one in candidates if one.id not in placed), None)

        if orphan is not None:
            return await self.designate(workspace_id, orphan.id)

        host = await self._agents.create_unplaced(
            workspace_id,
            self._free_name(taken),
            # The product's half, not the owner's. Their half starts as the default below and
            # is theirs to rewrite; this one no door lets them touch, so editing their host
            # cannot delete the job that makes it one (FR-007m, FR-124).
            system_instructions=HOST_INSTRUCTIONS,
            instructions=HOST_DEFAULT_INSTRUCTIONS,
            owner_user_id=ws.owner_user_id,
        )
        return await self.designate(workspace_id, host.id)

    @staticmethod
    def _free_name(taken: Sequence[Marius]) -> str:
        """`Livia`, or the first `Livia N` nobody is using.

        Names are unique within a workspace (FR-007h), and somebody may have used this one
        already. A refusal here would fail the creation of a whole workspace over a display
        name, which is the wrong trade by a wide margin (FR-113).
        """
        used = {one.name.strip().lower() for one in taken}
        if HOST_NAME.lower() not in used:
            return HOST_NAME
        for n in range(2, 100):
            candidate = f"{HOST_NAME} {n}"
            if candidate.lower() not in used:
                return candidate
        # A hundred agents called Livia is not a case worth a branch of its own; the database's
        # own uniqueness constraint is the backstop, and it raises NameTaken.
        return f"{HOST_NAME} {uuid4().hex[:6]}"

    async def place_host(
        self,
        workspace_id: UUID,
        marius_id: UUID,
        placement_id: UUID,
        *,
        instructions: str | None = None,
    ) -> Marius:
        """Put the host to work where its owner chose (spec 003 FR-125, FR-126, FR-128).

        This used to run by itself on the first sync a machine sent, and pick the placement
        with the smallest id. Stable, and meaningless to the person it happened to: on a
        machine with two runtimes it chose one for them, and FR-007 then held the choice for
        good. Now nothing places the host but this call, and this call is a person choosing.

        **Only the host.** Taking a machine out of a workspace leaves every agent on it with
        nowhere to work (`infrastructure/daemon/cleanup.py`), and a door that placed any such
        agent would be a way round FR-007 for all of them — a decision the owner has kept
        closed. The host is different in kind: it is the one agent *born* with nowhere to work
        (FR-114), and a workspace needs it to set up a project. So an agent not holding the
        seat is refused with `placement_is_fixed`, and a host that lost its machine may be
        placed again, because there is nothing left to move it from.

        `instructions`, when given, is written in the same transaction as the placement
        (FR-126): a host with its owner's words saved and nowhere to work is the half-finished
        state that step exists to avoid. `None` leaves them as they are; an empty string is a
        real answer and is saved.

        Only the placement id comes in, and the placement itself is asked whether it can take
        work — the caller knows what runtime it is, this layer must not (Constitution III).
        """
        host = await self.ensure_workspace_agent(workspace_id)
        async with self._uow() as uow:
            agent = await uow.mariuses.get(marius_id)
            if agent is None or agent.workspace_id != workspace_id:
                raise NotFound("agent_not_found")
            if host is None or host.id != agent.id:
                raise Conflict("placement_is_fixed")
            if (await uow.placements.placed_at([agent.id])).get(agent.id) is not None:
                raise Conflict("agent_already_placed")

            place = await uow.placements.get(workspace_id, placement_id)
            if place is None:
                raise NotFound("placement_not_found")
            if not place.ready:
                raise PlacementNotReady(
                    "placement_not_ready", reason=place.not_ready_reason or "unknown"
                )
            if not place.carried_by:
                raise PlacementNotReady("placement_not_ready", reason=PLACEMENT_CARRIES_NOTHING)

            # Two windows finishing the last step at once both get past the check above. The
            # second one's write is refused by the one-binding-per-agent rule and comes back
            # as the same `agent_already_placed` — the answer to *somebody placed it a moment
            # ago* is the answer to *it was already placed* (FR-127).
            await uow.placements.attach(agent.id, workspace_id, place.id)
            agent.adapter_type = place.carried_by
            if instructions is not None:
                agent.instructions = instructions
            agent.updated_at = utcnow()
            await uow.mariuses.update(agent)
            await uow.commit()
        if self._liveness is None:
            return agent
        # It has been missing its looks since the workspace was made, and its next one could be
        # half an hour off. Measure it now, so the person it was placed for can talk to it
        # (FR-006e, FR-126).
        await self._liveness.placement_changed([agent.id])
        async with self._uow() as uow:
            return await uow.mariuses.get(agent.id) or agent

    async def designate(self, workspace_id: UUID, marius_id: UUID) -> Marius:
        """Hand the host seat to this Marius. Any sitting host is demoted to a plain
        agent — role cleared, token/tasks untouched — never revoked (#32). Idempotent
        when the Marius already holds the seat.

        Read-modify-write without row locking: two concurrent designates can both see
        the same sitting host and the pointer goes to whichever commits last. Since the
        pointer is the source of truth the seat stays consistent; the loser is only
        left with a stale "Workspace Agent" role string. Same deferral as the #27
        delete guard — SELECT ... FOR UPDATE once Postgres is in prod."""
        now = utcnow()
        async with self._uow() as uow:
            ws = await uow.workspaces.get(workspace_id)
            if ws is None:
                raise NotFound("workspace_not_found")
            marius = await uow.mariuses.get(marius_id)
            if marius is None or marius.workspace_id != workspace_id:
                raise NotFound("agent_not_found")
            if ws.workspace_agent_id == marius.id:
                return marius

            sitting = None
            if ws.workspace_agent_id is not None:
                sitting = await uow.mariuses.get(ws.workspace_agent_id)
            if sitting is None:  # pre-#32 workspace: the host is known by role only
                sitting = next(
                    (
                        m
                        for m in await uow.mariuses.list_by_workspace(workspace_id)
                        if m.role == WORKSPACE_AGENT_ROLE and m.id != marius.id
                    ),
                    None,
                )
            if sitting is not None:
                sitting.role = ""
                sitting.updated_at = now
                await uow.mariuses.update(sitting)

            marius.role = WORKSPACE_AGENT_ROLE
            marius.updated_at = now
            await uow.mariuses.update(marius)
            ws.workspace_agent_id = marius.id
            await uow.workspaces.update(ws)
            await uow.commit()
            return marius
