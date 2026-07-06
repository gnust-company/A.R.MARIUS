"""Workspace, Project and Marius (directory) endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from armarius.application.use_cases.onboarding import build_invite_prompt
from armarius.presentation.api.agent import effective_skills
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
    UpdateWorkspaceIn,
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


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceOut)
async def rename_workspace(
    workspace_id: UUID,
    body: UpdateWorkspaceIn,
    container: ContainerDep,
    user: CurrentUser,
) -> WorkspaceOut:
    await _require_owned_workspace(container, user, workspace_id)
    ws = await container.workspaces.rename_workspace(workspace_id, body.name)
    return WorkspaceOut.model_validate(ws)


@router.delete("/workspaces/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: UUID, container: ContainerDep, user: CurrentUser
) -> None:
    await _require_owned_workspace(container, user, workspace_id)
    await container.workspaces.delete_workspace(workspace_id, owner_user_id=str(user.id))


# Project + roster + grant routes live in `presentation/api/projects.py`
# (the roster-driven ProjectService surface, API_CONTRACT §3).


async def _require_owned_workspace(container, user, workspace_id: UUID):
    ws = await container.workspaces.get_workspace(workspace_id)
    if ws is None or ws.owner_user_id != str(user.id):
        raise LookupError("workspace not found")
    return ws


async def _build_invite(container: ContainerDep, marius, workspace_id: UUID) -> str:
    """Assemble the invitation prompt for a Marius (workspace connection + skills).

    Connection-only by design — no project or task loop here (issue #43). Carries the
    **enrollment_code** (enroll-and-wait) until a token has been minted; after approval
    the prompt would carry the live token instead.
    """
    ws = await container.workspaces.get_workspace(workspace_id)
    # effective_skills (not skills.resolve) so the host's seat-granted onboarder
    # playbook shows up in STEP 3 — it is never in skill_ids (#32).
    linked = await effective_skills(container, marius)
    return build_invite_prompt(
        marius,
        settings.public_api_url,
        workspace_name=ws.name if ws else "the workspace",
        skills=linked,
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
    if body.is_workspace_agent:
        # Seat the newcomer as host right away (#32) — an existing host is demoted to
        # a plain agent. Done before the invite is built so the prompt shows the role.
        await container.workspace_agent.designate(workspace_id, marius.id)
        marius = await container.mariuses.get(marius.id) or marius
    # Inviting an agent is a connection step only (#43): it names no project and must
    # not conjure one. The patron commissions the first project explicitly (#49).
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


@router.post(
    "/workspaces/{workspace_id}/mariuses/{marius_id}/designate",
    response_model=MariusOut,
)
async def designate_workspace_agent(
    workspace_id: UUID, marius_id: UUID, container: ContainerDep, user: CurrentUser
) -> MariusOut:
    """Hand the Workspace Agent seat to this Marius (#32). A sitting host is demoted
    to a plain agent — kept, not revoked. Idempotent for the current host."""
    await _require_owned_workspace(container, user, workspace_id)
    marius = await container.workspace_agent.designate(workspace_id, marius_id)
    await container.control_bus.publish(
        f"ws:{workspace_id}",
        "workspace_agent.designated",
        {"marius_id": str(marius_id)},
    )
    return MariusOut.model_validate(marius)


@router.delete(
    "/workspaces/{workspace_id}/mariuses/{marius_id}", status_code=204
)
async def delete_marius(
    workspace_id: UUID, marius_id: UUID, container: ContainerDep, user: CurrentUser
) -> None:
    """Remove an agent from the directory. The Workspace Agent can be removed too —
    doing so just vacates its host seat (#50)."""
    await _require_owned_workspace(container, user, workspace_id)
    marius = await container.mariuses.get(marius_id)
    if marius is None or marius.workspace_id != workspace_id:
        raise LookupError("marius not found")
    await container.mariuses.delete(marius_id)
    await container.control_bus.publish(
        f"ws:{workspace_id}",
        "marius.status_changed",
        {"marius_id": str(marius_id), "status": "deleted"},
    )


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


@router.delete(
    "/workspaces/{workspace_id}/skills/{skill_id}", status_code=204
)
async def delete_skill(
    workspace_id: UUID, skill_id: UUID, container: ContainerDep, user: CurrentUser
) -> None:
    """Delete a workspace skill (built-in skills are protected)."""
    await _require_owned_workspace(container, user, workspace_id)
    skill = await container.skills.get_skill(skill_id)
    if skill is None or skill.workspace_id != workspace_id:
        raise LookupError("skill not found")
    await container.skills.delete_skill(skill_id)
