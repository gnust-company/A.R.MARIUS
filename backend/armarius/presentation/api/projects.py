"""Project, roster and seat endpoints (human/Patron surface, API_CONTRACT §3).

These wire `ProjectService` (create-with-brief, system-only grants, SETUP→ACTIVE activation)
to HTTP. Every route is scoped to the caller's workspace — touching a project in someone
else's workspace is a 404.

**There is no door here that makes a role, and putting an agent on a project takes one call**
(FR-007l). It used to take two, and the first of them asked the patron to invent a role: a
title, a seat count and a description of the work, written a second time next to the
instructions already on the agent. What an agent is comes from the agent; the project only
needs to know it is here, and whether it leads.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends

from armarius.domain.entities.project import Project, ProjectStatus
from armarius.domain.services.plan_gate import PlanDecision
from armarius.presentation.api.auth import CurrentUser
from armarius.presentation.api.frozen import refuse_when_frozen
from armarius.presentation.deps import ContainerDep
from armarius.presentation.schemas import (
    AutoApprovalIn,
    AutoApprovalOut,
    ContextDecisionIn,
    CreateProjectPlanIn,
    OrchestrationOut,
    PhaseChangeIn,
    PlanDecisionIn,
    PlanOut,
    ProjectContextOut,
    ProjectContextViewOut,
    ProjectDetailOut,
    ProjectOut,
    RosterRoleOut,
    SeatAgentIn,
    SeatGrantOut,
    SeatOut,
    SnagOut,
    ThresholdsIn,
    ThresholdsOut,
    UpdateProjectIn,
)
from armarius.shared.clock import as_utc
from armarius.shared.errors import BadRequest, NotFound

# FR-005 — a closed project is frozen. The guard hangs on the router, not on each
# route, so a route added later cannot forget it.
router = APIRouter(prefix="/v1", tags=["projects"], dependencies=[Depends(refuse_when_frozen)])


async def _require_owned_workspace(container, user, workspace_id: UUID):
    ws = await container.workspaces.get_workspace(workspace_id)
    if ws is None or ws.owner_user_id != str(user.id):
        raise NotFound("workspace_not_found")
    return ws


async def _require_owned_project(container, user, project_id: UUID) -> Project:
    project = await container.projects.get_project(project_id)
    if project is None:
        raise NotFound("project_not_found")
    ws = await container.workspaces.get_workspace(project.workspace_id)
    if ws is None or ws.owner_user_id != str(user.id):
        raise NotFound("project_not_found")  # cross-workspace → 404
    return project


async def _detail(container, project: Project) -> ProjectDetailOut:
    roster_views = await container.projects.get_roster(project.id)
    out = ProjectDetailOut.model_validate(project)
    out.roster = [
        RosterRoleOut(
            key=r.key,
            title=r.title,
            seats=r.seats,
            is_leader=r.is_leader,
            description=r.description,
            skill_ids=r.skill_ids,
            filled=r.filled,
            seated=[
                SeatOut(
                    marius_id=s.marius_id,
                    name=s.name,
                    role_key=s.role_key,
                    liveness=s.liveness,
                    is_primary=s.is_primary,
                )
                for s in r.seated
            ],
        )
        for r in roster_views
    ]
    return out


# ── projects ─────────────────────────────────────────────────────────────────
@router.get("/workspaces/{workspace_id}/projects", response_model=list[ProjectOut])
async def list_projects(
    workspace_id: UUID, container: ContainerDep, user: CurrentUser
) -> list[ProjectOut]:
    await _require_owned_workspace(container, user, workspace_id)
    rows = await container.projects.list_with_seat_counts(workspace_id)
    out: list[ProjectOut] = []
    for project, seats_total, seats_filled in rows:
        item = ProjectOut.model_validate(project)
        item.seats_total = seats_total
        item.seats_filled = seats_filled
        out.append(item)
    return out


@router.post(
    "/workspaces/{workspace_id}/projects",
    response_model=ProjectDetailOut,
    status_code=201,
)
async def create_project(
    workspace_id: UUID,
    body: CreateProjectPlanIn,
    container: ContainerDep,
    user: CurrentUser,
) -> ProjectDetailOut:
    await _require_owned_workspace(container, user, workspace_id)

    project = await container.projects.create_project(
        workspace_id,
        body.name,
        leader_description=body.leader.description,
        key=body.key,
        description=body.description,
        objective=body.objective,
        created_by_user_id=str(user.id),
    )

    # Brief fields beyond name/description/objective (validated already → project exists).
    if any(
        v is not None
        for v in (
            body.success_metrics,
            body.target_date,
            body.github_url,
            body.context,
            body.settings,
        )
    ):
        project = await container.projects.update_project(
            project.id,
            success_metrics=body.success_metrics,
            target_date=body.target_date,
            github_url=body.github_url,
            context=body.context,
            settings=body.settings,
        )

    # Seat whoever the plan named (system-only grants → may activate the project).
    if body.leader.marius_id is not None:
        await container.projects.seat_leader(
            project.id, body.leader.marius_id, granted_by_user_id=str(user.id)
        )
    for marius_id in dict.fromkeys(body.members):
        await container.projects.add_member(
            project.id, marius_id, granted_by_user_id=str(user.id)
        )

    project = await container.projects.get_project(project.id)
    return await _detail(container, project)


@router.get("/projects/{project_id}", response_model=ProjectDetailOut)
async def get_project(
    project_id: UUID, container: ContainerDep, user: CurrentUser
) -> ProjectDetailOut:
    project = await _require_owned_project(container, user, project_id)
    return await _detail(container, project)


@router.patch("/projects/{project_id}", response_model=ProjectDetailOut)
async def update_project(
    project_id: UUID,
    body: UpdateProjectIn,
    container: ContainerDep,
    user: CurrentUser,
) -> ProjectDetailOut:
    await _require_owned_project(container, user, project_id)
    project = await container.projects.update_project(
        project_id,
        description=body.description,
        objective=body.objective,
        success_metrics=body.success_metrics,
        target_date=body.target_date,
        github_url=body.github_url,
        context=body.context,
        settings=body.settings,
    )
    return await _detail(container, project)


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: UUID, container: ContainerDep, user: CurrentUser
) -> None:
    await _require_owned_project(container, user, project_id)
    await container.projects.delete_project(project_id)


# ── roster ───────────────────────────────────────────────────────────────────
@router.get("/projects/{project_id}/roster", response_model=list[RosterRoleOut])
async def get_roster(
    project_id: UUID, container: ContainerDep, user: CurrentUser
) -> list[RosterRoleOut]:
    project = await _require_owned_project(container, user, project_id)
    detail = await _detail(container, project)
    return detail.roster


# ── auto-approval switch (spec 001 FR-036 → FR-038) ───────────────────────────
@router.get("/projects/{project_id}/auto-approval", response_model=AutoApprovalOut)
async def get_auto_approval(
    project_id: UUID, container: ContainerDep, user: CurrentUser
) -> AutoApprovalOut:
    """This patron's own switch. Off until they turn it on (FR-038)."""
    await _require_owned_project(container, user, project_id)
    enabled = await container.approvals.auto_approval(project_id, str(user.id))
    return AutoApprovalOut(project_id=project_id, user_id=str(user.id), enabled=enabled)


