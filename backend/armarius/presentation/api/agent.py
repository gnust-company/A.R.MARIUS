"""Agent-facing API — the Armarius skills an onboarded Marius calls back into (§6.2).

Authenticated by the per-Marius bearer token. These endpoints are what make the
collaboration loop real: claim, comment/@mention, update status, record next_action,
and publish artifacts into the shared store.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from armarius.application.use_cases.onboarding_brain import _slug
from armarius.application.use_cases.plans import PlanItemSpec
from armarius.domain.entities.checklist_item import AcceptanceResult
from armarius.domain.entities.comment import AuthorKind
from armarius.domain.entities.marius import Liveness, Marius
from armarius.domain.entities.project import ProjectStatus
from armarius.domain.entities.task import Task, TaskStatus
from armarius.presentation.api.frozen import refuse_when_frozen
from armarius.presentation.container import Container
from armarius.presentation.deps import ContainerDep, CurrentMarius
from armarius.presentation.schemas import (
    AgentArtifactIn,
    AgentAssignmentRequestIn,
    AgentCommentIn,
    AgentCreateTaskIn,
    AgentGiveUpIn,
    AgentHandbackIn,
    AgentMajorChangeIn,
    AgentOnboardingCompleteIn,
    AgentOnboardingQuestionIn,
    AgentRecoveryIn,
    ArtifactOut,
    CommentOut,
    CriterionOut,
    MariusOut,
    NextActionIn,
    OnboardingOut,
    PhaseChangeIn,
    PlanIn,
    PlanOut,
    ProjectContextIn,
    ProjectContextOut,
    RateCriterionIn,
    SignApprovalIn,
    SprintSummaryIn,
    TaskOut,
    TransitionIn,
    decode_artifact_content,
)
from armarius.shared.errors import BadRequest, NotFound

# FR-005 — a closed project is frozen. The guard hangs on the router, not on each
# route, so a route added later cannot forget it.
router = APIRouter(prefix="/agent", tags=["agent"], dependencies=[Depends(refuse_when_frozen)])


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


# ── onboarding callbacks (a live Workspace-Agent runtime drives the interview) ─
async def _wa_onboarding_session(container, marius, session_id: UUID):
    """Load an onboarding session, asserting this Marius is its workspace's host agent."""
    session = await container.onboarding.get(session_id)
    if session is None or session.workspace_id is None:
        raise NotFound("onboarding_session_not_found")
    ws = await container.workspaces.get_workspace(session.workspace_id)
    if ws is None or ws.workspace_agent_id != marius.id:
        raise NotFound("onboarding_session_not_found")
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


async def _task_in_caller_workspace(
    container: Container, marius: Marius, task_id: UUID
) -> Task:
    """Resolve a task through the caller's workspace, or 404.

    Every ``/agent/tasks/*`` route goes through here: agent tokens are per-workspace, so a
    task from another workspace must read as *not found* rather than *forbidden* — its
    existence is not something another tenant gets to learn (Constitution I). Also the one
    place that narrows the agent's optional workspace id, instead of each route doing it.
    """
    if marius.workspace_id is None:
        raise NotFound("task_not_found")
    return await container.tasks.get_in_workspace(task_id, marius.workspace_id)


@router.post("/projects/{project_id}/tasks", response_model=TaskOut, status_code=201)
async def agent_create_task(
    project_id: UUID,
    body: AgentCreateTaskIn,
    marius: CurrentMarius,
    container: ContainerDep,
) -> TaskOut:
    """The Leader's create-task tool.

    Work attached to an approved plan item goes live and is assigned at once; work
    attached to nothing stays a draft and the patron is asked, because it widens the
    project's scope (FR-027). Scoped to the caller's workspace (#15)."""
    project = await container.projects.get_project(project_id)
    if project is None or project.workspace_id != marius.workspace_id:
        raise NotFound("project_not_found")  # cross-workspace → 404
    task = await container.tasks.propose(
        project_id=project_id,
        title=body.title,
        description=body.description,
        created_by_marius_id=marius.id,
        assigned_marius_id=body.assignee_marius_id,
        plan_item_id=body.plan_item_id,
    )
    return TaskOut.model_validate(task)


