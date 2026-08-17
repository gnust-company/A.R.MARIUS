"""A closed project is frozen — one guard, in front of every write (spec 001 FR-005).

FR-005 says a closed project keeps its history *read-only*. That was enforced in a handful
of hand-picked services, which is the shape of rule that holds until somebody adds a route.
Comments, artifacts, status moves, roster grants and threshold edits all still wrote to a
project the patron had declared finished.

So the rule is applied once, at the edge every request passes through, rather than beside
each caller: any non-read request that names a project — directly, or through a task —
is refused while that project is closed. A route added tomorrow inherits it without anyone
remembering to. `tests/test_closed_project_is_frozen.py` walks the whole route table and
fails if a write route ever escapes this guard.

Two things deliberately stay possible on a closed project:

  * **reading** — the whole point of keeping it;
  * **deleting the project itself** — freezing the contents must not trap the patron with
    a project they can never get rid of. Deleting is disposing of the frozen thing, not
    operating inside it.

The service-layer guards (the wake engine, the task edit) stay where they are. They cover
the callers that never touch HTTP at all: background loops, and the recovery ladder.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Request

from armarius.domain.services.project_rules import ProjectClosed, is_closed
from armarius.presentation.deps import ContainerDep

# Reads never change anything, so they are never refused — a closed project must stay
# fully readable.
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_MESSAGE = "Dự án đã đóng — mọi thao tác trên nó đã dừng, chỉ còn xem lại được."

# The single route that disposes of the project itself, rather than operating inside it.
_DELETE_THE_PROJECT = ("DELETE", "/v1/projects/{project_id}")


def _as_uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


async def refuse_when_frozen(request: Request, container: ContainerDep) -> None:
    """Refuse any write aimed at a closed project.

    Runs as a router dependency rather than middleware because the path parameters are
    only known once the route has matched — and matching on raw path strings instead is
    how a guard quietly stops covering a route whose URL shape changed.
    """
    if request.method in _READ_METHODS:
        return

    route = request.scope.get("route")
    if (request.method, getattr(route, "path", "")) == _DELETE_THE_PROJECT:
        return

    params = request.path_params
    project_id = _as_uuid(params.get("project_id"))
    if project_id is None:
        task_id = _as_uuid(params.get("task_id"))
        if task_id is None:
            return  # not aimed at a project — workspaces, skills, auth, onboarding
        task = await container.tasks.get(task_id)
        if task is None or task.project_id is None:
            return  # a missing task is the route's own 404 to give, not ours
        project_id = task.project_id

    project = await container.projects.get_project(project_id)
    if project is not None and is_closed(project.status):
        raise ProjectClosed(_MESSAGE)
