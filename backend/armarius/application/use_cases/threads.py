"""Thread use cases — post comments, resolve @mentions, and wake mentioned agents (§3.2)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from uuid import UUID

from armarius.application.use_cases.types import UowFactory
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.domain.entities.comment import AuthorKind, Comment
from armarius.domain.entities.run import WakeSource
from armarius.infrastructure.events.topic_bus import TopicEventBus, project_topic
from armarius.shared.clock import utcnow

_MENTION_RE = re.compile(r"@([A-Za-z0-9_\-\.]+)")

# Named here, next to the service that owns comments, because two other callers emit it:
# `TaskService.request_assignment` and `TaskService.hand_back` both write a comment row
# without going through this service. A board card counts those rows the same either way,
# so all three have to say the same word.
EVENT_TASK_COMMENT = "task.comment_added"


async def announce_comment(
    bus: TopicEventBus | None, project_id: UUID | None, task_id: UUID
) -> None:
    """Tell the project channel a comment landed (no-op if the bus is not wired).

    An identifier and nothing else — the comment body stays off the wire (contract
    `su-kien-day` principle 4). The listener re-reads through the API, where the workspace
    guard still applies; a body on the channel would be a second way to read the row with
    no guard in front of it.
    """
    if bus is None or project_id is None:
        return
    await bus.publish(
        project_topic(project_id), EVENT_TASK_COMMENT, {"task_id": str(task_id)}
    )


class ThreadService:
    def __init__(
        self,
        uow_factory: UowFactory,
        wake_engine: WakeEngine,
        *,
        control_bus: TopicEventBus | None = None,
    ) -> None:
        self._uow = uow_factory
        self._wake = wake_engine
        # A comment used to wake the people it concerned and tell nobody else. That is
        # right for a wake and wrong for a screen: the board draws a comment count, and it
        # sat frozen because this service had no channel to announce anything on (T177).
        self._bus = control_bus

    async def post_comment(
        self,
        *,
        task_id: UUID,
        body: str,
        author_kind: AuthorKind,
        author_marius_id: UUID | None = None,
        author_user_id: str | None = None,
        extra_mentions: list[UUID] | None = None,
    ) -> Comment:
        async with self._uow() as uow:
            task = await uow.tasks.get(task_id)
            if task is None:
                raise LookupError("task not found")
            project = await uow.projects.get(task.project_id) if task.project_id else None
            directory = (
                await uow.mariuses.list_by_workspace(project.workspace_id)
                if project and project.workspace_id
                else []
            )
            by_name = {m.name.lower(): m.id for m in directory}

            mention_ids: set[UUID] = set(extra_mentions or [])
            for token in _MENTION_RE.findall(body):
                resolved = by_name.get(token.lower())
                if resolved is not None:
                    mention_ids.add(resolved)
            if author_marius_id is not None:
                mention_ids.discard(author_marius_id)

            comment = Comment(
                task_id=task_id,
                author_kind=author_kind,
                author_marius_id=author_marius_id,
                author_user_id=author_user_id,
                body=body,
                mentions=list(mention_ids),
                created_at=utcnow(),
            )
            created = await uow.comments.add(comment)
            await uow.commit()
            project_id = task.project_id

        await announce_comment(self._bus, project_id, task_id)

        # Mention is a first-class event-wake: it actually wakes the right agent.
        for marius_id in mention_ids:
            await self._wake.enqueue(
                marius_id=marius_id,
                task_id=task_id,
                source=WakeSource.MENTION,
                reason="you were mentioned in the task thread",
            )

        # FR-048: a new comment on a task you are responsible for is a cause in its own
        # right. Until now only an @mention woke anyone, so asking a question the plain
        # way — the way people actually write — reached nobody until something else
        # happened to wake the worker. Note the scope: the **assignee**, and nobody else
        # (FR-049). A comment is not a project-wide announcement.
        assignee = task.assigned_marius_id
        if (
            assignee is not None
            and assignee != author_marius_id
            and assignee not in mention_ids
        ):
            await self._wake.enqueue(
                marius_id=assignee,
                task_id=task_id,
                source=WakeSource.COMMENT,
                reason="a new comment was posted on the task you are responsible for",
            )
        return created

    async def list_comments(self, task_id: UUID) -> Sequence[Comment]:
        async with self._uow() as uow:
            return await uow.comments.list_by_task(task_id)
