"""Workspace scoping for the patron-facing routers (Constitution I, FR-081).

Every row in this system hangs off a workspace: a task belongs to a project, a project to
exactly one workspace, and a workspace to one patron. A run usually hangs off a task, and
when it does not — an interview, a turn of the Leader chat — it hangs off the agent that
took it, which hangs off a workspace all the same. A route that resolves a row by its id
alone has skipped that chain, and the row is then readable — and usually writable — by
anyone who can name the id.

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
    """The run, only if the caller owns the workspace it belongs to.

    Two chains, because there are two kinds of run and only one of them hangs off a task.

    A run **about a task** is reached the way everything else here is: task → project →
    workspace → owner.

    A run about **no task and no project** is not a broken row — it is a whole kind of run
    this system opens on purpose (FR-040c): the team-building interview, and a turn of the
    chat with a project Leader. Both happen before there is any task to hang off. Those runs
    are reached through the agent that took them: an agent belongs to exactly one workspace,
    and that workspace has one owner, so the chain is the same length and ends in the same
    place.

    Until this had a second branch it refused every one of them outright, which is a strange
    thing for an authorisation guard to do: the events were written, the agent's own screen
    listed the runs, and every door onto their log answered *no such run*. Found 2026-09-07,
    from the owner: *"có khá nhiều activity onboarding_answered nhưng lại không có trace nào
    được record, ấn open full log không thấy gì"* — measured afterwards, every one of the 21
    task-less runs in the database had its events, six apiece, and none could be opened.

    Both endings are **not found** rather than *forbidden*, like everything else in this file:
    *forbidden* would confirm the row exists, and that is a fact belonging to the other tenant
    (Constitution I).
    """
    run = await container.runs.get(run_id)
    if run is None:
        raise NotFound("run_not_found")

    if run.task_id is not None:
        try:
            await own_task(container, user, run.task_id)
        except LookupError as exc:
            raise NotFound("run_not_found") from exc
        return run

    # A run with no task is scoped through the agent that ran it. No agent means there is no
    # chain to walk at all, so there is nothing to let anybody through on.
    if run.marius_id is None:
        raise NotFound("run_not_found")
    marius = await container.mariuses.get(run.marius_id)
    if marius is None or marius.workspace_id is None:
        raise NotFound("run_not_found")
    ws = await container.workspaces.get_workspace(marius.workspace_id)
    if ws is None or ws.owner_user_id != str(getattr(user, "id", "")):
        raise NotFound("run_not_found")
    return run
