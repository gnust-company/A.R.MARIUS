"""What has to be forgotten when a workspace, an agent or a run is deleted.

The six daemon tables hang off `workspaces`, `mariuses` and `runs` by real foreign keys with
no `ON DELETE CASCADE` — the same choice the rest of this schema makes, so that the cascade
is written down rather than inherited from whichever database happens to be running. The
cost of that choice is that every delete has to say what it takes with it, and a delete that
forgets one of these tables orphans rows on SQLite and fails outright on Postgres.

The list lives here, beside the models it is a list of, so a seventh table is added by
editing the file that defines it rather than by remembering which two repositories delete.

Order matters and is the reason these are functions rather than a loop: a child goes before
its parent, always.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from armarius.infrastructure.daemon.models import (
    AgentWorkplaceBindingModel,
    DaemonLinkCodeModel,
    MachineModel,
    RunClaimModel,
    WorkplaceModel,
)


async def forget_claims_of_runs(session: AsyncSession, run_ids: Sequence[UUID]) -> None:
    """Drop the claims on runs that are about to be deleted.

    Must be called *before* the runs go. A claim is which machine holds a run, so it cannot
    outlive the run it is about — and it points at it by foreign key, so it cannot even try.
    """
    if not run_ids:
        return
    await session.execute(
        delete(RunClaimModel).where(RunClaimModel.run_id.in_(list(run_ids)))
    )


async def forget_agent(session: AsyncSession, marius_id: UUID) -> None:
    """Release the workplace an agent was attached to.

    The workplace itself stays. It is a property of the machine, shared with every other
    agent living there (FR-007a), and one agent being deleted says nothing about it.
    """
    await session.execute(
        delete(AgentWorkplaceBindingModel).where(
            AgentWorkplaceBindingModel.marius_id == marius_id
        )
    )


async def forget_workspace(session: AsyncSession, workspace_id: UUID) -> None:
    """Everything a deleted workspace takes with it, machines included.

    A machine is enrolled into exactly one workspace and has no meaning outside it: with the
    workspace gone there is nothing left for it to be a machine *of*. Its daemon finds out
    the next time it asks for anything, which is the same way it finds out about a revoked
    token.
    """
    await session.execute(
        delete(AgentWorkplaceBindingModel).where(
            AgentWorkplaceBindingModel.workspace_id == workspace_id
        )
    )
    await session.execute(
        delete(RunClaimModel).where(RunClaimModel.workspace_id == workspace_id)
    )
    # Before machines: a code that was already approved points at the machine it admitted.
    await session.execute(
        delete(DaemonLinkCodeModel).where(
            DaemonLinkCodeModel.workspace_id == workspace_id
        )
    )
    await session.execute(
        delete(WorkplaceModel).where(WorkplaceModel.workspace_id == workspace_id)
    )
    await session.execute(
        delete(MachineModel).where(MachineModel.workspace_id == workspace_id)
    )
