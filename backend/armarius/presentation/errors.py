"""Maps domain/use-case exceptions to HTTP responses (keeps routers thin)."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from armarius.domain.entities.task import ArtifactRequiredError, TaskTransitionError


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

    @app.exception_handler(ValueError)
    async def _bad_request(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
