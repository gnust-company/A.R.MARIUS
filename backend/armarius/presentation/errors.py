"""Maps domain/use-case exceptions to HTTP responses (keeps routers thin)."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from armarius.application.use_cases.commission import (
    CommissionError as CommissionOpError,
)
from armarius.application.use_cases.enrollment import GatewayUnreachable
from armarius.application.use_cases.onboarding_session import (
    OnboardingBusy,
    WorkspaceAgentUnavailable,
)
from armarius.application.use_cases.projects import (
    DuplicateProjectKey,
    DuplicateRoleKey,
    SystemOnlyOperation,
)
from armarius.domain.entities.commission import (
    CommissionError as CommissionStateError,
)
from armarius.domain.entities.leader_chat import LeaderChatError
from armarius.domain.entities.marius import InviteError
from armarius.domain.entities.onboarding import OnboardingError
from armarius.domain.entities.seat_grant import SeatGrantError
from armarius.domain.entities.task import ArtifactRequiredError, TaskTransitionError
from armarius.domain.services.project_key import InvalidProjectKey
from armarius.domain.services.project_rules import InvalidProjectPlan


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(LookupError)
    async def _not_found(_: Request, exc: LookupError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc) or "not found"})

    @app.exception_handler(TaskTransitionError)
    async def _bad_transition(_: Request, exc: TaskTransitionError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ArtifactRequiredError)
    async def _artifact_required(_: Request, exc: ArtifactRequiredError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(InvalidProjectPlan)
    async def _invalid_plan(_: Request, exc: InvalidProjectPlan) -> JSONResponse:
        # Hard roster composition rule (API_CONTRACT §3.1) — unprocessable entity.
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(SystemOnlyOperation)
    async def _system_only(_: Request, exc: SystemOnlyOperation) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(DuplicateRoleKey)
    async def _duplicate_role_key(_: Request, exc: DuplicateRoleKey) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(DuplicateProjectKey)
    async def _duplicate_project_key(_: Request, exc: DuplicateProjectKey) -> JSONResponse:
        # Project KEY already used in this workspace (JIRA-style uniqueness) — conflict.
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(InvalidProjectKey)
    async def _invalid_project_key(_: Request, exc: InvalidProjectKey) -> JSONResponse:
        # KEY malformed (must be 2–10 uppercase chars, start with a letter) — unprocessable.
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(CommissionOpError)
    async def _commission_op(_: Request, exc: CommissionOpError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(CommissionStateError)
    async def _commission_state(_: Request, exc: CommissionStateError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(LeaderChatError)
    async def _leader_chat_conflict(_: Request, exc: LeaderChatError) -> JSONResponse:
        # No Leader seated / Leader offline / turn already running — all 409 (the FE
        # surfaces the detail verbatim; offline also disables the box up-front, #82).
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(SeatGrantError)
    async def _seat_grant_conflict(_: Request, exc: SeatGrantError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(InviteError)
    async def _invite_conflict(_: Request, exc: InviteError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(OnboardingError)
    async def _onboarding_conflict(_: Request, exc: OnboardingError) -> JSONResponse:
        # Illegal session transition (message/finalize/abandon on a non-open chat) — conflict.
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(OnboardingBusy)
    async def _onboarding_busy(_: Request, exc: OnboardingBusy) -> JSONResponse:
        # A live WA posted a new question while the previous one is unanswered (one-at-a-time).
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(WorkspaceAgentUnavailable)
    async def _wa_unavailable(_: Request, exc: WorkspaceAgentUnavailable) -> JSONResponse:
        # The Workspace Agent is not online (or a wake failed) — onboarding cannot proceed. No
        # fallback: tell the user to enroll/wake the agent (409, both start + mid-interview).
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(GatewayUnreachable)
    async def _gateway_unreachable(_: Request, exc: GatewayUnreachable) -> JSONResponse:
        # The operator-supplied gateway failed its reachability probe (issue #63) —
        # unprocessable entity: the request was well-formed but the target is not live.
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def _bad_request(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
