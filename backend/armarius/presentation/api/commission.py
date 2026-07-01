"""Commission endpoints — the Patron ↔ Leader task-shaping chat (API_CONTRACT §2.13).

Every route is scoped to the caller's workspace: shaping a task in a project the caller
does not own is a 404. Because the Leader is an agent, these calls return immediately with
the session's ``leader_state`` (thinking / waiting / leader_offline); the actual Leader turn
runs asynchronously through the wake engine and streams on the per-task SSE channel.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from armarius.presentation.api.auth import CurrentUser
from armarius.presentation.deps import ContainerDep
from armarius.presentation.schemas import (
    CommissionEditIn,
    CommissionOut,
    CommissionRefineIn,
    CommissionStartIn,
)

router = APIRouter(prefix="/v1", tags=["commission"])


async def _require_owned_project(container, user, project_id: UUID):
    project = await container.projects.get_project(project_id)
    if project is None:
        raise LookupError("project not found")
    ws = await container.workspaces.get_workspace(project.workspace_id)
    if ws is None or ws.owner_user_id != str(user.id):
        raise LookupError("project not found")  # cross-workspace → 404
    return project


async def _owned_commission(container, user, session_id: UUID):
    session = await container.commission.get(session_id)
    if session is None:
        raise LookupError("commission not found")
    if session.project_id is not None:
        await _require_owned_project(container, user, session.project_id)
    return session


@router.post("/commissions", response_model=CommissionOut, status_code=201)
async def start_commission(
    body: CommissionStartIn, container: ContainerDep, user: CurrentUser
) -> CommissionOut:
    await _require_owned_project(container, user, body.project_id)
    session = await container.commission.commission(
        project_id=body.project_id,
        message=body.message,
        title=body.title,
        created_by_user_id=str(user.id),
    )
    return CommissionOut.model_validate(session)


@router.post("/commissions/edit", response_model=CommissionOut, status_code=201)
async def edit_commission(
    body: CommissionEditIn, container: ContainerDep, user: CurrentUser
) -> CommissionOut:
    task = await container.tasks.get(body.task_id)
    if task is None or task.project_id is None:
        raise LookupError("task not found")
    await _require_owned_project(container, user, task.project_id)
    session = await container.commission.edit(task_id=body.task_id, message=body.message)
    return CommissionOut.model_validate(session)


@router.get("/commissions/{session_id}", response_model=CommissionOut)
async def get_commission(
    session_id: UUID, container: ContainerDep, user: CurrentUser
) -> CommissionOut:
    session = await _owned_commission(container, user, session_id)
    return CommissionOut.model_validate(session)


@router.post("/commissions/{session_id}/refine", response_model=CommissionOut)
async def refine_commission(
    session_id: UUID,
    body: CommissionRefineIn,
    container: ContainerDep,
    user: CurrentUser,
) -> CommissionOut:
    await _owned_commission(container, user, session_id)
    session = await container.commission.refine(session_id, body.message)
    return CommissionOut.model_validate(session)


@router.post("/commissions/{session_id}/confirm", response_model=CommissionOut)
async def confirm_commission(
    session_id: UUID, container: ContainerDep, user: CurrentUser
) -> CommissionOut:
    await _owned_commission(container, user, session_id)
    session = await container.commission.confirm(session_id)
    return CommissionOut.model_validate(session)


@router.post("/commissions/{session_id}/abandon", response_model=CommissionOut)
async def abandon_commission(
    session_id: UUID, container: ContainerDep, user: CurrentUser
) -> CommissionOut:
    await _owned_commission(container, user, session_id)
    session = await container.commission.abandon(session_id)
    return CommissionOut.model_validate(session)
