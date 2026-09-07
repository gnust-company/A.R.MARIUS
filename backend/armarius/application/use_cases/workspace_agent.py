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
from uuid import UUID, uuid4

from armarius.application.use_cases.enrollment import AgentService
from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.marius import Marius
from armarius.shared.clock import utcnow
from armarius.shared.errors import Conflict, NotFound

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


class WorkspaceAgentService:
    def __init__(self, uow_factory: UowFactory, agents: AgentService | None = None) -> None:
        self._uow = uow_factory
        # The one thing in the product that builds an agent. Handed in rather than reached for
        # so this service stays about the seat, and so a test can watch what was asked of it.
        self._agents = agents or AgentService(uow_factory)

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
            instructions=HOST_INSTRUCTIONS,
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
        self, workspace_id: UUID, candidates: Sequence[UUID]
    ) -> Marius | None:
        """Put an unplaced host to work, the first time this workspace has somewhere to work.

        Called when a machine reports what it can run (FR-112). Returns the host it placed, or
        ``None`` when there was nothing to do — no host, host already placed, or nothing among
        `candidates` able to take work. *Nothing to do* is the ordinary case and must not read
        as a failure: this runs on every sync a machine ever sends.

        Placed **once**. A second runtime appearing later does not move it: an agent is
        attached to one place for life, and the host is not an exception (FR-007) — which is
        also why the port this goes through has no `move` on it.

        `candidates` are placement ids and nothing more. The caller knows which machine
        reported them and what tool each one runs; this layer must not, so it asks the
        placement itself whether it can take work rather than reading anything off the caller
        (Constitution III).

        Which one, when several can: the smallest id. The domain's view of a place has no age
        — deliberately, it is one of the things infrastructure keeps to itself — so the stable
        thing available here is the id, and a stable rule matters more than a meaningful one.
        The alternative is *whatever order the rows arrived in*, which is the same workspace
        answering differently on two identical syncs.
        """
        if not candidates:
            return None
        host = await self.ensure_workspace_agent(workspace_id)
        if host is None:
            return None
        async with self._uow() as uow:
            placed = await uow.placements.placed_at([host.id])
            if placed.get(host.id) is not None:
                return None
            chosen = None
            for placement_id in sorted(set(candidates), key=str):
                place = await uow.placements.get(workspace_id, placement_id)
                if place is not None and place.ready and place.carried_by:
                    chosen = place
                    break
            if chosen is None:
                return None
            try:
                await uow.placements.attach(host.id, workspace_id, chosen.id)
            except Conflict:
                # Two machines finished their first sync at the same moment and both got past
                # the check above. The answer to *somebody else placed it a millisecond ago* is
                # the same as the answer to *it was already placed*: nothing to do. Left to
                # travel, this would come back to a daemon as a 409 on the call where it reports
                # what it can run — a machine refused for a reason that is not about it.
                return None
            host.adapter_type = chosen.carried_by
            host.updated_at = utcnow()
            await uow.mariuses.update(host)
            await uow.commit()
            return host

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
