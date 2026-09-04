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

from uuid import UUID

from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.marius import Marius, NameTaken
from armarius.domain.entities.placement import PLACEMENT_CARRIES_NOTHING
from armarius.shared.clock import utcnow
from armarius.shared.errors import BadRequest, NotFound


class PlacementNotReady(BadRequest):
    """The chosen placement exists in this workspace but cannot take work right now.

    Kept apart from *not found* on purpose: one means look again, the other means fix the
    thing you already picked, and only the person on the other end can tell those apart.
    """


class AgentService:
    """The one create path. There is no second one, by design (FR-007f)."""

    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow = uow_factory

    async def create(
        self,
        workspace_id: UUID,
        name: str,
        *,
        placement_id: UUID,
        instructions: str = "",
        description: str = "",
        placement_options: dict[str, str] | None = None,
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

        **Which tool carries this agent's turns is not a parameter of this call.** It is the
        place's answer, read off the placement and written down unchanged. There is no
        default here and there must not be one: a constant in this layer would be the
        business layer naming a runtime, which is precisely what Constitution III forbids —
        and the constant that used to sit here sent every agent ever created down a road
        built for demos.
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
            # What may be set on an agent is the **place's** answer, not the caller's
            # (FR-007k). Checked here rather than only where the screen builds its lists: a
            # screen rendered from the same data keeps an honest person right, and only this
            # keeps everybody right.
            chosen = {k: v for k, v in (placement_options or {}).items()}
            placement.refuse_unchosen(chosen)
            if not placement.carried_by:
                # Nothing a person did causes this, and it is refused all the same: an agent
                # created with no answer to *who does its work* is an agent no wake can ever
                # reach, and it would fail at the first turn instead of here.
                raise PlacementNotReady(
                    "placement_not_ready", reason=PLACEMENT_CARRIES_NOTHING
                )

            marius = Marius(
                workspace_id=workspace_id,
                name=name,
                instructions=instructions,
                description=description,
                skills=skills or [],
                skill_ids=skill_ids or [],
                adapter_type=placement.carried_by,
                placement_options=chosen,
                owner_user_id=owner_user_id,
                created_at=now,
                updated_at=now,
            )
            # No credential is minted here, and none is minted anywhere else either. An
            # agent is an identity, not a bearer: what opens a door is the token of the run
            # it is taking, and that is minted when a machine takes the run and dies with it
            # (FR-014a, FR-014g).
            created = await uow.mariuses.add(marius)
            await uow.placements.attach(created.id, workspace_id, placement.id)
            await uow.commit()
            return created