@router.put("/projects/{project_id}/auto-approval", response_model=AutoApprovalOut)
async def set_auto_approval(
    project_id: UUID, body: AutoApprovalIn, container: ContainerDep, user: CurrentUser
) -> AutoApprovalOut:
    """Only the patron flips their own switch — there is no agent-facing route for this
    on purpose (FR-038): an agent that could waive its own second signature would have
    turned two signatures into one."""
    await _require_owned_project(container, user, project_id)
    enabled = await container.approvals.set_auto_approval(
        project_id, str(user.id), enabled=body.enabled
    )
    return AutoApprovalOut(project_id=project_id, user_id=str(user.id), enabled=enabled)


@router.get("/projects/{project_id}/grants", response_model=list[SeatGrantOut])
async def list_seat_grants(
    project_id: UUID, container: ContainerDep, user: CurrentUser
) -> list[SeatGrantOut]:
    """Who sits in which seat, and **who put them there** (FR-034)."""
    await _require_owned_project(container, user, project_id)
    grants = await container.projects.list_seat_grants(project_id)
    return [SeatGrantOut.model_validate(g) for g in grants]


# ── putting an agent on a project (system-only — the Patron action IS the system action) ──
async def _tell_the_workspace_if_it_woke(container, project_id: UUID, was_active: bool) -> None:
    """Announce SETUP→ACTIVE, which a seating may have just caused (§3.3).

    Asked *after* the seating rather than reported by it: activation is a property of the
    whole roster, so the only honest way to know it happened is to look at the project again.
    """
    if was_active:
        return
    after = await container.projects.get_project(project_id)
    if after is not None and str(after.status) == "active":
        await container.control_bus.publish(
            f"ws:{after.workspace_id}",
            "project.active",
            {"project_id": str(project_id)},
        )


