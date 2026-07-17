"""Chat-with-Leader endpoints — the project-level 1-1 Patron ↔ Leader chat (#82).

Every route is JWT-scoped to the caller's workspace (a project the caller does not own is a
404). Because the Leader is an agent, ``POST .../messages`` returns immediately with the
conversation's ``state`` (``thinking``); the Leader's reply streams on the
``GET .../leader-chat/stream`` SSE channel (wired in ``events.py``) and is appended to the
durable transcript when the turn completes. Task approval reuses the ``draft`` lifecycle:
the Leader proposes a draft, the patron approves (→ todo + wake) or rejects (→ cancelled).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from armarius.domain.entities.task import TaskStatus
from armarius.presentation.api.auth import CurrentUser
from armarius.presentation.deps import ContainerDep
from armarius.presentation.schemas import (
    LeaderChatOut,
    LeaderChatSendIn,
    TaskOut,
    YoloModeIn,
)

router = APIRouter(prefix="/v1", tags=["leader-chat"])


async def _require_owned_project(container, user, project_id: UUID):
    project = await container.projects.get_project(project_id)
    if project is None:
        raise LookupError("project not found")
    ws = await container.workspaces.get_workspace(project.workspace_id)
    if ws is None or ws.owner_user_id != str(user.id):
        raise LookupError("project not found")  # cross-workspace → 404
    return project


def _to_out(view) -> LeaderChatOut:  # noqa: ANN001 - LeaderChatView (application dataclass)
    return LeaderChatOut(
        project_id=view.conversation.project_id,
        leader_marius_id=view.conversation.leader_marius_id,
        leader_name=view.leader_name,
        leader_online=view.leader_online,
        yolo_mode=view.yolo_mode,
        state=str(view.conversation.state),
        transcript=list(view.conversation.transcript),
        updated_at=view.conversation.updated_at,
    )


@router.get("/projects/{project_id}/leader-chat", response_model=LeaderChatOut)
async def get_leader_chat(
    project_id: UUID, container: ContainerDep, user: CurrentUser
) -> LeaderChatOut:
    await _require_owned_project(container, user, project_id)
    view = await container.leader_chat.get_or_open(project_id)
    return _to_out(view)


@router.post("/projects/{project_id}/leader-chat/messages", response_model=LeaderChatOut)
async def send_leader_chat(
    project_id: UUID,
    body: LeaderChatSendIn,
    container: ContainerDep,
    user: CurrentUser,
) -> LeaderChatOut:
    await _require_owned_project(container, user, project_id)
    view = await container.leader_chat.send(project_id=project_id, message=body.message)
    return _to_out(view)


@router.put("/projects/{project_id}/yolo-mode", response_model=LeaderChatOut)
async def set_yolo_mode(
    project_id: UUID,
    body: YoloModeIn,
    container: ContainerDep,
    user: CurrentUser,
) -> LeaderChatOut:
    await _require_owned_project(container, user, project_id)
    await container.projects.set_yolo_mode(project_id, body.yolo_mode)
    view = await container.leader_chat.get_or_open(project_id)
    return _to_out(view)


@router.get("/projects/{project_id}/proposed-tasks", response_model=list[TaskOut])
async def list_proposed_tasks(
    project_id: UUID, container: ContainerDep, user: CurrentUser
) -> list[TaskOut]:
    """Leader-proposed tasks awaiting the patron's approval (draft status)."""
    await _require_owned_project(container, user, project_id)
    items = await container.tasks.list_by_project(
        project_id, statuses=[str(TaskStatus.DRAFT)]
    )
    return [TaskOut.model_validate(t) for t in items]


@router.post("/tasks/{task_id}/approve", response_model=TaskOut)
async def approve_task(
    task_id: UUID, container: ContainerDep, user: CurrentUser
) -> TaskOut:
    task = await container.tasks.get(task_id)
    if task is None or task.project_id is None:
        raise LookupError("task not found")
    await _require_owned_project(container, user, task.project_id)
    approved = await container.tasks.approve_proposed(task_id)
    return TaskOut.model_validate(approved)


@router.post("/tasks/{task_id}/reject", response_model=TaskOut)
async def reject_task(
    task_id: UUID, container: ContainerDep, user: CurrentUser
) -> TaskOut:
    task = await container.tasks.get(task_id)
    if task is None or task.project_id is None:
        raise LookupError("task not found")
    await _require_owned_project(container, user, task.project_id)
    rejected = await container.tasks.reject_proposed(task_id)
    return TaskOut.model_validate(rejected)
