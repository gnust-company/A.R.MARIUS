"""Task, thread and artifact endpoints (human/operator surface).

Every route here is scoped to the caller's own workspace. A task in someone else's
workspace reads as *not found*, never *forbidden*, so a caller cannot use the error to
learn that it exists (Constitution I, FR-081). ``/agent/*`` gets the same guarantee
through the agent token's own workspace; this is its half for patron tokens.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from armarius.domain.entities.comment import AuthorKind
from armarius.domain.entities.run import WakeSource
from armarius.domain.entities.task import TaskStatus
from armarius.domain.services.wake_policy import WakeCauseRefused
from armarius.domain.services.wake_reason import reason as wake_reason
from armarius.presentation.api.auth import CurrentUser
from armarius.presentation.api.frozen import refuse_when_frozen
from armarius.presentation.api.scoping import own_project, own_task
from armarius.presentation.deps import ContainerDep
from armarius.presentation.schemas import (
    AddDependencyIn,
    ApprovalOut,
    ArtifactOut,
    AssignIn,
    BlockerOut,
    CommentOut,
    CreateTaskIn,
    CriterionOut,
    EditTaskIn,
    NextActionIn,
    PostCommentIn,
    PublishArtifactIn,
    ReopenTaskIn,
    RunStartedOut,
    SetCriteriaIn,
    SignApprovalIn,
    TaskCardCountsOut,
    TaskDependencyEdgeOut,
    TaskLogEntryOut,
    TaskOut,
    TransitionIn,
    WakeIn,
    decode_artifact_content,
)

# FR-005 — a closed project is frozen. The guard hangs on the router, not on each
# route, so a route added later cannot forget it.
router = APIRouter(prefix="/v1", tags=["tasks"], dependencies=[Depends(refuse_when_frozen)])


def _parse_status(value: str) -> TaskStatus:
    try:
        return TaskStatus(value)
    except ValueError as exc:
        raise ValueError(f"unknown status '{value}'") from exc


@router.post("/projects/{project_id}/tasks", response_model=TaskOut, status_code=201)
async def create_task(
    project_id: UUID, body: CreateTaskIn, container: ContainerDep, user: CurrentUser
) -> TaskOut:
    await own_project(container, user, project_id)
    task = await container.tasks.create(
        project_id=project_id,
        title=body.title,
        description=body.description,
        status=_parse_status(body.status) if body.status else TaskStatus.BACKLOG,
        priority=body.priority,
        due_date=body.due_date,
        definition_of_done=body.definition_of_done,
        assigned_marius_id=body.assigned_marius_id,
        plan_item_id=body.plan_item_id,
        created_by_user_id=body.created_by_user_id,
    )
    return TaskOut.model_validate(task)


@router.get("/projects/{project_id}/tasks", response_model=list[TaskOut])
async def list_tasks(
    project_id: UUID,
    container: ContainerDep,
    user: CurrentUser,
    status: str | None = None,
) -> list[TaskOut]:
    await own_project(container, user, project_id)
    statuses = [s.strip() for s in status.split(",")] if status else None
    items = await container.tasks.list_by_project(project_id, statuses=statuses)
    return [TaskOut.model_validate(t) for t in items]


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: UUID, container: ContainerDep, user: CurrentUser
) -> TaskOut:
    return TaskOut.model_validate(await own_task(container, user, task_id))


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def edit_task(
    task_id: UUID, body: EditTaskIn, container: ContainerDep, user: CurrentUser
) -> TaskOut:
    """The patron's direct edit (FR-070, FR-070a) — effective immediately.

    Only the fields actually present in the request body are forwarded, so omitting a
    field leaves it alone while sending it as null clears it. Without that distinction a
    deadline entered by mistake could never be removed, which is the exact hole FR-070a
    was written to close.
    """
    await own_task(container, user, task_id)
    sent = body.model_dump(include=body.model_fields_set)
    task = await container.tasks.edit(task_id, user_id=str(user.id), **sent)
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/assign", response_model=TaskOut)
async def assign_task(
    task_id: UUID, body: AssignIn, container: ContainerDep, user: CurrentUser
) -> TaskOut:
    await own_task(container, user, task_id)
    task = await container.tasks.assign(
        task_id,
        body.marius_id,
        transfer_reason=body.transfer_reason,
        user_id=str(user.id),
    )
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/status", response_model=TaskOut)
async def transition_task(
    task_id: UUID, body: TransitionIn, container: ContainerDep, user: CurrentUser
) -> TaskOut:
    await own_task(container, user, task_id)
    task = await container.tasks.transition(
        task_id, _parse_status(body.status), reason=body.reason, user_id=str(user.id)
    )
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/reopen", response_model=TaskOut)
async def reopen_task(
    task_id: UUID, body: ReopenTaskIn, container: ContainerDep, user: CurrentUser
) -> TaskOut:
    """The only way out of *done*/*cancelled* (FR-022). Reason mandatory, trace kept."""
    await own_task(container, user, task_id)
    task = await container.tasks.reopen(task_id, reason=body.reason, user_id=str(user.id))
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/approval", response_model=TaskOut)
async def sign_approval(
    task_id: UUID, body: SignApprovalIn, container: ContainerDep, user: CurrentUser
) -> TaskOut:
    """The patron's signature on an output (FR-033, FR-035).

    Only the patron **responsible for the agent that did the work** may sign — the one who
    granted its seat (FR-034). Anyone else gets a 403; the task is not theirs to close.
    """
    await own_task(container, user, task_id)
    responsible = await container.approvals.responsible_patron(task_id)
    if responsible != str(user.id):
        raise PermissionError(
            "Chỉ người chủ đã cấp agent làm đầu việc này mới ký công nhận được."
        )
    task = await container.approvals.sign_as_patron(
        task_id, user_id=str(user.id), approve=body.approve, reason=body.reason
    )
    return TaskOut.model_validate(task)


@router.get("/tasks/{task_id}/approvals", response_model=list[ApprovalOut])
async def list_approvals(
    task_id: UUID, container: ContainerDep, user: CurrentUser
) -> list[ApprovalOut]:
    """Every signature on the task, oldest first — including the automatic ones (FR-039)."""
    await own_task(container, user, task_id)
    rows = await container.approvals.list_for_task(task_id)
    return [ApprovalOut.model_validate(a) for a in rows]


@router.get("/tasks/{task_id}/criteria", response_model=list[CriterionOut])
async def list_criteria(
    task_id: UUID, container: ContainerDep, user: CurrentUser
) -> list[CriterionOut]:
    await own_task(container, user, task_id)
    items = await container.tasks.list_criteria(task_id)
    return [CriterionOut.model_validate(i) for i in items]


@router.put("/tasks/{task_id}/criteria", response_model=list[CriterionOut])
async def set_criteria(
    task_id: UUID, body: SetCriteriaIn, container: ContainerDep, user: CurrentUser
) -> list[CriterionOut]:
    """Replace the yardstick — refused (409) once the worker has started (FR-019)."""
    await own_task(container, user, task_id)
    items = await container.tasks.set_criteria(
        task_id, [i.text for i in body.items], user_id=str(user.id)
    )
    return [CriterionOut.model_validate(i) for i in items]


@router.post("/tasks/{task_id}/next-action", response_model=TaskOut)
async def set_next_action(
    task_id: UUID, body: NextActionIn, container: ContainerDep, user: CurrentUser
) -> TaskOut:
    await own_task(container, user, task_id)
    task = await container.tasks.set_next_action(task_id, body.next_action)
    return TaskOut.model_validate(task)


@router.get("/tasks/{task_id}/dependencies", response_model=list[BlockerOut])
async def list_dependencies(
    task_id: UUID, container: ContainerDep, user: CurrentUser
) -> list[BlockerOut]:
    """Tasks this task is blocked_by (feeds the dependency-gate, §1.3)."""
    await own_task(container, user, task_id)
    blockers = await container.tasks.list_blockers(task_id)
    return [BlockerOut.model_validate(t) for t in blockers]


@router.post(
    "/tasks/{task_id}/dependencies",
    response_model=list[BlockerOut],
    status_code=201,
)
async def add_dependency(
    task_id: UUID, body: AddDependencyIn, container: ContainerDep, user: CurrentUser
) -> list[BlockerOut]:
    """Add a `blocked_by` edge, then return the refreshed blocker list.

    Both ends are checked: an edge names a second task, and letting a caller point one of
    their own tasks at a stranger's would leak that it exists through the blocker list.
    """
    await own_task(container, user, task_id)
    await own_task(container, user, body.blocks_task_id)
    await container.tasks.add_dependency(task_id, body.blocks_task_id)
    blockers = await container.tasks.list_blockers(task_id)
    return [BlockerOut.model_validate(t) for t in blockers]


@router.delete("/tasks/{task_id}/dependencies/{blocks_task_id}", status_code=204)
async def remove_dependency(
    task_id: UUID, blocks_task_id: UUID, container: ContainerDep, user: CurrentUser
) -> None:
    await own_task(container, user, task_id)
    await container.tasks.remove_dependency(task_id, blocks_task_id)


@router.get(
    "/projects/{project_id}/task-dependencies",
    response_model=list[TaskDependencyEdgeOut],
)
async def list_project_dependencies(
    project_id: UUID, container: ContainerDep, user: CurrentUser
) -> list[TaskDependencyEdgeOut]:
    """All `blocked_by` edges in the project — the board flags cards with an
    unfinished blocker from these plus the tasks it already loaded."""
    await own_project(container, user, project_id)
    edges = await container.tasks.list_project_dependencies(project_id)
    return [TaskDependencyEdgeOut.model_validate(e) for e in edges]


@router.get(
    "/projects/{project_id}/task-counts",
    response_model=list[TaskCardCountsOut],
)
async def list_task_card_counts(
    project_id: UUID, container: ContainerDep, user: CurrentUser
) -> list[TaskCardCountsOut]:
    """Criteria tally, comment count and artifact count for every card on the board.

    The board drew all three from arrays only the single-task screen ever fills, so on the
    board they were always empty (T177). One grouped read here rather than three reads per
    card: the board re-runs this on every push, and a fan-out over cards would make each
    signal cost more the busier the project got.
    """
    await own_project(container, user, project_id)
    counts = await container.tasks.card_counts(project_id)
    return [TaskCardCountsOut.model_validate(c) for c in counts]


@router.get("/tasks/{task_id}/comments", response_model=list[CommentOut])
async def list_comments(
    task_id: UUID, container: ContainerDep, user: CurrentUser
) -> list[CommentOut]:
    await own_task(container, user, task_id)
    items = await container.threads.list_comments(task_id)
    return [CommentOut.model_validate(c) for c in items]


@router.post("/tasks/{task_id}/comments", response_model=CommentOut, status_code=201)
async def post_comment(
    task_id: UUID, body: PostCommentIn, container: ContainerDep, user: CurrentUser
) -> CommentOut:
    await own_task(container, user, task_id)
    comment = await container.threads.post_comment(
        task_id=task_id,
        body=body.body,
        author_kind=AuthorKind(body.author_kind),
        author_user_id=body.author_user_id,
        extra_mentions=body.extra_mentions,
    )
    return CommentOut.model_validate(comment)


@router.get("/tasks/{task_id}/artifacts", response_model=list[ArtifactOut])
async def list_artifacts(
    task_id: UUID, container: ContainerDep, user: CurrentUser
) -> list[ArtifactOut]:
    await own_task(container, user, task_id)
    items = await container.artifacts.list_by_task(task_id)
    return [ArtifactOut.model_validate(a) for a in items]


@router.post("/tasks/{task_id}/artifacts", response_model=ArtifactOut, status_code=201)
async def publish_artifact(
    task_id: UUID, body: PublishArtifactIn, container: ContainerDep, user: CurrentUser
) -> ArtifactOut:
    await own_task(container, user, task_id)
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
async def wake_task(
    task_id: UUID, body: WakeIn, container: ContainerDep, user: CurrentUser
) -> RunStartedOut:
    await own_task(container, user, task_id)
    run_id = await container.wake_engine.enqueue(
        marius_id=body.marius_id,
        task_id=task_id,
        source=WakeSource.ON_DEMAND,
        reason=(
            wake_reason("manual_wake_note", note=body.reason)
            if (body.reason or "").strip()
            else wake_reason("manual_wake")
        ),
    )
    if run_id is None:
        # The engine refuses a cause the recipient's role may not be woken for (FR-048a).
        # This button's cause is one of the system's own, allowed for every role, so the
        # branch does not fire today — but the rule lives in the engine, not here, and a
        # route that answered with a null run id would be lying to whoever pressed it.
        raise WakeCauseRefused(
            "Không đánh thức được agent này: cớ gọi không thuộc phần việc của vai họ."
        )
    return RunStartedOut(run_id=run_id)


@router.get("/tasks/{task_id}/log", response_model=list[TaskLogEntryOut])
async def task_log(
    task_id: UUID, container: ContainerDep, user: CurrentUser
) -> list[TaskLogEntryOut]:
    """The task's whole history, oldest first (spec 001 §10, FR-079).

    Distinct from ``/tasks/{id}/stream``, which follows one agent run — this follows the
    task across every run, assignee and signature it ever had.
    """
    await own_task(container, user, task_id)
    entries = await container.task_logs.list_for_task(task_id)
    return [TaskLogEntryOut.model_validate(e) for e in entries]