@router.post("/projects/{project_id}/change-request", status_code=202)
async def agent_request_major_change(
    project_id: UUID,
    body: AgentMajorChangeIn,
    marius: CurrentMarius,
    container: ContainerDep,
) -> dict[str, str]:
    """Ask the patron before changing what they agreed to (FR-075).

    Five areas only — scope, objective, cost, deadline, acceptance criteria. Everything
    else is the Leader's to decide on its own (FR-074), and a gate that caught
    everything would be a gate people learned to route around.

    202, not 200: the change has been *asked about*, not made.
    """
    project = await container.projects.get_project(project_id)
    if project is None or project.workspace_id != marius.workspace_id:
        raise NotFound("project_not_found")  # cross-workspace → 404
    item = await container.plans.request_major_change(
        project_id,
        area=body.area,
        summary=body.summary,
        detail=body.detail,
    )
    return {"item_id": str(item.id), "status": "awaiting_patron_approval"}


@router.post("/tasks/{task_id}/recovery", response_model=TaskOut)
async def agent_declare_recovery(
    task_id: UUID,
    body: AgentRecoveryIn,
    marius: CurrentMarius,
    container: ContainerDep,
) -> TaskOut:
    """The Leader names the recovery action Level 2 was waiting for (FR-059).

    Without this, Level 2 is a rung with no way off it: the ladder waits for a decision
    that has nowhere to be recorded, and the next sweep climbs to the patron anyway —
    telling them nobody decided, while the Leader was deciding.

    Leader seat required, same as the other door out of Level 2 (FR-060b). The pair is
    described as one window with two exits, so a check on one and not the other is a hole
    at the shape of the missing check: what this door writes is a *decision in the Leader's
    name*, and the dossier the patron eventually reads is built out of exactly those
    records. A worker filing "Leader decided: reassign to Bob" dirties the one thing
    FR-061 exists to keep clean.
    """
    task = await _task_in_caller_workspace(container, marius, task_id)
    if task.project_id is None:
        raise NotFound("task_not_found")
    await _leader_seat(container, marius, task.project_id)
    await container.recovery.leader_decided(task_id, action=body.action)
    if body.next_action:
        task = await container.tasks.set_next_action(task_id, body.next_action)
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/escalate", status_code=202)
async def agent_escalate_task(
    task_id: UUID,
    body: AgentGiveUpIn,
    marius: CurrentMarius,
    container: ContainerDep,
) -> dict[str, str]:
    """The Leader hands a stalled task straight to the patron (FR-059).

    The other door out of Level 2 is to fix it. Without this one, a Leader that knows in
    seconds it cannot help has only two moves: sit out the whole budget of asks, or invent
    an action so as to look busy. Both waste more than saying so.

    Leader seat required, unlike the sibling doors on this router. They route work between
    agents; this one reaches a person, and the whole ladder is ordered so that a human is
    the last resort — a worker that could hand its own stuck task straight to the patron
    would walk around every rung in one call, which is what `NotOnTheLeadersRung` guards
    against from the other direction.
    """
    task = await _task_in_caller_workspace(container, marius, task_id)
    if task.project_id is None:
        raise NotFound("task_not_found")
    await _leader_seat(container, marius, task.project_id)
    await container.recovery.leader_gave_up(task_id, reason=body.reason)
    return {"status": "raised_to_patron"}


@router.get("/projects/{project_id}/queue", response_model=list[TaskOut])
async def agent_ready_queue(
    project_id: UUID,
    marius: CurrentMarius,
    container: ContainerDep,
) -> list[TaskOut]:
    """What to hand out next, in order (FR-066, FR-067).

    The Leader still decides who does what — this answers the question underneath that
    decision, and answers it the same way every time: priority, then deadline, then age,
    with the wait itself promoting a task so nothing at the bottom is starved.

    Anything standing behind a pending patron decision is left out, and **only** that.
    A project parks at the question, not across the whole board (FR-066).
    """
    project = await container.projects.get_project(project_id)
    if project is None or project.workspace_id != marius.workspace_id:
        raise NotFound("project_not_found")  # cross-workspace → 404
    return [
        TaskOut.model_validate(t)
        for t in await container.tasks.ready_queue(project_id)
    ]


@router.get("/tasks/{task_id}")
async def get_task_view(
    task_id: UUID, marius: CurrentMarius, container: ContainerDep
) -> dict:
    # Agent tokens are per-workspace: every /agent/tasks/* route resolves the task
    # through get_in_workspace so a token can't touch another workspace's tasks (#15).
    task = await _task_in_caller_workspace(container, marius, task_id)
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


