"""Composition root — wires infrastructure into application services (one place).

This is the only module allowed to know about both the application services and the
concrete infrastructure implementations.
"""

from __future__ import annotations

from dataclasses import dataclass

from armarius.application.ports.event_bus import EventBus
from armarius.application.use_cases.artifacts import ArtifactService
from armarius.application.use_cases.mariuses import MariusService
from armarius.application.use_cases.runs import RunQueryService
from armarius.application.use_cases.tasks import TaskService
from armarius.application.use_cases.threads import ThreadService
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.application.use_cases.workspaces import WorkspaceService
from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.adapters.hermes_gateway import HermesGatewayAdapter
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus
from armarius.infrastructure.persistence.unit_of_work import make_uow
from armarius.infrastructure.store.local_store import LocalArtifactStore
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
    runs: RunQueryService


def build_container() -> Container:
    uow_factory = make_uow

    event_bus = InMemoryEventBus()

    registry = InMemoryAdapterRegistry()
    registry.register(HermesGatewayAdapter())
    registry.register(EchoAdapter())

    store = LocalArtifactStore(settings.artifact_store_path)

    wake_engine = WakeEngine(
        uow_factory,
        registry,
        event_bus,
        run_timeout_seconds=settings.run_timeout_seconds,
        max_continuation_attempts=settings.wake_max_continuation_attempts,
    )

    return Container(
        event_bus=event_bus,
        registry=registry,
        wake_engine=wake_engine,
        workspaces=WorkspaceService(uow_factory),
        mariuses=MariusService(uow_factory),
        tasks=TaskService(uow_factory, wake_engine),
        threads=ThreadService(uow_factory, wake_engine),
        artifacts=ArtifactService(uow_factory, store),
        runs=RunQueryService(uow_factory),
    )
