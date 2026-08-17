"""Workspace scoping for the patron-facing routers (Constitution I, FR-081).

Every row in this system hangs off a workspace: a run belongs to a task, a task to a
project, a project to exactly one workspace, and a workspace to one patron. A route that
resolves a row by its id alone has skipped that chain, and the row is then readable — and
usually writable — by anyone who can name the id.

Both helpers answer **not found** rather than *forbidden* when the chain does not lead
back to the caller. *Forbidden* would confirm the row exists, which is itself a fact
belonging to the other tenant.

The agent side has its own half of this: ``/agent/*`` scopes through the token's
workspace (see ``TaskService.get_in_workspace``).
"""

from __future__ import annotations

from uuid import UUID

from armarius.domain.entities.project import Project
from armarius.domain.entities.run import Run
from armarius.domain.entities.task import Task
from armarius.presentation.container import Container
from armarius.shared.errors import NotFound


async def own_project(container: Container, user: object, project_id: UUID) -> Project:
    """The project, only if the caller owns the workspace holding it."""
    project = await container.projects.get_project(project_id)
    if project is None:
        raise NotFound("project_not_found")
    ws = await container.workspaces.get_workspace(project.workspace_id)
    if ws is None or ws.owner_user_id != str(getattr(user, "id", "")):
        raise NotFound("project_not_found")  # cross-workspace → 404
    return project


async def own_task(container: Container, user: object, task_id: UUID) -> Task:
    """The task, only if the caller owns the workspace holding it."""
    task = await container.tasks.get(task_id)
    if task is None or task.project_id is None:
        raise NotFound("task_not_found")
    try:
        await own_project(container, user, task.project_id)
    except LookupError as exc:
        raise NotFound("task_not_found") from exc
    return task


async def own_run(container: Container, user: object, run_id: UUID) -> Run:
    """The run, only if the caller owns the workspace its task lives in."""
    run = await container.runs.get(run_id)
    if run is None or run.task_id is None:
        raise NotFound("run_not_found")
    try:
        await own_task(container, user, run.task_id)
    except LookupError as exc:
        raise NotFound("run_not_found") from exc
    return run