# The self-claim route is gone (FR-072). A worker no longer takes work; it asks, and the
# Leader — which can see the whole board — decides. Both routes below leave the assignee
# untouched on purpose.


@router.post("/tasks/{task_id}/request", response_model=TaskOut)
async def request_task(
    task_id: UUID,
    body: AgentAssignmentRequestIn,
    marius: CurrentMarius,
    container: ContainerDep,
) -> TaskOut:
    """Ask to be put on a task. Routed to the Leader; nothing is assigned here."""
    await _task_in_caller_workspace(container, marius, task_id)
    task = await container.tasks.request_assignment(task_id, marius.id, note=body.note)
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/handback", response_model=TaskOut)
async def handback_task(
    task_id: UUID,
    body: AgentHandbackIn,
    marius: CurrentMarius,
    container: ContainerDep,
) -> TaskOut:
    """Hand work back, or ask a clarifying question. Healthy behaviour: the task keeps a
    live drive (a wake is booked for the Leader) and is not counted as stalled."""
    await _task_in_caller_workspace(container, marius, task_id)
    task = await container.tasks.hand_back(task_id, marius.id, reason=body.reason)
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/comment", response_model=CommentOut, status_code=201)
async def post_comment(
    task_id: UUID, body: AgentCommentIn, marius: CurrentMarius, container: ContainerDep
) -> CommentOut:
    await _task_in_caller_workspace(container, marius, task_id)
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
    await _task_in_caller_workspace(container, marius, task_id)
    try:
        target = TaskStatus(body.status)
    except ValueError as exc:
        raise BadRequest("unknown_task_status", status=body.status) from exc
    task = await container.tasks.transition(
        task_id, target, reason=body.reason, marius_id=marius.id
    )
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/approval", response_model=TaskOut)
async def sign_approval(
    task_id: UUID, body: SignApprovalIn, marius: CurrentMarius, container: ContainerDep
) -> TaskOut:
    """The Leader's signature — the first of the two (FR-033).

    Only the Leader signs here. A worker signing off its own output is exactly the "fake
    done" this story exists to stop, so a non-leader caller reads as *not found* rather
    than *forbidden*: the route is not theirs to know about.
    """
    task = await _task_in_caller_workspace(container, marius, task_id)
    if task.project_id is None:
        raise NotFound("task_not_found")
    await _leader_seat(container, marius, task.project_id)
    signed = await container.approvals.sign_as_leader(
        task_id, marius_id=marius.id, approve=body.approve, reason=body.reason
    )
    return TaskOut.model_validate(signed)


@router.get("/tasks/{task_id}/criteria", response_model=list[CriterionOut])
async def agent_list_criteria(
    task_id: UUID, marius: CurrentMarius, container: ContainerDep
) -> list[CriterionOut]:
    """The yardstick this task is measured against, and how it stands so far.

    Readable by any agent on the task, not only the Leader: the worker is entitled to know
    what it is being judged on, and a criteria list it cannot read is a brief it was never
    given (FR-019).
    """
    await _task_in_caller_workspace(container, marius, task_id)
    items = await container.tasks.list_criteria(task_id)
    return [CriterionOut.model_validate(i) for i in items]


@router.post("/tasks/{task_id}/criteria/{criterion_id}", response_model=CriterionOut)
async def rate_criterion(
    task_id: UUID,
    criterion_id: UUID,
    body: RateCriterionIn,
    marius: CurrentMarius,
    container: ContainerDep,
) -> CriterionOut:
    """Score one criterion (Story 3 scenario 1) — the Leader's seat only.

    Same rule as the signature next door, for the same reason: scoring *is* the judgement,
    and a worker that could mark its own work passed would walk straight through the gate
    the criteria exist to be. A non-leader reads as *not found*, not *forbidden*.
    """
    task = await _task_in_caller_workspace(container, marius, task_id)
    if task.project_id is None:
        raise NotFound("task_not_found")
    await _leader_seat(container, marius, task.project_id)
    item = await container.tasks.rate_criterion(
        task_id,
        criterion_id,
        result=AcceptanceResult(body.result),
        evidence_artifact_id=body.evidence_artifact_id,
        marius_id=marius.id,
    )
    return CriterionOut.model_validate(item)


