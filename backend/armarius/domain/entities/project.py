"""Project entity — a single initiative inside a workspace (LLD §2.2).

A project owns its roster (Roles + SeatGrants), tasks and a shared artifact folder.
Its `status` is a small lifecycle (LLD §3.1): `setup → active → archived`. Activation
is reached ONCE — every seat granted AND every seated agent ONLINE — and never rolls
back. The only behavioral gate keyed off `active` is task commission.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class ProjectStatus(StrEnum):
    SETUP = "setup"
    ACTIVE = "active"
    ARCHIVED = "archived"


def default_project_settings() -> dict:
    """Patron-tunable gates (LLD §2.2). Conservative defaults: review before done."""
    return {
        "require_review_before_done": True,
        "require_approval_for_done": False,
        "comment_required_for_review": False,
        # YOLO mode (#82): when False (default), a task the Leader proposes in the
        # Chat-with-Leader tab is created as a `draft` awaiting the patron's approval;
        # when True, the Leader's task creation + assignment is auto-approved.
        "yolo_mode": False,
        # Per-project timing overrides (spec 001). Empty means "use the system floor" —
        # only the keys a patron actually tuned live here, so raising a system default
        # lifts every project that never overrode it.
        "thresholds": {},
    }


@dataclass(frozen=True)
class ProjectThresholds:
    """Every timing knob the safety net and the orchestrator read.

    Resolved per project: a project's own `settings["thresholds"]` overrides field by
    field, and anything it leaves out falls back to the system floor built from config.
    Pure data — the domain never reads the environment itself.
    """

    hang_suspect_seconds: int
    hang_grace_seconds: int
    orchestration_cadence_seconds: int
    task_silence_seconds: int
    due_soon_hours: tuple[int, ...]
    patron_reminder_hours: tuple[int, ...]
    level1_recovery_attempts: int
    rejection_round_cap: int

    def with_overrides(self, overrides: dict[str, object] | None) -> ProjectThresholds:
        """Apply a project's overrides on top of these values, ignoring junk.

        A malformed override is dropped rather than raising: a bad number typed into
        project settings must not be able to stop the watchdog from running.
        """
        if not overrides:
            return self
        merged = {f.name: getattr(self, f.name) for f in fields(self)}
        for name, value in overrides.items():
            if name not in merged:
                continue
            current = merged[name]
            if isinstance(current, tuple):
                parsed = _coerce_int_tuple(value)
                if parsed:
                    merged[name] = parsed
            else:
                parsed_int = _coerce_positive_int(value)
                if parsed_int is not None:
                    merged[name] = parsed_int
        return ProjectThresholds(**merged)


def _coerce_positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _coerce_int_tuple(value: object) -> tuple[int, ...]:
    if not isinstance(value, list | tuple):
        return ()
    parsed = [n for n in (_coerce_positive_int(v) for v in value) if n is not None]
    return tuple(parsed)


@dataclass
class Project:
    """A single initiative inside a workspace; owns tasks, roster and a shared store."""

    id: UUID = field(default_factory=uuid4)
    workspace_id: UUID | None = None
    name: str = ""
    slug: str = ""
    # Short uppercase code, unique per workspace — the KEY in task identifiers "{key}-{n}"
    # (JIRA-style). Immutable once set; chosen at create time (suggested from `name`).
    key: str = ""
    description: str | None = None
    # Commission/brief context (Patron-supplied, all optional).
    objective: str | None = None
    success_metrics: dict | None = None
    target_date: datetime | None = None
    github_url: str | None = None
    context: str | None = None
    settings: dict = field(default_factory=default_project_settings)
    status: ProjectStatus = ProjectStatus.SETUP
    # Monotonic per-project task counter — atomically incremented when a task is created
    # so identifiers are never reused and never collide under concurrent creates.
    next_task_seq: int = 1
    created_by_user_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
