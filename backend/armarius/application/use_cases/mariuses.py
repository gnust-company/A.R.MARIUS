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
from armarius.domain.entities.placement import NOT_PLACED, PLACEMENT_NOT_READY
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
    ) -> Marius:
        """Edit an existing Marius (partial). Token and liveness are untouched."""
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
            marius.updated_at = utcnow()
            updated = await uow.mariuses.update(marius)
            await uow.commit()
            return updated

    async def set_skill_installs(
        self, marius_id: UUID, updates: dict[str, str]
    ) -> Marius:
        """Merge per-skill install-state updates (slug → pending|installed|failed) into an
        agent (#74). Used when pushing a skill (→ pending/failed) and when the agent confirms
        an install (→ installed). Other install states are left untouched."""
        async with self._uow() as uow:
            marius = await uow.mariuses.get(marius_id)
            if marius is None:
                raise NotFound("agent_not_found")
            marius.skill_installs = {**marius.skill_installs, **updates}
            marius.updated_at = utcnow()
            updated = await uow.mariuses.update(marius)
            await uow.commit()
            return updated

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
