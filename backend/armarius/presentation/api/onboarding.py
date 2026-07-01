"""Onboarding endpoints — the Patron ↔ Workspace Agent project-setup chat (Sprint 7 / Phase G).

Every route is scoped to the caller's workspace. The Workspace Agent runs a scripted
playbook (greet → propose a roster from the objective → confirm); ``finalize`` hands the
plan to ``ProjectService``, which creates a ``setup`` project with its roster. Because the
brain is deterministic (no real gateway in this stack), every call resolves synchronously
and returns the full session transcript.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from armarius.presentation.api.auth import CurrentUser
from armarius.presentation.deps import ContainerDep
from armarius.presentation.schemas import OnboardingMessageIn, OnboardingOut

router = APIRouter(prefix="/v1", tags=["onboarding"])


async def _require_owned_workspace(container, user, workspace_id: UUID):
    ws = await container.workspaces.get_workspace(workspace_id)
    if ws is None or ws.owner_user_id != str(user.id):
        raise LookupError("workspace not found")
    return ws


async def _owned_session(container, user, session_id: UUID):
    """Load an onboarding session and confirm its workspace belongs to the caller."""
    session = await container.onboarding.get(session_id)
    if session is None or session.workspace_id is None:
        raise LookupError("onboarding session not found")
    await _require_owned_workspace(container, user, session.workspace_id)
    return session


@router.post(
    "/workspaces/{workspace_id}/onboarding",
    response_model=OnboardingOut,
    status_code=201,
)
async def start_onboarding(
    workspace_id: UUID, container: ContainerDep, user: CurrentUser
) -> OnboardingOut:
    """Open a project-setup chat with the Workspace Agent (idempotent agent designation)."""
    await _require_owned_workspace(container, user, workspace_id)
    session = await container.onboarding.start(workspace_id)
    return OnboardingOut.model_validate(session)


@router.get(
    "/workspaces/{workspace_id}/onboarding/active",
    response_model=OnboardingOut,
)
async def get_active_onboarding(
    workspace_id: UUID, container: ContainerDep, user: CurrentUser
) -> OnboardingOut:
    """The workspace's live (open) onboarding chat, if any — 404 when none is open."""
    await _require_owned_workspace(container, user, workspace_id)
    session = await container.onboarding.active_for(workspace_id)
    if session is None:
        raise LookupError("no active onboarding session")
    return OnboardingOut.model_validate(session)


@router.get("/onboarding/{session_id}", response_model=OnboardingOut)
async def get_onboarding(
    session_id: UUID, container: ContainerDep, user: CurrentUser
) -> OnboardingOut:
    session = await _owned_session(container, user, session_id)
    return OnboardingOut.model_validate(session)


@router.post("/onboarding/{session_id}/messages", response_model=OnboardingOut)
async def post_onboarding_message(
    session_id: UUID,
    body: OnboardingMessageIn,
    container: ContainerDep,
    user: CurrentUser,
) -> OnboardingOut:
    await _owned_session(container, user, session_id)
    session = await container.onboarding.message(session_id, body.text)
    return OnboardingOut.model_validate(session)


@router.post("/onboarding/{session_id}/finalize", response_model=OnboardingOut)
async def finalize_onboarding(
    session_id: UUID, container: ContainerDep, user: CurrentUser
) -> OnboardingOut:
    """Lock the plan: create a ``setup`` project + roster from the agreed conversation."""
    await _owned_session(container, user, session_id)
    session = await container.onboarding.finalize(
        session_id, created_by_user_id=str(user.id)
    )
    return OnboardingOut.model_validate(session)


@router.post("/onboarding/{session_id}/abandon", response_model=OnboardingOut)
async def abandon_onboarding(
    session_id: UUID, container: ContainerDep, user: CurrentUser
) -> OnboardingOut:
    await _owned_session(container, user, session_id)
    session = await container.onboarding.abandon(session_id)
    return OnboardingOut.model_validate(session)