@router.post("/projects/{project_id}/leader", response_model=SeatGrantOut, status_code=201)
async def seat_leader(
    project_id: UUID, body: SeatAgentIn, container: ContainerDep, user: CurrentUser
) -> SeatGrantOut:
    """Put an agent in this project's leader seat (FR-007l keeps the Leader)."""
    project = await _require_owned_project(container, user, project_id)
    was_active = str(project.status) == "active"
    grant = await container.projects.seat_leader(
        project_id, body.marius_id, granted_by_user_id=str(user.id)
    )
    await _tell_the_workspace_if_it_woke(container, project_id, was_active)
    return SeatGrantOut.model_validate(grant)


@router.post("/projects/{project_id}/members", response_model=SeatGrantOut, status_code=201)
async def add_member(
    project_id: UUID, body: SeatAgentIn, container: ContainerDep, user: CurrentUser
) -> SeatGrantOut:
    """Put an agent on this project. One call, and it names no role (FR-007l)."""
    project = await _require_owned_project(container, user, project_id)
    was_active = str(project.status) == "active"
    grant = await container.projects.add_member(
        project_id, body.marius_id, granted_by_user_id=str(user.id)
    )
    await _tell_the_workspace_if_it_woke(container, project_id, was_active)
    return SeatGrantOut.model_validate(grant)


@router.delete("/projects/{project_id}/members/{marius_id}", response_model=SeatGrantOut)
async def remove_member(
    project_id: UUID, marius_id: UUID, container: ContainerDep, user: CurrentUser
) -> SeatGrantOut:
    """Take an agent off this project. The Leader is not reachable from here."""
    await _require_owned_project(container, user, project_id)
    grant = await container.projects.remove_member(project_id, marius_id)
    return SeatGrantOut.model_validate(grant)


@router.get("/projects/{project_id}/agents", response_model=list[SeatOut])
async def list_agents(
    project_id: UUID, container: ContainerDep, user: CurrentUser
) -> list[SeatOut]:
    await _require_owned_project(container, user, project_id)
    seats = await container.projects.list_agents(project_id)
    return [
        SeatOut(
            marius_id=s.marius_id,
            name=s.name,
            role_key=s.role_key,
            liveness=s.liveness,
            is_primary=s.is_primary,
        )
        for s in seats
    ]


@router.get("/projects/{project_id}/thresholds", response_model=ThresholdsOut)
async def get_thresholds(
    project_id: UUID, container: ContainerDep, user: CurrentUser
) -> ThresholdsOut:
    """Effective timing thresholds: the system floor with this project's overrides on
    top (spec 001). A patron reading this sees the numbers actually in force, not the
    sparse override dict."""
    await _require_owned_project(container, user, project_id)
    resolved = await container.projects.get_thresholds(project_id)
    return ThresholdsOut.model_validate(resolved)


@router.put("/projects/{project_id}/thresholds", response_model=ThresholdsOut)
async def set_thresholds(
    project_id: UUID, body: ThresholdsIn, container: ContainerDep, user: CurrentUser
) -> ThresholdsOut:
    """Replace this project's overrides. Omitted fields fall back to the system floor;
    an empty body resets the project to it entirely."""
    await _require_owned_project(container, user, project_id)
    resolved = await container.projects.set_thresholds(
        project_id, body.model_dump(exclude_none=True)
    )
    return ThresholdsOut.model_validate(resolved)


