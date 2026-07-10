"""Onboarding endpoints — the Patron ↔ Workspace Agent project-setup chat (#61).

Every route is scoped to the caller's workspace. The Workspace Agent asks a guided,
tick-select questionnaire (one question at a time); each ``start`` opens a FRESH session
and ``answer`` advances it until the agent emits a project + roster draft. ``finalize`` hands
the draft to ``ProjectService``, which creates a ``setup`` project with its roster. The active
brain is deterministic (see ``onboarding_brain.py``); a live agent runtime can drive the same
contract via the agent-facing callbacks in ``api/agent.py``.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from armarius.presentation.api.auth import CurrentUser
from armarius.presentation.deps import ContainerDep
from armarius.presentation.schemas import OnboardingAnswerIn, OnboardingOut

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


@router.post("/onboarding/{session_id}/answer", response_model=OnboardingOut)
async def answer_onboarding(
    session_id: UUID,
    body: OnboardingAnswerIn,
    container: ContainerDep,
    user: CurrentUser,
) -> OnboardingOut:
    """Answer the pending question; the agent asks the next one (or emits the final draft)."""
    await _owned_session(container, user, session_id)
    other = (body.other_text or "").strip()
    value = other or body.answer
    session = await container.onboarding.answer(session_id, value)
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
