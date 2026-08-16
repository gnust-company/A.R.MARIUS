"""Artifact use cases — publish an output into the Shared Artifact Store (§3.4)."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from armarius.application.ports.artifact_store import ArtifactStore
from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.artifact import Artifact
from armarius.infrastructure.events.topic_bus import TopicEventBus, project_topic
from armarius.shared.clock import utcnow

EVENT_TASK_ARTIFACT = "task.artifact_added"


class ArtifactService:
    def __init__(
        self,
        uow_factory: UowFactory,
        store: ArtifactStore,
        *,
        control_bus: TopicEventBus | None = None,
    ) -> None:
        self._uow = uow_factory
        self._store = store
        # The board card draws a clip when a task has any artifact, and this service had
        # no way to say one arrived (T177). It matters most on the path where nobody is
        # looking at the screen: a worker publishes through the agent API, so the patron
        # watching the board never touched anything that could have triggered a re-read.
        self._bus = control_bus

    async def publish(
        self,
        *,
        task_id: UUID,
        name: str,
        kind: str = "file",
        content: bytes | None = None,
        uri: str | None = None,
        marius_id: UUID | None = None,
    ) -> Artifact:
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise LookupError("task not found")
            project_id = task.project_id
            assert project_id is not None

            if kind == "link":
                if not uri:
                    raise ValueError("link artifacts require a uri")
                artifact = Artifact(
                    project_id=project_id,
                    task_id=task_id,
                    marius_id=marius_id,
                    name=name,
                    kind=kind,
                    uri=uri,
                    created_at=utcnow(),
                )
            else:
                if content is None:
                    raise ValueError(f"{kind} artifacts require content")
                stored = await self._store.save_bytes(project_id, name, content)
                artifact = Artifact(
                    project_id=project_id,
                    task_id=task_id,
                    marius_id=marius_id,
                    name=name,
                    kind=kind,
                    uri=stored.uri,
                    content_sha256=stored.sha256,
                    size_bytes=stored.size_bytes,
                    created_at=utcnow(),
                )
            created = await uow.artifacts.add(artifact)
            await uow.commit()

        # Identifiers only — the artifact's name is content, and content stays off the
        # channel (contract `push-events` principle 4).
        if self._bus is not None:
            await self._bus.publish(
                project_topic(project_id),
                EVENT_TASK_ARTIFACT,
                {"task_id": str(task_id), "artifact_id": str(created.id)},
            )
        return created

    async def list_by_task(self, task_id: UUID) -> Sequence[Artifact]:
        async with self._uow() as uow:
            return await uow.artifacts.list_by_task(task_id)
