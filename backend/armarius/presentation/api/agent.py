"""Agent-facing API — the Armarius skills an onboarded Marius calls back into (§6.2).

Authenticated by the per-Marius bearer token. These endpoints are what make the
collaboration loop real: claim, comment/@mention, update status, record next_action,
and publish artifacts into the shared store.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from armarius.domain.entities.comment import AuthorKind
from armarius.domain.entities.marius import Liveness
from armarius.domain.entities.task import TaskStatus
from armarius.presentation.deps import ContainerDep, CurrentMarius
from armarius.presentation.schemas import (
    AgentArtifactIn,
    AgentClaimIn,
    AgentCommentIn,
    AgentEnrollIn,
    AgentSkillBundleOut,
    AgentSkillSummary,
    AgentTokenOut,
    ArtifactOut,
    CommentOut,
    MariusOut,
    NextActionIn,
    TaskOut,
    TransitionIn,
    decode_artifact_content,
)

router = APIRouter(prefix="/agent", tags=["agent"])


# ── enroll-and-wait (pre-token; API_CONTRACT §4.1, §9) ───────────────────────
@router.post("/enroll", response_model=AgentTokenOut)
async def enroll(body: AgentEnrollIn, container: ContainerDep) -> AgentTokenOut:
    """Present the enrollment_code and **hold** until the Patron approves; the minted
    agent_token is returned on this same call."""
    token = await container.enrollment.enroll(body.marius_id, body.enrollment_code)
    return AgentTokenOut(agent_token=token)


@router.post("/claim", response_model=AgentTokenOut)
async def claim(body: AgentClaimIn, container: ContainerDep) -> AgentTokenOut:
    """Recovery fallback: return the token iff already approved (enroll session lost)."""
    token = await container.enrollment.claim(body.marius_id, body.enrollment_code)
    return AgentTokenOut(agent_token=token)


@router.get("/me")
async def whoami(marius: CurrentMarius, container: ContainerDep) -> dict:
    # Every agent call is a liveness signal (API_CONTRACT §9): fold it in → ONLINE.
    was_online = marius.liveness == Liveness.ONLINE
    marius = await container.liveness.record_signal(marius.id)
    if not was_online:
        # First contact (or a return from silence) → control-plane ping (§2).
        await container.control_bus.publish(
            f"ws:{marius.workspace_id}",
            "marius.online",
            {"marius_id": str(marius.id)},
        )
        # A Leader back online drains any commission turns queued while it was away (§2.13).
        await container.commission.on_leader_online(marius.id)
    directory = await container.mariuses.list_directory(marius.workspace_id)
    return {
        "marius": MariusOut.model_validate(marius).model_dump(mode="json"),
        "directory": [
            MariusOut.model_validate(m).model_dump(mode="json")
            for m in directory
            if m.id != marius.id
        ],
    }


# ── skill install (fetch the full file tree of your linked skills) ───────────
@router.get("/skills", response_model=list[AgentSkillSummary])
async def list_my_skills(
    marius: CurrentMarius, container: ContainerDep
) -> list[AgentSkillSummary]:
    """The skills linked to you — slug + file count. Fetch each one's full file tree
    from GET /agent/skills/{slug} and write it under your runtime's skills directory."""
    linked = await container.skills.resolve(marius.skill_ids)
    return [
        AgentSkillSummary(
            slug=sk.slug,
            name=sk.name,
            description=sk.description,
            file_count=len(sk.files),
        )
        for sk in linked
    ]


@router.get("/skills/{slug}", response_model=AgentSkillBundleOut)
async def get_my_skill_bundle(
    slug: str, marius: CurrentMarius, container: ContainerDep
) -> AgentSkillBundleOut:
    """One linked skill's complete file tree (path → content). 404 if the slug is not
    linked to you — you can only install skills your patron granted you."""
    linked = await container.skills.resolve(marius.skill_ids)
    for sk in linked:
        if sk.slug == slug:
            return AgentSkillBundleOut(
                slug=sk.slug,
                name=sk.name,
                description=sk.description,
                files=sk.files,
            )
    raise LookupError(f"skill '{slug}' is not linked to you")


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
        content=decode_artifact_content(
            content_b64=body.content_b64,
            content=body.content,
            content_sha256=body.content_sha256,
        ),
        uri=body.uri,
        marius_id=marius.id,
    )
    return ArtifactOut.model_validate(artifact)
