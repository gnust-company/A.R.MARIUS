"""FastAPI application entrypoint and router wiring."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from armarius import __version__
from armarius.infrastructure.database.migrations import ensure_schema
from armarius.presentation.api import (
    agent,
    auth,
    commission,
    events,
    health,
    projects,
    tasks,
    trace,
    workspaces,
)
from armarius.presentation.container import build_container
from armarius.presentation.errors import install_error_handlers
from armarius.seed import maybe_seed
from armarius.shared.config import settings
from armarius.shared.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    logger.info("Armarius %s starting (env=%s)", __version__, settings.environment)
    await ensure_schema()
    app.state.container = build_container()
    # Provision the Shared Artifact Store (creates the MinIO bucket `armarius` if missing).
    await app.state.container.artifact_store.ensure_ready()
    # Demo seed is opt-in (ARMARIUS_SEED_DEMO=true). Off by default so real users
    # get their own empty personal workspace — never someone else's demo data.
    if settings.seed_demo:
        await maybe_seed(app.state.container)
    # Start the liveness watchdog — the background clock that decays silent agents (§10).
    app.state.container.liveness_watchdog.start()
    yield
    await app.state.container.liveness_watchdog.stop()
    logger.info("Armarius shutting down")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Armarius",
        version=__version__,
        summary="Provisioner for cross-team agent collaboration.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(workspaces.router)
    app.include_router(projects.router)
    app.include_router(commission.router)
    app.include_router(events.router)
    app.include_router(tasks.router)
    app.include_router(trace.router)
    app.include_router(agent.router)

    # Mount static files for skills, etc.
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app


app = create_app()
