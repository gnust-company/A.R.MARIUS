"""Task, thread and artifact endpoints (human/operator surface)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from armarius.domain.entities.comment import AuthorKind
from armarius.domain.entities.run import WakeSource
from armarius.domain.entities.task import TaskStatus
from armarius.presentation.deps import ContainerDep
from armarius.presentation.schemas import (
    AddDependencyIn,
    ArtifactOut,
    AssignIn,
    BlockerOut,
    CommentOut,
    CreateTaskIn,
    NextActionIn,
    PostCommentIn,
    PublishArtifactIn,
    RunStartedOut,
    TaskDependencyEdgeOut,
    TaskOut,
    TransitionIn,
    WakeIn,
    decode_artifact_content,
)

router = APIRouter(prefix="/v1", tags=["tasks"])


def _parse_status(value: str) -> TaskStatus:
    try:
        return TaskStatus(value)
    except ValueError as exc:
        raise ValueError(f"unknown status '{value}'") from exc


@router.post("/projects/{project_id}/tasks", response_model=TaskOut, status_code=201)
async def create_task(
    project_id: UUID, body: CreateTaskIn, container: ContainerDep
) -> TaskOut:
    task = await container.tasks.create(
        project_id=project_id,
        title=body.title,
        description=body.description,
        status=_parse_status(body.status) if body.status else TaskStatus.BACKLOG,
        priority=body.priority,
        due_date=body.due_date,
        definition_of_done=body.definition_of_done,
        assigned_marius_id=body.assigned_marius_id,
        created_by_user_id=body.created_by_user_id,
    )
    return TaskOut.model_validate(task)


@router.get("/projects/{project_id}/tasks", response_model=list[TaskOut])
async def list_tasks(
    project_id: UUID, container: ContainerDep, status: str | None = None
) -> list[TaskOut]:
    statuses = [s.strip() for s in status.split(",")] if status else None
    items = await container.tasks.list_by_project(project_id, statuses=statuses)
    return [TaskOut.model_validate(t) for t in items]


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(task_id: UUID, container: ContainerDep) -> TaskOut:
    task = await container.tasks.get(task_id)
    if task is None:
        raise LookupError("task not found")
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/assign", response_model=TaskOut)
async def assign_task(task_id: UUID, body: AssignIn, container: ContainerDep) -> TaskOut:
    task = await container.tasks.assign(task_id, body.marius_id)
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/status", response_model=TaskOut)
async def transition_task(
    task_id: UUID, body: TransitionIn, container: ContainerDep
) -> TaskOut:
    task = await container.tasks.transition(
        task_id, _parse_status(body.status), reason=body.reason
    )
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/next-action", response_model=TaskOut)
async def set_next_action(
    task_id: UUID, body: NextActionIn, container: ContainerDep
) -> TaskOut:
    task = await container.tasks.set_next_action(task_id, body.next_action)
    return TaskOut.model_validate(task)


@router.get("/tasks/{task_id}/dependencies", response_model=list[BlockerOut])
async def list_dependencies(
    task_id: UUID, container: ContainerDep
) -> list[BlockerOut]:
    """Tasks this task is blocked_by (feeds the dependency-gate, §1.3)."""
    blockers = await container.tasks.list_blockers(task_id)
    return [BlockerOut.model_validate(t) for t in blockers]


@router.post(
    "/tasks/{task_id}/dependencies",
    response_model=list[BlockerOut],
    status_code=201,
)
async def add_dependency(
    task_id: UUID, body: AddDependencyIn, container: ContainerDep
) -> list[BlockerOut]:
    """Add a `blocked_by` edge, then return the refreshed blocker list."""
    await container.tasks.add_dependency(task_id, body.blocks_task_id)
    blockers = await container.tasks.list_blockers(task_id)
    return [BlockerOut.model_validate(t) for t in blockers]


@router.delete("/tasks/{task_id}/dependencies/{blocks_task_id}", status_code=204)
async def remove_dependency(
    task_id: UUID, blocks_task_id: UUID, container: ContainerDep
) -> None:
    await container.tasks.remove_dependency(task_id, blocks_task_id)


@router.get(
    "/projects/{project_id}/task-dependencies",
    response_model=list[TaskDependencyEdgeOut],
)
async def list_project_dependencies(
    project_id: UUID, container: ContainerDep
) -> list[TaskDependencyEdgeOut]:
    """All `blocked_by` edges in the project — the board flags cards with an
    unfinished blocker from these plus the tasks it already loaded."""
    edges = await container.tasks.list_project_dependencies(project_id)
    return [TaskDependencyEdgeOut.model_validate(e) for e in edges]


@router.get("/tasks/{task_id}/comments", response_model=list[CommentOut])
async def list_comments(task_id: UUID, container: ContainerDep) -> list[CommentOut]:
    items = await container.threads.list_comments(task_id)
    return [CommentOut.model_validate(c) for c in items]


@router.post("/tasks/{task_id}/comments", response_model=CommentOut, status_code=201)
async def post_comment(
    task_id: UUID, body: PostCommentIn, container: ContainerDep
) -> CommentOut:
    comment = await container.threads.post_comment(
        task_id=task_id,
        body=body.body,
        author_kind=AuthorKind(body.author_kind),
        author_user_id=body.author_user_id,
        extra_mentions=body.extra_mentions,
    )
    return CommentOut.model_validate(comment)


@router.get("/tasks/{task_id}/artifacts", response_model=list[ArtifactOut])
async def list_artifacts(task_id: UUID, container: ContainerDep) -> list[ArtifactOut]:
    items = await container.artifacts.list_by_task(task_id)
    return [ArtifactOut.model_validate(a) for a in items]


@router.post("/tasks/{task_id}/artifacts", response_model=ArtifactOut, status_code=201)
async def publish_artifact(
    task_id: UUID, body: PublishArtifactIn, container: ContainerDep
) -> ArtifactOut:
    artifact = await container.artifacts.publish(
        task_id=task_id,
        name=body.name,
        kind=body.kind,
        content=decode_artifact_content(
            content_b64=body.content_b64,
            content=body.content,
            content_sha256=body.content_sha256,
        ),
        uri=body.uri,
    )
    return ArtifactOut.model_validate(artifact)


@router.post("/tasks/{task_id}/wake", response_model=RunStartedOut, status_code=202)
async def wake_task(task_id: UUID, body: WakeIn, container: ContainerDep) -> RunStartedOut:
    run_id = await container.wake_engine.enqueue(
        marius_id=body.marius_id,
        task_id=task_id,
        source=WakeSource.ON_DEMAND,
        reason=body.reason or "manual wake from dashboard",
    )
    return RunStartedOut(run_id=run_id)
