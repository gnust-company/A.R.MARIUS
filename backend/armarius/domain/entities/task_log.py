"""Task change log — the append-only history of one task's whole life (spec 001 §10).

Distinct from the per-run trace (`RunEvent`), which follows *one agent run*. This log
follows *the task*, across every run, every assignee and every signature, and is the
single evidence trail four separate requirements depend on (FR-021, FR-039, FR-061,
FR-079).

Immutable by construction: entries are only ever appended, never edited or deleted.
`seq` is per-task and monotonic so the timeline is stable even when two entries share a
timestamp.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class TaskLogKind(StrEnum):
    """What happened. One entry kind per meaningful event in a task's life."""

    STATUS_CHANGED = "status_changed"
    ASSIGNED = "assigned"
    UNASSIGNED = "unassigned"
    ARTIFACT_PUBLISHED = "artifact_published"
    APPROVAL_SIGNED = "approval_signed"
    STALL_FLAGGED = "stall_flagged"
    STALL_CLEARED = "stall_cleared"
    ESCALATED = "escalated"
    WOKEN = "woken"
    CRITERIA_CHANGED = "criteria_changed"
    REOPENED = "reopened"
    PLAN_ITEM_LINKED = "plan_item_linked"


class ActorKind(StrEnum):
    """Who caused it. `SYSTEM` covers watchdogs, the orchestrator and migrations."""

    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


@dataclass
class TaskLogEntry:
    """One immutable line in a task's history."""

    id: UUID = field(default_factory=uuid4)
    task_id: UUID | None = None
    # Per-task monotonic counter, allocated at append time. Two entries never share one.
    seq: int = 0
    kind: TaskLogKind = TaskLogKind.STATUS_CHANGED
    actor_kind: ActorKind = ActorKind.SYSTEM
    actor_marius_id: UUID | None = None
    actor_user_id: str | None = None
    # Free-form before/after — a status pair, an assignee pair, a signature verdict…
    # Rendered by the reader; the log stores what changed, not how to phrase it.
    before: str | None = None
    after: str | None = None
    reason: str | None = None
    # Extra structured payload for kinds that need more than a before/after pair
    # (escalation dossiers, wake causes). Kept small — the log is not a blob store.
    detail: dict[str, object] = field(default_factory=dict)
    created_at: datetime | None = None
