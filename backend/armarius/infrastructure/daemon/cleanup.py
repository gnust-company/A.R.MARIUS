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

from sqlalchemy import delete, select
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


async def forget_machine(session: AsyncSession, machine_id: UUID) -> None:
    """Everything a removed machine takes with it (FR-001d).

    Same list as :func:`forget_workspace`, same order, narrowed to one machine — a child
    before its parent, always. The one table that is not narrowed by `machine_id` is the
    bindings: an agent is attached to a *workplace*, and the workplaces being removed are the
    ones this machine reported, so they are found through it.

    **A spent link code goes with the machine it admitted**, rather than being unlinked and
    left behind. That was the open question in T159, and what settles it is that nothing
    reads these rows: the only code in the product that touches `daemon_link_codes` is the
    linking flow itself, which looks up a *live* code by its value. A consumed row whose
    machine is gone would be a record with no reader, kept for an audit trail that does not
    exist. Deleting it also matches what a deleted workspace already does with the same rows.

    **Agents that lived here become unplaced, not deleted.** Their binding goes, and the
    absence of a binding already has a defined meaning — offline, reason `not_placed`
    (FR-006c). That is exactly true of them now, and it is recoverable: put the agent
    somewhere else and it works again. Deleting the agents would throw away their run
    history and their seats for a fact about a machine.

    **A run held by this machine loses its claim, and that is the honest outcome.** The
    machine is gone; the run cannot go on. What the daemon sees if it is still alive and
    still talking is a refusal rather than a crash — run authentication resolves a token
    through the claim row, and with the row gone it resolves to nothing.
    """
    workplaces = select(WorkplaceModel.id).where(WorkplaceModel.machine_id == machine_id)
    await session.execute(
        delete(AgentWorkplaceBindingModel).where(
            AgentWorkplaceBindingModel.workplace_id.in_(workplaces)
        )
    )
    await session.execute(
        delete(RunClaimModel).where(RunClaimModel.workplace_id.in_(workplaces))
    )
    await session.execute(
        delete(DaemonLinkCodeModel).where(DaemonLinkCodeModel.machine_id == machine_id)
    )
    await session.execute(
        delete(WorkplaceModel).where(WorkplaceModel.machine_id == machine_id)
    )
    await session.execute(delete(MachineModel).where(MachineModel.id == machine_id))
