"""Marius (agent) use cases — read and edit the directory (§3.1).

Creating an agent is deliberately NOT here. There is exactly one way to make an agent — the
create path behind the route — and a second one in this layer would be a rule that holds only
on whichever path somebody happens to be looking at (FR-007f). The fixture the tests used to
get from here lives in `tests/support/agents.py`, where being scaffolding is the honest name
for it.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.marius import Marius
from armarius.domain.entities.placement import (
    NOT_PLACED,
    PLACEMENT_NOT_READY,
    OptionNotOffered,
    Placement,
    PlacementOption,
)
from armarius.shared.clock import utcnow
from armarius.shared.errors import NotFound


class MariusService:
    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow = uow_factory

    async def update(
        self,
        marius_id: UUID,
        *,
        name: str | None = None,
        role: str | None = None,
        skills: list[str] | None = None,
        skill_ids: list[str] | None = None,
        adapter_type: str | None = None,
        adapter_config: dict | None = None,
        placement_options: dict[str, str] | None = None,
    ) -> Marius:
        """Edit an existing Marius (partial). Token and liveness are untouched.

        `placement_options` is the one field here that can be refused, and it is refused by
        the same call the create path makes — `Placement.refuse_unchosen`. Two doors set
        this now, and a rule that holds at one of them is not a rule.

        **It takes effect on the next run, not the one in flight.** What an agent was set to
        is read when a machine claims a run and travels down inside that claim packet, so a
        run already out of the door is running on what was true when it left. Nothing here
        can reach it, and pretending otherwise would be a lie the screen repeats (FR-007k).
        """
        async with self._uow() as uow:
            marius = await uow.mariuses.get(marius_id)
            if marius is None:
                raise NotFound("agent_not_found")
            if name is not None:
                marius.name = name
            if role is not None:
                marius.role = role
            if skills is not None:
                marius.skills = skills
            if skill_ids is not None:
                marius.skill_ids = skill_ids
            if adapter_type is not None:
                marius.adapter_type = adapter_type
            if adapter_config is not None:
                marius.adapter_config = adapter_config
            if placement_options:
                marius.placement_options = await self._settle(
                    uow, marius, placement_options
                )
            marius.updated_at = utcnow()
            updated = await uow.mariuses.update(marius)
            await uow.commit()
            return updated

    async def _settle(
        self,
        uow,  # noqa: ANN001
        marius: Marius,
        chosen: dict[str, str],
    ) -> dict[str, str]:
        """What this agent is set to, after the person changed some of it (FR-007k).

        **Only what this call carries is checked, never the result of merging it in.** What
        a place offers is what its tool answered the last time it was asked, and that answer
        moves: a machine gets upgraded, a tool drops a level, and a value stored months ago
        is suddenly outside the list. Checking the merged settings would then refuse a
        rename — an edit that never went near the setting that went stale — and the person
        would have no way to find out why. A value already stored was accepted when it was
        chosen; what is being decided here is only what is being chosen now.

        Merged rather than replaced, for the same reason. A caller that sends one setting is
        changing one setting; the rest are not mentioned, and *not mentioned* is not the same
        as *cleared*. Clearing one is still expressible and stays a first-class act: an empty
        value means the tool's own default, which is exactly what FR-007k says an unset one
        does, and it survives the trip unrefused.
        """
        place = await self._place_of(uow, marius)
        if place is None:
            # Nowhere to work offers nothing to set, so every key is one the place never
            # offered — the same refusal, not a new one. An agent in this state cannot run
            # at all (FR-007f); being unable to change what it would have run with is the
            # smaller half of that, and it is not worth a second thing for a reader to learn.
            raise OptionNotOffered("placement_option_unknown", option=next(iter(chosen)))
        place.refuse_unchosen(chosen)
        return {**marius.placement_options, **chosen}

    async def _place_of(
        self,
        uow,  # noqa: ANN001
        marius: Marius,
    ) -> Placement | None:
        """Where this agent works, read whole — what the place *offers*, not just whether
        it is open.

        Two reads because the two ports answer two questions, and only one of them is asked
        of a whole roster at a time. `placed_at` says where an agent sits and whether that
        place can take work this minute, which is what a screen full of agents needs; it
        does not carry what the place accepts, because no screen full of agents wants it.
        `get` carries that, and it answers whether the place is shut or open — which is the
        wanted behaviour here. What a tool takes does not stop being true because somebody
        uninstalled it; refusing to let a setting be changed until the place reopens would
        be a rule nobody asked for, and the agent cannot run either way.
        """
        if marius.workspace_id is None:
            return None
        at = (await uow.placements.placed_at([marius.id])).get(marius.id)
        if at is None:
            return None
        return await uow.placements.get(marius.workspace_id, at.id)

    async def options_offered(self, marius_id: UUID) -> tuple[PlacementOption, ...]:
        """What may be set on this agent, as the place it works at answered it (FR-007k).

        Asked per agent rather than read off the list of places one may be *put* on. That
        list is a picker: it holds only the places still taking work, and it says nothing
        about which of them any given agent sits at. A screen built on it would have to
        guess, and would read *nothing to choose* for an agent whose CLI somebody
        uninstalled — when in truth its settings are perfectly well known and perfectly
        changeable, and will matter again the moment the CLI is put back.

        Empty is an ordinary answer: this place offers nothing to pick, and the agent runs
        on whatever its tool defaults to.
        """
        async with self._uow() as uow:
            marius = await uow.mariuses.get(marius_id)
            if marius is None:
                raise NotFound("agent_not_found")
            place = await self._place_of(uow, marius)
            return () if place is None else place.options

    async def delete(self, marius_id: UUID) -> None:
        """Remove a Marius from the directory.

        The Workspace Agent is just a flag (#50), not a protected system agent — it can
        be deleted like any other. When the host is removed, vacate the workspace's
        `workspace_agent_id` pointer so nothing dangles at a deleted Marius; workspace-
        level features that want a host fall back to manual until one is re-designated
        (a host is also re-created lazily on demand by `ensure_workspace_agent`).
        """
        async with self._uow() as uow:
            marius = await uow.mariuses.get(marius_id)
            if marius is None:
                raise NotFound("agent_not_found")
            ws = (
                await uow.workspaces.get(marius.workspace_id)
                if marius.workspace_id
                else None
            )
            if ws is not None and ws.workspace_agent_id == marius.id:
                ws.workspace_agent_id = None
                await uow.workspaces.update(ws)
            await uow.mariuses.remove(marius_id)
            await uow.commit()

    async def get(self, marius_id: UUID) -> Marius | None:
        async with self._uow() as uow:
            return await uow.mariuses.get(marius_id)

    async def list_directory(self, workspace_id: UUID) -> Sequence[Marius]:
        async with self._uow() as uow:
            return await uow.mariuses.list_by_workspace(workspace_id)

    async def offline_reasons(self, marius_ids: Sequence[UUID]) -> dict[UUID, str]:
        """Why each of these agents has nowhere to work. For the screen, and only that.

        This layer is not allowed to branch on the answer and does not: it collects codes
        and hands them on. The verdict *offline* was already decided elsewhere, off the
        same read, and nothing here can disagree with it — which is the whole reason the
        reason is fetched rather than reconstructed (FR-006c).

        An agent whose place is open is simply absent from the result. There is no code
        for "fine", because a caller that has to tell a well-agent's code from an
        ill-agent's code is a caller doing the branching this rule exists to prevent.
        """
        wanted = list(marius_ids)
        if not wanted:
            return {}
        async with self._uow() as uow:
            placed = await uow.placements.placed_at(wanted)
        reasons: dict[UUID, str] = {}
        for marius_id in wanted:
            placement = placed.get(marius_id)
            if placement is None:
                reasons[marius_id] = NOT_PLACED
            elif not placement.ready:
                reasons[marius_id] = placement.not_ready_reason or PLACEMENT_NOT_READY
        return reasons
