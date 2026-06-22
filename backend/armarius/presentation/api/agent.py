"""Agent-facing API — the Armarius skills an onboarded Marius calls back into (§6.2).

Authenticated by the per-Marius bearer token. These endpoints are what make the
collaboration loop real: claim, comment/@mention, update status, record next_action,
and publish artifacts into the shared store.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from armarius.domain.entities.comment import AuthorKind
from armarius.domain.entities.task import TaskStatus
from armarius.presentation.deps import ContainerDep, CurrentMarius
from armarius.presentation.schemas import (
    AgentArtifactIn,
    AgentCommentIn,
    ArtifactOut,
    CommentOut,
    MariusOut,
    NextActionIn,
    TaskOut,
    TransitionIn,
)

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/me")
async def whoami(marius: CurrentMarius, container: ContainerDep) -> dict:
    directory = await container.mariuses.list_directory(marius.workspace_id)
    return {
        "marius": MariusOut.model_validate(marius).model_dump(mode="json"),
        "directory": [
            MariusOut.model_validate(m).model_dump(mode="json")
            for m in directory
            if m.id != marius.id
        ],
    }


@router.get("/tasks/{task_id}")
async def get_task_view(
    task_id: UUID, marius: CurrentMarius, container: ContainerDep
) -> dict:
    task = await container.tasks.get(task_id)
    if task is None:
        raise LookupError("task not found")
    comments = await container.threads.list_comments(task_id)
    artifacts = await container.artifacts.list_by_task(task_id)
    directory = await container.mariuses.list_directory(marius.workspace_id)
    return {
        "task": TaskOut.model_validate(task).model_dump(mode="json"),
        "thread": [
            CommentOut.model_validate(c).model_dump(mode="json") for c in comments
        ],
        "artifacts": [
            ArtifactOut.model_validate(a).model_dump(mode="json") for a in artifacts
        ],
        "directory": [
            MariusOut.model_validate(m).model_dump(mode="json")
            for m in directory
            if m.id != marius.id
        ],
    }


@router.post("/tasks/{task_id}/claim", response_model=TaskOut)
async def claim_task(
    task_id: UUID, marius: CurrentMarius, container: ContainerDep
) -> TaskOut:
    task = await container.tasks.claim(task_id, marius.id)
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/comment", response_model=CommentOut, status_code=201)
async def post_comment(
    task_id: UUID, body: AgentCommentIn, marius: CurrentMarius, container: ContainerDep
) -> CommentOut:
    comment = await container.threads.post_comment(
        task_id=task_id,
        body=body.body,
        author_kind=AuthorKind.AGENT,
        author_marius_id=marius.id,
    )
    return CommentOut.model_validate(comment)


@router.post("/tasks/{task_id}/status", response_model=TaskOut)
async def update_status(
    task_id: UUID, body: TransitionIn, marius: CurrentMarius, container: ContainerDep
) -> TaskOut:
    try:
        target = TaskStatus(body.status)
    except ValueError as exc:
        raise ValueError(f"unknown status '{body.status}'") from exc
    task = await container.tasks.transition(task_id, target, reason=body.reason)
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/next-action", response_model=TaskOut)
async def set_next_action(
    task_id: UUID, body: NextActionIn, marius: CurrentMarius, container: ContainerDep
) -> TaskOut:
    task = await container.tasks.set_next_action(task_id, body.next_action)
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/artifact", response_model=ArtifactOut, status_code=201)
async def publish_artifact(
    task_id: UUID, body: AgentArtifactIn, marius: CurrentMarius, container: ContainerDep
) -> ArtifactOut:
    artifact = await container.artifacts.publish(
        task_id=task_id,
        name=body.name,
        kind=body.kind,
        content=body.content.encode("utf-8") if body.content is not None else None,
        uri=body.uri,
        marius_id=marius.id,
    )
    return ArtifactOut.model_validate(artifact)
