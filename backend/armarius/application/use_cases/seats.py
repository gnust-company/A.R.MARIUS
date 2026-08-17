"""Who holds a project's leader seat — one answer, in one place.

Four call sites used to work this out for themselves, and the four did not agree.

Three read the roster's leader flag; the fourth matched the literal role key ``"leader"``,
which the flag does not have to imply — `add_role` deliberately skips the roster rule, so a
leader role under a different key is reachable through the API, and then those two readings
name different agents. A fifth reader (the wake guard) stopped at the *first* grant row
matching the agent, without checking it was still in force: a seat is re-granted by writing
a **new** row, so an agent put back on the leader seat has a revoked row sitting ahead of
its live one, and that reader concluded the project's own Leader held no role at all.

Neither is a mistake a reader can be told to stop making. They are copies of one lookup,
and every copy is another chance to get it wrong. So the lookup lives here, and the callers
ask for the answer instead of deriving it.

The roster rule (`project_rules.validate_plan`) gives every project exactly one leader role
with exactly one seat, so "who leads this project" is a single value — not a list to be
searched by whoever needs it.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from armarius.application.ports.unit_of_work import UnitOfWork
from armarius.domain.entities.role import Role


def leader_role_keys(roles: Iterable[Role]) -> set[str]:
    """The roster keys that mark the leader seat, read off the flag rather than the name."""
    return {role.key for role in roles if role.is_leader}


async def leader_role(uow: UnitOfWork, project_id: UUID) -> Role | None:
    """The project's leader role — its title and duties, for prompts that show them."""
    return next((r for r in await uow.roles.list_by_project(project_id) if r.is_leader), None)


async def leader_marius_id(uow: UnitOfWork, project_id: UUID) -> UUID | None:
    """The agent currently seated as this project's Leader, or None if the seat is empty.

    Every grant is looked at, never only the first: revoked rows are kept and sorted ahead
    of the live one, so stopping early reads history and calls it the present.
    """
    keys = leader_role_keys(await uow.roles.list_by_project(project_id))
    if not keys:
        return None
    for grant in await uow.seat_grants.list_by_project(project_id):
        if grant.role_key in keys and grant.is_active and grant.marius_id is not None:
            return grant.marius_id
    return None


async def holds_the_leader_seat(uow: UnitOfWork, project_id: UUID, marius_id: UUID) -> bool:
    """Whether this agent is the project's Leader.

    Answered *through* `leader_marius_id` on purpose: asking "is it them" and asking "who is
    it" can then never disagree, which is the whole point of there being one place.
    """
    return await leader_marius_id(uow, project_id) == marius_id
