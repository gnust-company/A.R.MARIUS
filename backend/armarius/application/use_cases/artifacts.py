"""Artifact use cases — publish an output into the Shared Artifact Store (§3.4)."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from armarius.application.ports.artifact_store import ArtifactStore
from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.artifact import Artifact
from armarius.infrastructure.events.topic_bus import TopicEventBus, project_topic
from armarius.shared.clock import utcnow
from armarius.shared.errors import ArtifactStoreUnreliable, BadRequest, NotFound

EVENT_TASK_ARTIFACT = "task.artifact_added"


@dataclass(frozen=True)
class PublishOutcome:
    """What one publish call landed on (FR-020c).

    ``created`` is the whole answer to *was this a retry*: the same bytes under the same
    name on the same task are the artifact that is already there, not a new one.
    ``version`` counts how many times this name has changed content — same name with
    different bytes is a new version of the one artifact the agent means.
    """

    artifact: Artifact
    created: bool
    version: int


class ArtifactService:
    def __init__(
        self,
        uow_factory: UowFactory,
        store: ArtifactStore,
        *,
        control_bus: TopicEventBus | None = None,
        drive_refresh: Callable[[UUID], Awaitable[None]] | None = None,
    ) -> None:
        self._uow = uow_factory
        self._store = store
        # The board card draws a clip when a task has any artifact, and this service had
        # no way to say one arrived (T177). It matters most on the path where nobody is
        # looking at the screen: a worker publishes through the agent API, so the patron
        # watching the board never touched anything that could have triggered a re-read.
        self._bus = control_bus
        # A publish is a task-change moment, so the task's drive is recomputed here
        # (QĐ-4): an artifact landing at the Done gate is evidence the task is being
        # moved, and without this say-so the net could read the gate itself as silence
        # (FR-020d).
        self._drive_refresh = drive_refresh

    async def publish(
        self,
        *,
        task_id: UUID,
        name: str,
        kind: str = "file",
        content: bytes | None = None,
        uri: str | None = None,
        marius_id: UUID | None = None,
    ) -> PublishOutcome:
        # The dedup key (research §6): same task, same agent-chosen name, same bytes is
        # the SAME artifact — a retry after a push that died mid-upload lands on the row
        # already written rather than fathering a duplicate (FR-020c). Nothing in the key
        # mentions a run: the working directory lives with the task, so the file is still
        # there and the retry is welcome in a later run, as many times as it takes
        # (FR-020b).
        if kind == "link":
            if not uri:
                raise BadRequest("artifact_link_needs_uri")
            content_hash = hashlib.sha256(uri.encode("utf-8")).hexdigest()
        else:
            if content is None:
                raise BadRequest("artifact_needs_content", kind=kind)
            content_hash = hashlib.sha256(content).hexdigest()

        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise NotFound("task_not_found")
            project_id = task.project_id
            assert project_id is not None

            existing = await uow.artifacts.find_by_dedup_key(task_id, name, content_hash)
            if existing is not None:
                version = await uow.artifacts.count_named(task_id, name)
                return PublishOutcome(artifact=existing, created=False, version=version)

            if kind == "link":
                artifact = Artifact(
                    project_id=project_id,
                    task_id=task_id,
                    marius_id=marius_id,
                    name=name,
                    kind=kind,
                    uri=uri or "",
                    content_hash=content_hash,
                    created_at=utcnow(),
                )
            else:
                assert content is not None
                stored = await self._store.save_bytes(project_id, name, content)
                await self._verify_stored(stored.uri, content_hash)
                artifact = Artifact(
                    project_id=project_id,
                    task_id=task_id,
                    marius_id=marius_id,
                    name=name,
                    kind=kind,
                    uri=stored.uri,
                    content_sha256=stored.sha256,
                    content_hash=content_hash,
                    size_bytes=stored.size_bytes,
                    created_at=utcnow(),
                )
            version = await uow.artifacts.count_named(task_id, name) + 1
            try:
                created = await uow.artifacts.add(artifact)
                await uow.commit()
            except IntegrityError:
                # Two copies of the same push landing together: the unique key
                # (task, name, hash) kept the duplicate out — hand back the row that won,
                # exactly as if this call had arrived a second later.
                await uow.rollback()
                won = await uow.artifacts.find_by_dedup_key(task_id, name, content_hash)
                assert won is not None
                return PublishOutcome(artifact=won, created=False, version=version)

        if self._drive_refresh is not None:
            await self._drive_refresh(task_id)

        # Identifiers only — the artifact's name is content, and content stays off the
        # channel (contract `push-events` principle 4). A retry does not announce again:
        # the clip is already on the card, and a second ping would only say "the network
        # dropped a reply once".
        if self._bus is not None:
            await self._bus.publish(
                project_topic(project_id),
                EVENT_TASK_ARTIFACT,
                {"task_id": str(task_id), "artifact_id": str(created.id)},
            )
        return PublishOutcome(artifact=created, created=True, version=version)

    async def _verify_stored(self, uri: str, content_hash: str) -> None:
        """Prove the bytes can be fetched back before the row claims they exist (FR-020).

        A store that cannot return what it was just handed has not stored anything. The
        publish fails here — no row is written — so the caller is free to send it again
        (FR-020b); recording the row anyway would make the retry a duplicate of nothing.
        """
        try:
            back = await self._store.read_bytes(uri)
        except Exception as exc:
            raise ArtifactStoreUnreliable("artifact_store_unreadable") from exc
        if hashlib.sha256(back).hexdigest() != content_hash:
            raise ArtifactStoreUnreliable("artifact_store_unreadable")

    async def list_by_task(self, task_id: UUID) -> Sequence[Artifact]:
        async with self._uow() as uow:
            return await uow.artifacts.list_by_task(task_id)
