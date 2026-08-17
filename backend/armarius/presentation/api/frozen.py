"""A closed project is frozen — one guard, in front of every write (spec 001 FR-005).

FR-005 says a closed project keeps its history *read-only*. That was enforced in a handful
of hand-picked services, which is the shape of rule that holds until somebody adds a route.
Comments, artifacts, status moves, roster grants and threshold edits all still wrote to a
project the patron had declared finished.

So the rule is applied once, at the edge every request passes through, rather than beside
each caller: any non-read request that names a project — directly, through a task, or
through an inbox item — is refused while that project is closed. A route added tomorrow
inherits it without anyone remembering to. `tests/test_closed_project_is_frozen.py` walks
the whole route table and fails if a write route ever escapes this guard.

The inbox door is why that audit had to stop reading path parameters to decide what needs
guarding. `POST /v1/inbox/{item_id}/answer` names neither a project nor a task in its URL,
yet answering an escalation reassigns, cancels, or redirects the task it is about — so it
wrote to closed projects while both the guard and its audit looked straight past it. Which
project an item belongs to has always been recorded on the item; only the guard's way of
finding it was too narrow.

Three things deliberately stay possible on a closed project:

  * **reading** — the whole point of keeping it;
  * **deleting the project itself** — freezing the contents must not trap the patron with
    a project they can never get rid of. Deleting is disposing of the frozen thing, not
    operating inside it;
  * **closing one of its letters** — that writes into the patron's own inbox, not into the
    project. Refusing it once left letters that could never be cleared and a waiting count
    that could never come down.

That last one is why the inbox router carries no door guard and enforces the freeze inside
instead (`RecoveryEscalator._refuse_if_closed`): which of its two doors writes into the
project is decided by the request *body*, and routing happens before the body is read. The
item hop below stays regardless — any future guarded route that names only a letter needs
it, and a guard that cannot find the project is the blind spot this rewrite was about.

The service-layer guards (the wake engine, the task edit) stay where they are. They cover
the callers that never touch HTTP at all: the background loops.
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


async def _project_named_by(request: Request, container: ContainerDep) -> UUID | None:
    """Which project this request is aimed at, or None if it is aimed at none.

    A route names its project directly, or by way of something the project owns. Each hop
    ends in None when the thing is missing: a request for something that is not there is
    the route's own 404 to give, not ours to turn into "closed".
    """
    params = request.path_params

    direct = _as_uuid(params.get("project_id"))
    if direct is not None:
        return direct

    task_id = _as_uuid(params.get("task_id"))
    if task_id is not None:
        task = await container.tasks.get(task_id)
        return task.project_id if task is not None else None

    item_id = _as_uuid(params.get("item_id"))
    if item_id is not None:
        item = await container.inbox.get(item_id)
        if item is None:
            return None
        if item.project_id is not None:
            return item.project_id
        if item.task_id is not None:
            task = await container.tasks.get(item.task_id)
            return task.project_id if task is not None else None
        return None

    return None  # workspaces, mariuses, skills, auth, onboarding — no project named


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

    project_id = await _project_named_by(request, container)
    if project_id is None:
        return

    project = await container.projects.get_project(project_id)
    if project is not None and is_closed(project.status):
        raise ProjectClosed(_MESSAGE)
