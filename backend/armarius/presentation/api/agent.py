"""Agent-facing API — the Armarius skills an onboarded Marius calls back into (§6.2).

Authenticated by the per-Marius bearer token. These endpoints are what make the
collaboration loop real: claim, comment/@mention, update status, record next_action,
and publish artifacts into the shared store.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from armarius.application.use_cases.onboarding_brain import _slug
from armarius.domain.entities.comment import AuthorKind
from armarius.domain.entities.marius import Liveness
from armarius.domain.entities.task import TaskStatus
from armarius.presentation.deps import ContainerDep, CurrentMarius
from armarius.presentation.schemas import (
    AgentArtifactIn,
    AgentCommentIn,
    AgentCreateTaskIn,
    AgentOnboardingCompleteIn,
    AgentOnboardingQuestionIn,
    AgentSkillBundleOut,
    AgentSkillSummary,
    ArtifactOut,
    CommentOut,
    MariusOut,
    NextActionIn,
    OnboardingOut,
    TaskOut,
    TransitionIn,
    decode_artifact_content,
)

router = APIRouter(prefix="/agent", tags=["agent"])


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
async def effective_skills(container, marius) -> list:
    """The skills linked to this Marius (what these routes serve). The onboarding playbook is
    no longer a granted skill — it is injected into the Workspace Agent's prompt at start (#61)."""
    return list(await container.skills.resolve(marius.skill_ids))


@router.get("/skills", response_model=list[AgentSkillSummary])
async def list_my_skills(
    marius: CurrentMarius, container: ContainerDep
) -> list[AgentSkillSummary]:
    """The skills linked to you — slug + file count. Fetch each one's full file tree
    from GET /agent/skills/{slug} and write it under your runtime's skills directory."""
    linked = await effective_skills(container, marius)
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
    linked = await effective_skills(container, marius)
    for sk in linked:
        if sk.slug == slug:
            return AgentSkillBundleOut(
                slug=sk.slug,
                name=sk.name,
                description=sk.description,
                files=sk.files,
            )
    raise LookupError(f"skill '{slug}' is not linked to you")


@router.post("/skills/{slug}/installed", status_code=200)
async def confirm_skill_installed(
    slug: str, marius: CurrentMarius, container: ContainerDep
) -> dict[str, str]:
    """Confirm you finished installing a linked skill (#74) → install state flips to
    'installed', and the patron's UI updates in realtime. 404 if the slug is not linked to
    you (you can only confirm skills you were granted)."""
    linked = await effective_skills(container, marius)
    if not any(sk.slug == slug for sk in linked):
        raise LookupError(f"skill '{slug}' is not linked to you")
    updated = await container.mariuses.set_skill_installs(marius.id, {slug: "installed"})
    await container.control_bus.publish(
        f"ws:{updated.workspace_id}",
        "marius.skill_installed",
        {"marius_id": str(marius.id), "slug": slug},
    )
    return {"slug": slug, "status": "installed"}


# ── onboarding callbacks (a live Workspace-Agent runtime drives the interview) ─
async def _wa_onboarding_session(container, marius, session_id: UUID):
    """Load an onboarding session, asserting this Marius is its workspace's host agent."""
    session = await container.onboarding.get(session_id)
    if session is None or session.workspace_id is None:
        raise LookupError("onboarding session not found")
    ws = await container.workspaces.get_workspace(session.workspace_id)
    if ws is None or ws.workspace_agent_id != marius.id:
        raise LookupError("onboarding session not found")
    return session


@router.post("/onboarding/{session_id}/question", response_model=OnboardingOut)
async def post_onboarding_question(
    session_id: UUID,
    body: AgentOnboardingQuestionIn,
    marius: CurrentMarius,
    container: ContainerDep,
) -> OnboardingOut:
    """Post your next onboarding question. One question at a time — 409 if the previous
    question is still unanswered (wait for the Patron's answer, don't retry)."""
    await _wa_onboarding_session(container, marius, session_id)
    question = {
        "question": body.question,
        "options": [{"id": o.id, "label": o.label} for o in body.options],
        "multi": body.multi,
    }
    session = await container.onboarding.agent_post_question(session_id, question)
    return OnboardingOut.model_validate(session)


@router.post("/onboarding/{session_id}/complete", response_model=OnboardingOut)
async def post_onboarding_complete(
    session_id: UUID,
    body: AgentOnboardingCompleteIn,
    marius: CurrentMarius,
    container: ContainerDep,
) -> OnboardingOut:
    """Post your final project + roster draft for the Patron to confirm and finalize."""
    await _wa_onboarding_session(container, marius, session_id)
    draft = {
        "name": body.project.name,
        "objective": body.project.objective,
        "success_metrics": body.project.success_metrics,
        "target_date": body.project.target_date,
        "context": body.project.context,
        "roster": [
            {"key": _slug(r.title), "title": r.title, "seats": r.seats,
             "is_leader": r.is_leader, "description": r.description, "skills": list(r.skills)}
            for r in body.roster
        ],
    }
    session = await container.onboarding.agent_post_complete(session_id, draft)
    return OnboardingOut.model_validate(session)


@router.post("/projects/{project_id}/tasks", response_model=TaskOut, status_code=201)
async def agent_create_task(
    project_id: UUID,
    body: AgentCreateTaskIn,
    marius: CurrentMarius,
    container: ContainerDep,
) -> TaskOut:
    """The Leader's create-task tool (Chat-with-Leader, #82). Creates a DRAFT awaiting the
    patron's approval; if the project's YOLO mode is on, it is auto-approved (→ todo, and
    the proposed assignee is woken). Scoped to the caller's workspace (#15)."""
    project = await container.projects.get_project(project_id)
    if project is None or project.workspace_id != marius.workspace_id:
        raise LookupError("project not found")  # cross-workspace → 404
    task = await container.tasks.create(
        project_id=project_id,
        title=body.title,
        description=body.description,
        status=TaskStatus.DRAFT,
        created_by_marius_id=marius.id,
        assigned_marius_id=body.assignee_marius_id,
    )
    if project.settings.get("yolo_mode", False):
        task = await container.tasks.approve_proposed(task.id)
    return TaskOut.model_validate(task)


@router.get("/tasks/{task_id}")
async def get_task_view(
    task_id: UUID, marius: CurrentMarius, container: ContainerDep
) -> dict:
    # Agent tokens are per-workspace: every /agent/tasks/* route resolves the task
    # through get_in_workspace so a token can't touch another workspace's tasks (#15).
    task = await container.tasks.get_in_workspace(task_id, marius.workspace_id)
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
    await container.tasks.get_in_workspace(task_id, marius.workspace_id)
    task = await container.tasks.claim(task_id, marius.id)
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/comment", response_model=CommentOut, status_code=201)
async def post_comment(
    task_id: UUID, body: AgentCommentIn, marius: CurrentMarius, container: ContainerDep
) -> CommentOut:
    await container.tasks.get_in_workspace(task_id, marius.workspace_id)
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
    await container.tasks.get_in_workspace(task_id, marius.workspace_id)
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
    await container.tasks.get_in_workspace(task_id, marius.workspace_id)
    task = await container.tasks.set_next_action(task_id, body.next_action)
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/artifact", response_model=ArtifactOut, status_code=201)
async def publish_artifact(
    task_id: UUID, body: AgentArtifactIn, marius: CurrentMarius, container: ContainerDep
) -> ArtifactOut:
    await container.tasks.get_in_workspace(task_id, marius.workspace_id)
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
