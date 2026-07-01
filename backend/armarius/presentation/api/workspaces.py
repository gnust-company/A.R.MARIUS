"""Workspace, Project and Marius (directory) endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from armarius.application.use_cases.onboarding import build_invite_prompt
from armarius.presentation.api.auth import CurrentUser
from armarius.presentation.deps import ContainerDep
from armarius.presentation.schemas import (
    CreateLabelIn,
    CreateWorkspaceIn,
    ImportSkillIn,
    LabelOut,
    ManualSkillIn,
    MariusCreatedOut,
    MariusOut,
    RegisterMariusIn,
    SkillOut,
    UpdateMariusIn,
    UpdateSkillIn,
    WorkspaceOut,
)
from armarius.shared.config import settings

router = APIRouter(prefix="/v1", tags=["workspaces"])


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201)
async def create_workspace(
    body: CreateWorkspaceIn, container: ContainerDep, user: CurrentUser
) -> WorkspaceOut:
    ws = await container.workspaces.create_workspace(body.name, owner_user_id=str(user.id))
    return WorkspaceOut.model_validate(ws)


@router.get("/workspaces", response_model=list[WorkspaceOut])
async def list_workspaces(container: ContainerDep, user: CurrentUser) -> list[WorkspaceOut]:
    """List workspaces OWNED by the current user (multi-tenant scoped)."""
    items = await container.workspaces.list_workspaces(owner_user_id=str(user.id))
    return [WorkspaceOut.model_validate(w) for w in items]


# Project + roster + grant routes live in `presentation/api/projects.py`
# (the roster-driven ProjectService surface, API_CONTRACT §3).


async def _require_owned_workspace(container, user, workspace_id: UUID):
    ws = await container.workspaces.get_workspace(workspace_id)
    if ws is None or ws.owner_user_id != str(user.id):
        raise LookupError("workspace not found")
    return ws


async def _build_invite(container: ContainerDep, marius, workspace_id: UUID) -> str:
    """Assemble the invitation prompt for a Marius (workspace + project + skills).

    Carries the **enrollment_code** (enroll-and-wait) until a token has been minted;
    after approval the prompt would carry the live token instead.
    """
    ws = await container.workspaces.get_workspace(workspace_id)
    projects = await container.workspaces.list_projects(workspace_id)
    linked = await container.skills.resolve(marius.skill_ids)
    return build_invite_prompt(
        marius,
        settings.public_api_url,
        workspace_name=ws.name if ws else "the workspace",
        project_name=projects[0].name if projects else "the project",
        skills=list(linked),
        enrollment_code=marius.enrollment_code if marius.agent_token is None else None,
    )


@router.post(
    "/workspaces/{workspace_id}/mariuses",
    response_model=MariusCreatedOut,
    status_code=201,
)
async def invite_marius(
    workspace_id: UUID,
    body: RegisterMariusIn,
    container: ContainerDep,
    user: CurrentUser,
) -> MariusCreatedOut:
    """Invite a Marius — enroll-and-wait (API_CONTRACT §4.1). Returns an enrollment_code
    and a copyable prompt; the agent_token is **not** minted until approval."""
    await _require_owned_workspace(container, user, workspace_id)
    marius = await container.enrollment.invite(
        workspace_id,
        body.name,
        body.role,
        skills=body.skills,
        skill_ids=body.skill_ids,
        adapter_type=body.adapter_type,
        adapter_config=body.adapter_config,
        owner_user_id=str(user.id),
    )
    # Ensure the workspace has a default project so the invitation names a real
    # project (the board also does this lazily on first load).
    await container.workspaces.ensure_default_project(workspace_id)
    invite = await _build_invite(container, marius, workspace_id)
    await container.control_bus.publish(
        f"ws:{workspace_id}",
        "marius.status_changed",
        {"marius_id": str(marius.id), "status": "invited"},
    )
    return MariusCreatedOut.model_validate(marius).model_copy(update={"invite": invite})


@router.post(
    "/workspaces/{workspace_id}/mariuses/{marius_id}/approve",
    response_model=MariusCreatedOut,
)
async def approve_marius(
    workspace_id: UUID,
    marius_id: UUID,
    container: ContainerDep,
    user: CurrentUser,
) -> MariusCreatedOut:
    """Approve a pending enrollment → mint the agent_token once and complete any held
    `/agent/enroll` call (API_CONTRACT §4.1)."""
    await _require_owned_workspace(container, user, workspace_id)
    marius = await container.enrollment.approve(marius_id, workspace_id=workspace_id)
    await container.control_bus.publish(
        f"ws:{workspace_id}",
        "marius.status_changed",
        {"marius_id": str(marius.id), "status": "approved"},
    )
    return MariusCreatedOut.model_validate(marius)


@router.get("/workspaces/{workspace_id}/mariuses", response_model=list[MariusOut])
async def list_directory(
    workspace_id: UUID, container: ContainerDep, user: CurrentUser
) -> list[MariusOut]:
    items = await container.mariuses.list_directory(workspace_id)
    return [MariusOut.model_validate(m) for m in items]


# ---------------------------------------------------------------------- labels
@router.get("/workspaces/{workspace_id}/labels", response_model=list[LabelOut])
async def list_labels(
    workspace_id: UUID, container: ContainerDep, user: CurrentUser
) -> list[LabelOut]:
    await _require_owned_workspace(container, user, workspace_id)
    items = await container.labels.list_labels(workspace_id)
    return [LabelOut.model_validate(label) for label in items]


@router.post(
    "/workspaces/{workspace_id}/labels", response_model=LabelOut, status_code=201
)
async def create_label(
    workspace_id: UUID,
    body: CreateLabelIn,
    container: ContainerDep,
    user: CurrentUser,
) -> LabelOut:
    await _require_owned_workspace(container, user, workspace_id)
    label = await container.labels.create(workspace_id, body.name, body.color)
    return LabelOut.model_validate(label)


@router.patch(
    "/workspaces/{workspace_id}/mariuses/{marius_id}",
    response_model=MariusCreatedOut,
)
async def update_marius(
    workspace_id: UUID,
    marius_id: UUID,
    body: UpdateMariusIn,
    container: ContainerDep,
    user: CurrentUser,
) -> MariusCreatedOut:
    marius = await container.mariuses.update(
        marius_id,
        name=body.name,
        role=body.role,
        skills=body.skills,
        skill_ids=body.skill_ids,
        adapter_type=body.adapter_type,
        adapter_config=body.adapter_config,
    )
    invite = await _build_invite(container, marius, workspace_id)
    return MariusCreatedOut.model_validate(marius).model_copy(update={"invite": invite})


# ---------------------------------------------------------------------- skills
@router.get("/workspaces/{workspace_id}/skills", response_model=list[SkillOut])
async def list_skills(
    workspace_id: UUID, container: ContainerDep, user: CurrentUser
) -> list[SkillOut]:
    items = await container.skills.list_skills(workspace_id)
    return [SkillOut.model_validate(s) for s in items]


@router.get(
    "/workspaces/{workspace_id}/skills/{skill_id}", response_model=SkillOut
)
async def get_skill(
    workspace_id: UUID, skill_id: UUID, container: ContainerDep, user: CurrentUser
) -> SkillOut:
    skill = await container.skills.get_skill(skill_id)
    if skill is None:
        raise LookupError("skill not found")
    return SkillOut.model_validate(skill)


@router.post(
    "/workspaces/{workspace_id}/skills/manual",
    response_model=SkillOut,
    status_code=201,
)
async def create_manual_skill(
    workspace_id: UUID, body: ManualSkillIn, container: ContainerDep, user: CurrentUser
) -> SkillOut:
    skill = await container.skills.create_manual(
        workspace_id=workspace_id, name=body.name, description=body.description
    )
    return SkillOut.model_validate(skill)


@router.post(
    "/workspaces/{workspace_id}/skills/import",
    response_model=SkillOut,
    status_code=201,
)
async def import_skill(
    workspace_id: UUID, body: ImportSkillIn, container: ContainerDep, user: CurrentUser
) -> SkillOut:
    try:
        skill = await container.skills.import_from_url(
            workspace_id=workspace_id, url=body.source_url
        )
    except ValueError as e:
        raise LookupError(str(e)) from e
    return SkillOut.model_validate(skill)


@router.put(
    "/workspaces/{workspace_id}/skills/{skill_id}", response_model=SkillOut
)
async def update_skill(
    workspace_id: UUID,
    skill_id: UUID,
    body: UpdateSkillIn,
    container: ContainerDep,
    user: CurrentUser,
) -> SkillOut:
    try:
        skill = await container.skills.update_files(skill_id, body.files)
    except LookupError:
        raise
    return SkillOut.model_validate(skill)