@router.post("/tasks/{task_id}/next-action", response_model=TaskOut)
async def set_next_action(
    task_id: UUID, body: NextActionIn, marius: CurrentMarius, container: ContainerDep
) -> TaskOut:
    await _task_in_caller_workspace(container, marius, task_id)
    task = await container.tasks.set_next_action(task_id, body.next_action)
    return TaskOut.model_validate(task)


@router.post("/tasks/{task_id}/artifact", response_model=ArtifactOut, status_code=201)
async def publish_artifact(
    task_id: UUID, body: AgentArtifactIn, marius: CurrentMarius, container: ContainerDep
) -> ArtifactOut:
    await _task_in_caller_workspace(container, marius, task_id)
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


# ── Leader: context, plan, phase proposal (spec 001, contracts/agent-surface.md §2) ───
#
# Note what is NOT here: there is no route for deciding on a plan or moving a phase. The
# Leader submits and proposes; the patron decides (FR-004, FR-014). The absence is the
# enforcement — a missing route cannot be called by mistake.


async def _leader_seat(container, marius: Marius, project_id: UUID) -> None:
    """Refuse unless the caller holds the leader seat on this project (Constitution V).

    Cross-workspace and non-leader both read as *not found*, so a token cannot be used to
    probe which projects exist elsewhere.
    """
    project = await container.projects.get_project(project_id)
    if project is None or project.workspace_id != marius.workspace_id:
        raise NotFound("project_not_found")
    seats = await container.projects.list_agents(project_id)
    if not any(s.marius_id == marius.id and s.is_primary for s in seats):
        raise NotFound("project_not_found")


@router.post("/projects/{project_id}/context", response_model=ProjectContextOut)
async def submit_project_context(
    project_id: UUID,
    body: ProjectContextIn,
    marius: CurrentMarius,
    container: ContainerDep,
) -> ProjectContextOut:
    """Submit the brief agreed with the patron → awaits their approval (FR-008)."""
    await _leader_seat(container, marius, project_id)
    context = await container.plans.submit_context(
        project_id,
        objective=body.objective,
        background=body.background,
        constraints=body.constraints,
        scope=body.scope,
        principles=body.principles,
    )
    return ProjectContextOut.model_validate(context)


@router.post("/projects/{project_id}/plan", response_model=PlanOut)
async def submit_project_plan(
    project_id: UUID, body: PlanIn, marius: CurrentMarius, container: ContainerDep
) -> PlanOut:
    """Submit the plan → it parks in the patron's inbox, and stays there (FR-011)."""
    await _leader_seat(container, marius, project_id)
    plan = await container.plans.submit_plan(
        project_id,
        summary=body.summary,
        risks=body.risks,
        milestones=body.milestones,
        items=[
            PlanItemSpec(
                title=item.title,
                description=item.description,
                order=item.order,
                definition_of_done=item.definition_of_done,
                depends_on=list(item.depends_on),
            )
            for item in body.items
        ],
    )
    return PlanOut.model_validate(plan)


@router.post("/projects/{project_id}/phase-proposal", status_code=200)
async def propose_project_phase(
    project_id: UUID,
    body: PhaseChangeIn,
    marius: CurrentMarius,
    container: ContainerDep,
) -> dict:
    """Ask the patron to move the project. Changes nothing on its own (FR-004)."""
    await _leader_seat(container, marius, project_id)
    await container.projects.propose_phase(
        project_id,
        target_phase=_parse_phase(body.target_phase),
        reason=body.reason or "",
    )
    return {"status": "proposed", "target_phase": body.target_phase}


@router.post("/projects/{project_id}/sprint-summary", status_code=200)
async def submit_sprint_summary(
    project_id: UUID,
    body: SprintSummaryIn,
    marius: CurrentMarius,
    container: ContainerDep,
) -> dict[str, object]:
    """Wrap up a finished batch and hand the patron their three choices (FR-043).

    Not an acceptance gate — there is none at project level (FR-042). The work was signed
    off task by task; what is left is deciding what happens next.
    """
    await _leader_seat(container, marius, project_id)
    await container.projects.submit_sprint_summary(project_id, summary=body.summary)
    return {"status": "sent", "choices": list(container.projects.SPRINT_CHOICES)}


def _parse_phase(value: str) -> ProjectStatus:
    try:
        return ProjectStatus(value)
    except ValueError as exc:
        raise BadRequest("unknown_project_phase", phase=value) from exc
