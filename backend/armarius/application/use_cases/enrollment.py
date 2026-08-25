"""Creating an agent — the only way one comes into existence (FR-007g).

Four things and no more: a name, what the agent is told to be, what it can do, and where it
works. That is the whole of it, and it is deliberately the same shape the runtime this
feature is built on already uses.

Everything that used to be here belonged to a world without a daemon. Back then Armarius
reached an agent by calling a gateway somebody else was running, so creating an agent meant
collecting that gateway's address and key, proving they answered, and pushing a setup prompt
down the wire so the agent could learn who it was. None of those four steps has anything left
to do: the daemon runs on the user's own machine and asks for work rather than being called,
so there is no address to collect, nothing to probe, and no setup to push (FR-040a). The
agent's own long-lived token went with them — the system has exactly two tokens, the daemon's
and the run's, and the daemon's is the only one a person ever handles (FR-014a).

What replaced the setup prompt is not a smaller prompt. `instructions` goes down with *every*
run in the claim packet (FR-007i), so an agent cannot drift away from what it was told, and a
compressed session cannot lose it.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from uuid import UUID

from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.marius import Marius
from armarius.shared.clock import utcnow
from armarius.shared.errors import BadRequest, Conflict, NotFound


class PlacementNotReady(BadRequest):
    """The chosen placement exists in this workspace but cannot take work right now.

    Kept apart from *not found* on purpose: one means look again, the other means fix the
    thing you already picked, and only the person on the other end can tell those apart.
    """


class NameTaken(Conflict):
    """Another agent in this workspace already answers to that name (FR-007h)."""


def _default_token() -> str:
    return f"arm_{secrets.token_urlsafe(32)}"


class AgentService:
    """The one create path. There is no second one, by design (FR-007f)."""

    def __init__(
        self,
        uow_factory: UowFactory,
        *,
        token_factory: Callable[[], str] = _default_token,
    ) -> None:
        self._uow = uow_factory
        self._mint_token = token_factory

    async def create(
        self,
        workspace_id: UUID,
        name: str,
        *,
        placement_id: UUID,
        instructions: str = "",
        description: str = "",
        adapter_type: str = "echo",
        skills: list[str] | None = None,
        skill_ids: list[str] | None = None,
        owner_user_id: str | None = None,
    ) -> Marius:
        """Create an agent and put it where it will work, in one transaction.

        `placement_id` is required and has no default (FR-007, FR-007f). An agent works in
        exactly one place, chosen here and never again, so there is no such thing as an
        agent that has not been placed yet — the attachment is written inside the very
        transaction that creates the agent, and either both land or neither does. A default
        would quietly reintroduce the state this requirement exists to abolish.

        No role is taken, here or anywhere. How an agent behaves comes from `instructions`
        and nothing else; a project supplies the work, not a second personality
        (Constitution V, FR-007l).
        """
        now = utcnow()
        async with self._uow() as uow:
            if await uow.workspaces.get(workspace_id) is None:
                raise NotFound("workspace_not_found")

            # Everything that can refuse, refuses before the agent is built. An agent that
            # exists for a moment and is then rolled back has still burned a name, and on a
            # failure path nobody is watching, "rolled back" is a promise rather than a fact.
            taken = await uow.mariuses.list_by_workspace(workspace_id)
            if any(one.name.strip().lower() == name.strip().lower() for one in taken):
                raise NameTaken("agent_name_taken", name=name)

            placement = await uow.placements.get(workspace_id, placement_id)
            if placement is None:
                raise NotFound("placement_not_found")
            if not placement.ready:
                raise PlacementNotReady(
                    "placement_not_ready",
                    reason=placement.not_ready_reason or "unknown",
                )

            marius = Marius(
                workspace_id=workspace_id,
                name=name,
                instructions=instructions,
                description=description,
                skills=skills or [],
                skill_ids=skill_ids or [],
                adapter_type=adapter_type,
                owner_user_id=owner_user_id,
                created_at=now,
                updated_at=now,
            )
            # The agent's own long-lived token is on its way out (FR-014a): the system is
            # meant to have two tokens, the daemon's and the run's. It is still minted here
            # because `/agent/*` has nothing else to authenticate with yet, and an agent
            # created without one would simply be locked out. Nothing pushes it anywhere any
            # more — it is read back from the database by whatever still needs it. T039d
            # removes it, once the run token can carry that traffic.
            marius.activate(self._mint_token(), now)
            created = await uow.mariuses.add(marius)
            await uow.placements.attach(created.id, workspace_id, placement.id)
            await uow.commit()
            return created
