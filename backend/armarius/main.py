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
    daemon,
    events,
    health,
    inbox,
    leader_chat,
    onboarding,
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
    # Start the reaper for work a machine took and never got going (FR-056a). It has to
    # be a clock of its own: each agent is bound to one place, so a machine that goes
    # dark takes its own work down with it and no second machine will ever come asking
    # on that task's behalf.
    app.state.container.daemon_claims.start_sweep()
    # Start the orchestration loop — sweeps each project's board on its own rhythm and
    # wakes the Leader only when the sweep found something (spec 001 FR-052 → FR-055).
    app.state.container.orchestrator.start()
    # Rebuild every open task's drive **before** the safety net starts sweeping (FR-068).
    # A drive is a claim about the future, and the process that made the last claims is
    # gone: a run it was streaming is now a run nobody is reading. Rebuilding first is what
    # separates "the net survived the restart" from "the net raised an alarm on every task
    # in the database one second after boot".
    rebuilt = await app.state.container.stall_watchdog.rebuild_drives()
    logger.info("rebuilt push reasons for %d open task(s)", rebuilt)
    # Start the safety net — the loop that notices a task nobody is going to touch again
    # (spec 001 FR-056 → FR-069).
    app.state.container.stall_watchdog.start()
    # Start the clock that forgets a run's log once it is past its keeping (FR-050). Its own
    # loop and its own setting: the working directory on a machine is cleared for the machine's
    # reasons, and this is the record people read months later to answer what an agent did.
    app.state.container.trace_retention.start()
    yield
    await app.state.container.trace_retention.stop()
    await app.state.container.stall_watchdog.stop()
    await app.state.container.orchestrator.stop()
    await app.state.container.daemon_claims.stop_sweep()
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
    app.include_router(leader_chat.router)
    app.include_router(onboarding.router)
    app.include_router(events.router)
    app.include_router(inbox.router)
    app.include_router(tasks.router)
    app.include_router(trace.router)
    app.include_router(agent.router)
    app.include_router(daemon.router)
    app.include_router(daemon.people_router)

    # Mount static files for skills, etc.
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app


app = create_app()
