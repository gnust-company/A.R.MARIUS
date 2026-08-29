"""Opening a real run for an agent, and getting the token that run's agent is started with.

Every `/agent/*` route authenticates a **run token** (FR-014g), so a test that wants to act
as an agent needs a run first — the token does not exist outside one and cannot be minted
any other way.

Nothing here hand-writes a claim or a token. The run is shelved and taken through the same
`offer` → `claim` the daemon's own door goes through, so a test built on this is built on
the shape the product actually produces: the token comes back from `claim`, hashed into
`run_claims` by the same code that will hash it in production, and it stops working the
moment the run is closed because that is the mechanism, not a fixture detail.

**One piece of the door is deliberately left out: the dressing.** `claim` normally composes
the message the agent will read, and `compose_packet` needs a task — so a project-level or
workspace-level run cannot be dressed today and is handed straight back, token revoked, by
the very door that just minted it. That is a real gap and it belongs to T048a, which is
where FR-040c turns the interview into a workspace-level run; until then a fixture that
asked for the dressing could only ever produce task-level runs, and the scope rule this
file exists to test would have nothing to be tested against. So the service used here is
built without a composer, which is the same door with that one step absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select

from armarius.domain.entities.run import RunStatus
from armarius.infrastructure.daemon.claim import DaemonClaimService
from armarius.infrastructure.daemon.enrollment import MachineIdentity
from armarius.infrastructure.daemon.models import (
    AgentWorkplaceBindingModel,
    RunClaimModel,
    WorkplaceModel,
)
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import RunModel
from armarius.main import app
from armarius.shared.clock import utcnow


@dataclass(frozen=True)
class OpenRun:
    """One live run and the credential its agent speaks with."""

    run_id: UUID
    marius_id: UUID
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


async def open_run(
    *,
    marius_id: str | UUID,
    task_id: str | UUID | None = None,
    project_id: str | UUID | None = None,
) -> OpenRun:
    """A run for this agent, taken by the machine the agent works on.

    `task_id` and `project_id` are what make the run task-level, project-level or
    workspace-level (FR-013d) — the same three shapes the wake engine produces, and what
    the scope guard reads.
    """
    marius_uuid = UUID(str(marius_id))
    claims = DaemonClaimService()

    async with get_sessionmaker()() as session:
        binding = await session.get(AgentWorkplaceBindingModel, marius_uuid)
        assert binding is not None, "an agent must be placed before it can hold a run"
        workplace = await session.get(WorkplaceModel, binding.workplace_id)
        assert workplace is not None
        run_id = uuid4()
        session.add(
            RunModel(
                id=run_id,
                marius_id=marius_uuid,
                task_id=UUID(str(task_id)) if task_id else None,
                project_id=UUID(str(project_id)) if project_id else None,
                adapter_type="daemon",
                status=RunStatus.QUEUED.value,
                created_at=utcnow(),
            )
        )
        await session.commit()

    await claims.offer(
        run_id=run_id,
        workspace_id=binding.workspace_id,
        workplace_id=binding.workplace_id,
    )
    granted = await claims.claim(
        MachineIdentity(
            machine_id=workplace.machine_id,
            workspace_id=binding.workspace_id,
            owner_user_id=uuid4(),
            token_expires_at=None,
        ),
        workplace_ids=[binding.workplace_id],
        free_slots=1,
    )
    mine = [g for g in granted if g.run_id == run_id]
    assert mine, "the shelf handed back something other than the run just put on it"
    return OpenRun(run_id=run_id, marius_id=marius_uuid, token=mine[0].run_token)


async def close_run(open_run_: OpenRun) -> None:
    """Finish the run through the same door the daemon uses, so its token is revoked.

    Through `finish` and not an `UPDATE`: revocation is something that door *does*, and a
    test that blanked the column itself would prove the door's behaviour by performing it.
    """
    async with get_sessionmaker()() as session:
        claim = await session.get(RunClaimModel, open_run_.run_id)
        assert claim is not None and claim.machine_id is not None
        machine_id, workspace_id = claim.machine_id, claim.workspace_id
    await app.state.container.daemon_claims.finish(
        MachineIdentity(
            machine_id=machine_id,
            workspace_id=workspace_id,
            owner_user_id=uuid4(),
            token_expires_at=None,
        ),
        open_run_.run_id,
        status=RunStatus.COMPLETED,
    )


async def workplace_of(marius_id: str | UUID) -> UUID:
    async with get_sessionmaker()() as session:
        return (
            await session.execute(
                select(AgentWorkplaceBindingModel.workplace_id).where(
                    AgentWorkplaceBindingModel.marius_id == UUID(str(marius_id))
                )
            )
        ).scalar_one()
