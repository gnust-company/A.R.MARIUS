"""Thread use cases — post comments, resolve @mentions, and wake mentioned agents (§3.2)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from uuid import UUID

from armarius.application.use_cases.types import UowFactory
from armarius.application.use_cases.wake_engine import WakeEngine
from armarius.domain.entities.comment import AuthorKind, Comment
from armarius.domain.entities.run import WakeSource
from armarius.shared.clock import utcnow

_MENTION_RE = re.compile(r"@([A-Za-z0-9_\-\.]+)")


class ThreadService:
    def __init__(self, uow_factory: UowFactory, wake_engine: WakeEngine) -> None:
        self._uow = uow_factory
        self._wake = wake_engine

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

        # Mention is a first-class event-wake: it actually wakes the right agent.
        for marius_id in mention_ids:
            await self._wake.enqueue(
                marius_id=marius_id,
                task_id=task_id,
                source=WakeSource.MENTION,
                reason="you were mentioned in the task thread",
            )
        return created

    async def list_comments(self, task_id: UUID) -> Sequence[Comment]:
        async with self._uow() as uow:
            return await uow.comments.list_by_task(task_id)
