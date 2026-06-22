"""Workspace, Project and Marius (directory) endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from armarius.application.use_cases.onboarding import build_invite_prompt
from armarius.presentation.deps import ContainerDep
from armarius.presentation.schemas import (
    CreateProjectIn,
    CreateWorkspaceIn,
    MariusCreatedOut,
    MariusOut,
    ProjectOut,
    RegisterMariusIn,
    WorkspaceOut,
)
from armarius.shared.config import settings

router = APIRouter(prefix="/v1", tags=["workspaces"])


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201)
async def create_workspace(body: CreateWorkspaceIn, container: ContainerDep) -> WorkspaceOut:
    ws = await container.workspaces.create_workspace(body.name)
    return WorkspaceOut.model_validate(ws)


@router.get("/workspaces", response_model=list[WorkspaceOut])
async def list_workspaces(container: ContainerDep) -> list[WorkspaceOut]:
    items = await container.workspaces.list_workspaces()
    return [WorkspaceOut.model_validate(w) for w in items]


@router.post(
    "/workspaces/{workspace_id}/projects", response_model=ProjectOut, status_code=201
)
async def create_project(
    workspace_id: UUID, body: CreateProjectIn, container: ContainerDep
) -> ProjectOut:
    project = await container.workspaces.create_project(
        workspace_id, body.name, body.description
    )
    return ProjectOut.model_validate(project)


@router.get("/workspaces/{workspace_id}/projects", response_model=list[ProjectOut])
async def list_projects(workspace_id: UUID, container: ContainerDep) -> list[ProjectOut]:
    items = await container.workspaces.list_projects(workspace_id)
    return [ProjectOut.model_validate(p) for p in items]


@router.post(
    "/workspaces/{workspace_id}/mariuses",
    response_model=MariusCreatedOut,
    status_code=201,
)
async def register_marius(
    workspace_id: UUID, body: RegisterMariusIn, container: ContainerDep
) -> MariusCreatedOut:
    marius = await container.mariuses.register(
        workspace_id=workspace_id,
        name=body.name,
        role=body.role,
        skills=body.skills,
        adapter_type=body.adapter_type,
        adapter_config=body.adapter_config,
        owner_user_id=body.owner_user_id,
    )
    invite = build_invite_prompt(marius, settings.public_api_url)
    return MariusCreatedOut.model_validate(marius).model_copy(update={"invite": invite})


@router.get("/workspaces/{workspace_id}/mariuses", response_model=list[MariusOut])
async def list_directory(workspace_id: UUID, container: ContainerDep) -> list[MariusOut]:
    items = await container.mariuses.list_directory(workspace_id)
    return [MariusOut.model_validate(m) for m in items]
