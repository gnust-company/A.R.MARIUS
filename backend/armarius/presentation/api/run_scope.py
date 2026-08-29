"""A run reaches only what it is about — one guard, in front of every agent route (FR-059).

The run token says which run is calling, and a run is *about* something: one task, one
project, or — for the team-building interview — a workspace and nothing narrower
(FR-013d). This guard is the half of that rule the agent cannot get around.

The other half is the toolset the run is handed (T137, T138): a run that never receives a
project command will not send one. Two layers because they cover two different things. The
toolset is what the agent **sees**, so it does not go wrong; this is what the agent
**cannot get past**, so it does not go wrong even when it tries — or when a machine whose
hold quietly expired starts an agent anyway, which is the case FR-059 was written for.

It hangs on the router rather than beside each route, for the same reason `refuse_when_frozen`
does: a route added tomorrow inherits it without anyone remembering to.

It also hangs **before** the frozen-project guard, and the order is load-bearing: that guard
answers *this project is closed*, which is an answer about something the caller was never
entitled to know exists. Scope has to be settled first, so a run reaching outside itself gets
*not found* rather than a fact about somebody else's project.

What it does **not** do is decide who may call what. A worker run and a Leader run both
belong to their project; whether the caller holds the Leader's seat is a different question
and is already asked where it belongs (`_leader_seat`). Folding role into a scope guard
would put one rule in two places and let them disagree.

The one shape it lets through is a **workspace-level** run — the team-building interview
(FR-040c), which is about no task and no project. There is nothing to compare it against, and
it is handed no task or project commands to begin with; the workspace check every route
already does is what bounds it.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Header, Request

from armarius.presentation.deps import ContainerDep, resolve_run
from armarius.shared.errors import NotFound


def _as_uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


async def refuse_outside_run_scope(
    request: Request,
    container: ContainerDep,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Refuse anything aimed outside what the calling run is about.

    Silent on a token that resolves to no run: saying *not found* here would answer before
    the route's own door has, and that door already gives exactly this answer with the code
    that names the real cause. A guard that refuses first turns "your run is over" into
    "no such task", which is the one thing the daemon needs to tell apart (FR-014f).
    """
    caller = await resolve_run(request, container, authorization)
    if caller is None:
        return

    params = request.path_params

    task_id = _as_uuid(params.get("task_id"))
    if task_id is not None:
        if caller.task_id is not None:
            if caller.task_id != task_id:
                # A run about one task reaching for another. Not forbidden — not there
                # (Constitution I): the agent learns nothing about a task it was never given.
                raise NotFound("task_not_found")
        elif caller.project_id is not None:
            # A Leader's run carries no task, and it is *meant* to work across the tasks of
            # its project — so the comparison has to be made one hop further out, against
            # the task's project. Checking only the pair of task ids would let this run
            # comment on, publish to and move tasks belonging to a project next door: the
            # seat check catches that on the four routes that ask for it and on none of the
            # others, which is a rule that holds exactly where somebody was already looking.
            task = await container.tasks.get(task_id)
            if task is not None and task.project_id != caller.project_id:
                raise NotFound("task_not_found")

    project_id = _as_uuid(params.get("project_id"))
    if (
        project_id is not None
        and caller.project_id is not None
        and caller.project_id != project_id
    ):
        raise NotFound("project_not_found")
