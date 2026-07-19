"""Project, roster and seat-grant endpoints (human/Patron surface, API_CONTRACT §3).

These wire the roster-driven `ProjectService` (create-with-seat-plan, system-only grants,
SETUP→ACTIVE activation) to HTTP. Every route is scoped to the caller's workspace —
touching a project in someone else's workspace is a 404.
"""

from __future__ import annotations

import re
from uuid import UUID

from fastapi import APIRouter

from armarius.application.use_cases.projects import RoleSpec
from armarius.domain.entities.project import Project
from armarius.presentation.api.auth import CurrentUser
from armarius.presentation.deps import ContainerDep
from armarius.presentation.schemas import (
    AddRoleIn,
    CreateProjectPlanIn,
    GrantSeatIn,
    ProjectDetailOut,
    ProjectOut,
    RoleOut,
    RosterRoleOut,
    SeatGrantOut,
    SeatOut,
    UpdateProjectIn,
    UpdateRoleIn,
)

router = APIRouter(prefix="/v1", tags=["projects"])


def _slug(value: str) -> str:
    # Cap at RoleModel.key's column width (String(120)) — a long title must not overflow
    # the key column on Postgres (SQLite silently ignores VARCHAR length; Postgres errors).
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:120].strip("-")
    return slug or "role"


async def _require_owned_workspace(container, user, workspace_id: UUID):
    ws = await container.workspaces.get_workspace(workspace_id)
    if ws is None or ws.owner_user_id != str(user.id):
        raise LookupError("workspace not found")
    return ws


async def _require_owned_project(container, user, project_id: UUID) -> Project:
    project = await container.projects.get_project(project_id)
    if project is None:
        raise LookupError("project not found")
    ws = await container.workspaces.get_workspace(project.workspace_id)
    if ws is None or ws.owner_user_id != str(user.id):
        raise LookupError("project not found")  # cross-workspace → 404
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

    specs = [
        RoleSpec(
            key="leader",
            title="Project Leader",
            seats=1,
            is_leader=True,
            description=body.leader.description,
        )
    ]
    used_keys = {"leader"}
    worker_keys: list[str] = []
    for role in body.roles:
        key = _slug(role.title)
        base_key = key
        i = 2
        while key in used_keys:
            key = f"{base_key}-{i}"
            i += 1
        used_keys.add(key)
        worker_keys.append(key)
        specs.append(
            RoleSpec(
                key=key,
                title=role.title,
                seats=role.seats,
                description=role.description,
                skill_ids=[str(x) for x in role.skill_ids],
            )
        )

    project = await container.projects.create_project(
        workspace_id,
        body.name,
        roles=specs,
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

    # Pre-seat any agents the plan named (system-only grants → may activate the project).
    if body.leader.marius_id is not None:
        await container.projects.grant_seat(
            project.id, "leader", body.leader.marius_id, system=True
        )
    for role, key in zip(body.roles, worker_keys, strict=True):
        for marius_id in role.marius_ids:
            if marius_id is not None:
                await container.projects.grant_seat(
                    project.id, key, marius_id, system=True
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


@router.post("/projects/{project_id}/roles", response_model=RoleOut, status_code=201)
async def add_role(
    project_id: UUID, body: AddRoleIn, container: ContainerDep, user: CurrentUser
) -> RoleOut:
    await _require_owned_project(container, user, project_id)
    role = await container.projects.add_role(
        project_id,
        RoleSpec(
            key=_slug(body.title),
            title=body.title,
            seats=body.seats,
            is_leader=body.is_leader,
            description=body.description,
            skill_ids=[str(x) for x in body.skill_ids],
        ),
    )
    return RoleOut.model_validate(role)


@router.patch("/projects/{project_id}/roles/{role_key}", response_model=RoleOut)
async def update_role(
    project_id: UUID,
    role_key: str,
    body: UpdateRoleIn,
    container: ContainerDep,
    user: CurrentUser,
) -> RoleOut:
    await _require_owned_project(container, user, project_id)
    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    role = await container.projects.update_role_by_key(project_id, role_key, **changes)
    return RoleOut.model_validate(role)


@router.delete("/projects/{project_id}/roles/{role_key}", status_code=204)
async def remove_role(
    project_id: UUID, role_key: str, container: ContainerDep, user: CurrentUser
) -> None:
    await _require_owned_project(container, user, project_id)
    await container.projects.remove_role_by_key(project_id, role_key)


# ── seat grants (system-only — the Patron action IS the system action) ─────────
@router.post("/projects/{project_id}/grant", response_model=SeatGrantOut, status_code=201)
async def grant_seat(
    project_id: UUID, body: GrantSeatIn, container: ContainerDep, user: CurrentUser
) -> SeatGrantOut:
    project = await _require_owned_project(container, user, project_id)
    was_active = str(project.status) == "active"
    grant = await container.projects.grant_seat(
        project_id, body.role_key, body.marius_id, system=True
    )
    if not was_active:
        after = await container.projects.get_project(project_id)
        if after is not None and str(after.status) == "active":
            # SETUP→ACTIVE flips once, when every seat is granted and online (§3.3).
            await container.control_bus.publish(
                f"ws:{after.workspace_id}",
                "project.active",
                {"project_id": str(project_id)},
            )
    return SeatGrantOut.model_validate(grant)


@router.delete("/projects/{project_id}/grant", response_model=SeatGrantOut)
async def revoke_seat(
    project_id: UUID, body: GrantSeatIn, container: ContainerDep, user: CurrentUser
) -> SeatGrantOut:
    await _require_owned_project(container, user, project_id)
    grant = await container.projects.revoke_seat_by_role(
        project_id, body.marius_id, body.role_key, system=True
    )
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
