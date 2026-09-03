"""DaemonAdapter — handing work to a machine, which means putting it down and walking away.

Every other adapter in this system is a *call*: hand it a turn, wait, get a result. This one
cannot be, and the difference is not a detail of implementation — it is the shape of the
whole path. The machine that will do the work is not reachable from here. It is behind
somebody's home network, asleep, or mid-upgrade; it comes to us, we never go to it. So the
only honest thing dispatch can do is leave the work where that machine will look, and
return.

That is also why there is exactly one way for a run to begin (FR-053). A second path — a
call that reaches out and starts something — would be a second answer to *who has this run*,
and the first thing two answers do is disagree.

`execute` therefore has no meaning on this path and says so out loud rather than quietly
doing something almost right. Callers that still wait for a runtime to answer are being
moved over one at a time; a loud stop is what makes the ones still to move visible.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from armarius.application.ports.adapter import (
    AdapterCapabilities,
    Diagnostics,
    ExecContext,
    ExecResult,
    MariusAdapter,
)
from armarius.domain.entities.run import RunStatus
from armarius.infrastructure.daemon.claim import DaemonClaimService
from armarius.infrastructure.daemon.models import AgentWorkplaceBindingModel
from armarius.infrastructure.database.engine import get_sessionmaker


class DaemonAdapter(MariusAdapter):
    type = "daemon"
    capabilities = AdapterCapabilities(
        resumable=True,
        streaming=True,
        transport="process",
        # The whole of what makes this path different, said in one place so nobody has to
        # ask for it by name. A turn here does not happen inside the call that starts it;
        # it happens later, on a machine, and that machine reports it.
        turn_ends_in_the_call=False,
    )

    def __init__(
        self,
        claims: DaemonClaimService,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._claims = claims
        self._sessionmaker = sessionmaker

    def _sessions(self) -> async_sessionmaker[AsyncSession]:
        return self._sessionmaker or get_sessionmaker()

    async def dispatch(self, ctx: ExecContext) -> ExecResult:
        """Put the run where its machine will find it, and return at once (FR-009).

        Comes back **queued**, not running. Nothing is running: the work is on a shelf, and
        it stays there until a machine asks for it. Saying *running* here would be the one
        lie that matters, because the board's whole reading of "is anything moving this
        task" hangs off the difference between work that has been taken and work that has
        only been put out.
        """
        if ctx.run_id is None or ctx.marius_id is None:
            return ExecResult(status=RunStatus.FAILED, error="run_or_agent_missing_on_dispatch")
        placed = await self._placed_at(ctx.marius_id)
        if placed is None:
            # An agent with nowhere to work cannot be given work, and this is not an
            # accident to paper over: FR-007 makes the place compulsory at creation, so
            # reaching here means the binding was lost, not that it was never asked for.
            return ExecResult(status=RunStatus.FAILED, error="agent_has_no_workplace")
        workspace_id, workplace_id = placed
        await self._claims.offer(
            run_id=ctx.run_id,
            workspace_id=workspace_id,
            workplace_id=workplace_id,
        )
        return ExecResult(status=RunStatus.QUEUED)

    async def execute(self, ctx: ExecContext) -> ExecResult:
        raise NotImplementedError(
            "Work that runs on a machine is offered, not called: the machine asks for it "
            "and reports back. Use dispatch()."
        )

    async def test_environment(self, config: dict) -> Diagnostics:
        """There is no environment to reach out and test — that is the point of this path.

        Whether an agent here can actually run is answered from what its machine has already
        told us, by the liveness probe, and never by poking anything (FR-006a, FR-055b).
        """
        return Diagnostics(ok=True, detail="daemon_reports_in")

    async def _placed_at(self, marius_id: UUID) -> tuple[UUID, UUID] | None:
        async with self._sessions()() as session:
            row = (
                await session.execute(
                    select(
                        AgentWorkplaceBindingModel.workspace_id,
                        AgentWorkplaceBindingModel.workplace_id,
                    ).where(AgentWorkplaceBindingModel.marius_id == marius_id)
                )
            ).first()
        return (row.workspace_id, row.workplace_id) if row is not None else None
