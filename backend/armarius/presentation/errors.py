"""Maps domain/use-case exceptions to HTTP responses (keeps routers thin)."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from armarius.application.use_cases.commission import (
    CommissionError as CommissionOpError,
)
from armarius.application.use_cases.enrollment import EnrollmentError
from armarius.application.use_cases.projects import DuplicateRoleKey, SystemOnlyOperation
from armarius.domain.entities.commission import (
    CommissionError as CommissionStateError,
)
from armarius.domain.entities.marius import InviteError
from armarius.domain.entities.onboarding import OnboardingError
from armarius.domain.entities.seat_grant import SeatGrantError
from armarius.domain.entities.task import ArtifactRequiredError, TaskTransitionError
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

    @app.exception_handler(CommissionOpError)
    async def _commission_op(_: Request, exc: CommissionOpError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(CommissionStateError)
    async def _commission_state(_: Request, exc: CommissionStateError) -> JSONResponse:
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

    @app.exception_handler(EnrollmentError)
    async def _enrollment_bad(_: Request, exc: EnrollmentError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def _bad_request(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