@router.get("/projects/{project_id}/orchestration", response_model=OrchestrationOut)
async def get_orchestration(
    project_id: UUID, container: ContainerDep, user: CurrentUser
) -> OrchestrationOut:
    """The Leader's last look at this board and what it saw (spec 001 FR-052 → FR-055).

    A project that has never been swept comes back empty rather than 404 — "not looked at
    yet" is a real state of a young project, not a missing resource.
    """
    await _require_owned_project(container, user, project_id)
    async with container.uow_factory() as uow:  # type: ignore[operator]
        recent = await uow.orchestration_sweeps.list_recent(project_id, limit=1)
    if not recent:
        return OrchestrationOut()
    last = recent[0]
    swept_at = as_utc(last.swept_at)
    return OrchestrationOut(
        last_swept_at=swept_at,
        next_sweep_at=(
            swept_at + timedelta(seconds=last.next_interval_seconds)
            if swept_at is not None
            else None
        ),
        interval_seconds=last.next_interval_seconds,
        woke_leader=last.woke_leader,
        skipped_reason=last.skipped_reason,
        snags=[
            SnagOut(
                kind=str(s.kind),
                task_id=s.task_id,
                identifier=s.identifier,
                title=s.title,
                mark_hours=s.mark_hours,
                detail=s.detail,
            )
            for s in last.snags
        ],
    )


# ── project context, plan and phase (spec 001, contracts/user-surface.md §1–3) ──


@router.get("/projects/{project_id}/context", response_model=ProjectContextViewOut)
async def get_project_context(
    project_id: UUID, container: ContainerDep, user: CurrentUser
) -> ProjectContextViewOut:
    """The brief in force, plus one awaiting the patron if the Leader submitted a change.
    An edit never overwrites the approved version (FR-010)."""
    await _require_owned_project(container, user, project_id)
    approved, pending = await container.plans.get_context(project_id)
    return ProjectContextViewOut(
        approved=ProjectContextOut.model_validate(approved) if approved else None,
        pending=ProjectContextOut.model_validate(pending) if pending else None,
    )


@router.post("/projects/{project_id}/context/approve", response_model=ProjectContextOut)
async def approve_project_context(
    project_id: UUID, body: ContextDecisionIn, container: ContainerDep, user: CurrentUser
) -> ProjectContextOut:
    await _require_owned_project(container, user, project_id)
    context = await container.plans.approve_context(
        project_id, user_id=str(user.id), approve=body.approve, note=body.note
    )
    return ProjectContextOut.model_validate(context)


@router.get("/projects/{project_id}/plan", response_model=PlanOut)
async def get_project_plan(
    project_id: UUID, container: ContainerDep, user: CurrentUser
) -> PlanOut:
    await _require_owned_project(container, user, project_id)
    plan = await container.plans.get_plan(project_id)
    if plan is None:
        raise NotFound("plan_not_found")
    return PlanOut.model_validate(plan)


@router.post("/projects/{project_id}/plan/decision", response_model=PlanOut)
async def decide_project_plan(
    project_id: UUID, body: PlanDecisionIn, container: ContainerDep, user: CurrentUser
) -> PlanOut:
    """The patron's three choices at the plan gate (FR-013).

    There is deliberately no counterpart on the agent surface: the Leader that wrote the
    plan has no route to approve it (FR-014).
    """
    await _require_owned_project(container, user, project_id)
    plan = await container.plans.decide_plan(
        project_id,
        user_id=str(user.id),
        decision=_parse_decision(body.decision),
        note=body.note,
    )
    return PlanOut.model_validate(plan)


@router.post("/projects/{project_id}/phase", response_model=ProjectDetailOut)
async def change_project_phase(
    project_id: UUID, body: PhaseChangeIn, container: ContainerDep, user: CurrentUser
) -> ProjectDetailOut:
    """Only the patron moves a project between phases (FR-004). An agent may propose;
    the decision is never delegated, and no auto-accept switch reaches this route."""
    await _require_owned_project(container, user, project_id)
    project = await container.projects.change_phase(
        project_id,
        user_id=str(user.id),
        target_phase=_parse_phase(body.target_phase),
        reason=body.reason,
    )
    return await _detail(container, project)


def _parse_decision(value: str) -> PlanDecision:
    try:
        return PlanDecision(value)
    except ValueError as exc:
        raise BadRequest("unknown_plan_decision", decision=value) from exc


def _parse_phase(value: str) -> ProjectStatus:
    try:
        return ProjectStatus(value)
    except ValueError as exc:
        raise BadRequest("unknown_project_phase", phase=value) from exc
