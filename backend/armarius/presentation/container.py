"""Composition root — wires infrastructure into application services (one place).

This is the only module allowed to know about both the application services and the
concrete infrastructure implementations.
"""

from __future__ import annotations

from dataclasses import dataclass

from armarius.application.ports.artifact_store import ArtifactStore
from armarius.application.ports.event_bus import EventBus
from armarius.application.use_cases.artifacts import ArtifactService
from armarius.application.use_cases.auth import AuthService
from armarius.application.use_cases.mariuses import MariusService
from armarius.application.use_cases.runs import RunQueryService
from armarius.application.use_cases.skills import SkillService
from armarius.application.use_cases.tasks import TaskService
from armarius.application.use_cases.threads import ThreadService
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.adapters.hermes_gateway import HermesGatewayAdapter
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus
from armarius.infrastructure.persistence.unit_of_work import make_uow
from armarius.infrastructure.security.jwt import JWTService
from armarius.infrastructure.security.password import PasswordService
from armarius.infrastructure.store.local_store import LocalArtifactStore
from armarius.infrastructure.store.minio_store import MinioArtifactStore
from armarius.shared.config import settings


@dataclass
class Container:
    event_bus: EventBus
    registry: InMemoryAdapterRegistry
    wake_engine: WakeEngine
    workspaces: WorkspaceService
    mariuses: MariusService
    tasks: TaskService
    threads: ThreadService
    artifacts: ArtifactService
    artifact_store: ArtifactStore
    runs: RunQueryService
    auth: AuthService
    skills: SkillService
    jwt_service: JWTService
    uow_factory: object


def build_container() -> Container:
    uow_factory = make_uow

    event_bus = InMemoryEventBus()

    registry = InMemoryAdapterRegistry()
    registry.register(HermesGatewayAdapter())
    registry.register(EchoAdapter())

    store: ArtifactStore
    if settings.artifact_store_backend == "minio":
        store = MinioArtifactStore(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.minio_bucket,
            secure=settings.minio_secure,
        )
    else:
        store = LocalArtifactStore(settings.artifact_store_path)

    jwt_service = JWTService()
    password_service = PasswordService()

    wake_engine = WakeEngine(
        uow_factory,
        registry,
        event_bus,
        run_timeout_seconds=settings.run_timeout_seconds,
        max_continuation_attempts=settings.wake_max_continuation_attempts,
    )

    skills = SkillService(uow_factory)
    workspaces = WorkspaceService(uow_factory, skills)

    return Container(
        event_bus=event_bus,
        registry=registry,
        wake_engine=wake_engine,
        workspaces=workspaces,
        mariuses=MariusService(uow_factory),
        tasks=TaskService(uow_factory, wake_engine),
        threads=ThreadService(uow_factory, wake_engine),
        artifacts=ArtifactService(uow_factory, store),
        artifact_store=store,
        runs=RunQueryService(uow_factory),
        auth=AuthService(uow_factory, workspaces, jwt_service, password_service),
        skills=skills,
        jwt_service=jwt_service,
        uow_factory=uow_factory,
    )
