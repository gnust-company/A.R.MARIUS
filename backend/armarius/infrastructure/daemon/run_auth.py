"""Who is calling from inside a run — the only credential `/agent/*` takes (FR-014g).

Until this module existed, an agent authenticated with a token minted once, when it was
created, and good for its whole life. That token answered *which agent* and nothing else,
so every write it carried arrived with no way of saying which run produced it — the one
thing FR-059 asks for. It also outlived every run it was ever used in, which is precisely
what FR-014b says a run's credential must not do.

The run token answers both at once: it is minted when a machine takes the run (claim.py),
it is written back to nothing the moment the run closes, and while it is alive it names
exactly one run — and through that run, one agent, one workspace, and at most one task.

**A revoked token and a token that never existed answer identically.** Revocation is a
write of `NULL` over `run_claims.run_token_hash`, and a lookup by value never matches a
NULL, so the closed run drops out of reach through the revocation itself rather than
through a second check somebody has to remember to write. Both cases come back as nothing,
which the door above turns into *no such run* — never *forbidden*, so nobody holding a dead
string can confirm it once opened something (Constitution I).

Infrastructure, and staying there (Constitution III): `run_claims` is a fact about which
machine holds what, and no rule above the adapter contract may learn that such a table
exists. That is why this talks to its own session instead of joining the unit of work.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from armarius.infrastructure.daemon.models import RunClaimModel
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import RunModel


def hash_run_token(token: str) -> str:
    """The only form of a run token this system keeps.

    Minting (claim.py) and checking (here) share this one function on purpose. Two copies
    of a hash are two hashes the day one of them is changed, and the failure that follows
    looks like every token being wrong at once.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RunCaller:
    """One live run, seen from the door: who it speaks for and what it is about.

    `task_id` and `project_id` are both optional, and the combination is what says which
    kind of run this is (FR-013d):

      * a **task-level** run carries both — it is about that one task,
      * a **project-level** run carries only the project — a Leader run, which is why it
        may touch every task on that project rather than one,
      * a **workspace-level** run carries neither — the team-building interview, which
        happens before any project exists (FR-040c).
    """

    run_id: UUID
    marius_id: UUID
    workspace_id: UUID
    task_id: UUID | None
    project_id: UUID | None

    @property
    def is_task_scoped(self) -> bool:
        return self.task_id is not None


class RunTokenAuthenticator:
    """Resolves the bearer token an agent was started with into the run it belongs to."""

    def __init__(
        self,
        sessions: Callable[[], async_sessionmaker[AsyncSession]] | None = None,
    ) -> None:
        self._sessions = sessions or get_sessionmaker

    async def authenticate(self, token: str) -> RunCaller | None:
        """The run this token opens, or `None` for anything that opens nothing.

        A run whose agent is missing resolves to nothing as well. It is not a state the
        product can reach — a run is created for an agent — but resolving it to a caller
        with no identity would hand every route below a `None` to trip over, one route at
        a time, instead of one refusal here.
        """
        if not token:
            return None
        async with self._sessions()() as session:
            row = (
                await session.execute(
                    select(RunClaimModel, RunModel)
                    .join(RunModel, RunModel.id == RunClaimModel.run_id)
                    .where(RunClaimModel.run_token_hash == hash_run_token(token))
                )
            ).first()
        if row is None:
            return None
        claim, run = row
        if run.marius_id is None:
            return None
        return RunCaller(
            run_id=claim.run_id,
            marius_id=run.marius_id,
            workspace_id=claim.workspace_id,
            task_id=run.task_id,
            project_id=run.project_id,
        )
