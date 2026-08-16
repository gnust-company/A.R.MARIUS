"""Project entity — a single initiative inside a workspace (LLD §2.2).

A project owns its roster (Roles + SeatGrants), tasks and a shared artifact folder.
Its `status` is the five-phase lifecycle of spec 001 (FR-001 → FR-006):

    setup → planning → operating ⇄ maintaining → closed

Reaching a full, online roster no longer opens the doors — it opens the *planning* gate.
Real work only starts once the patron approves the plan, and `closed` is terminal: the
history stays readable, every write is refused. The transition table and the gates live
in `domain.services.project_rules`; this module only names the phases.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class ProjectStatus(StrEnum):
    """The five phases. Declaration order is the forward order of the lifecycle."""

    SETUP = "setup"
    PLANNING = "planning"
    OPERATING = "operating"
    MAINTAINING = "maintaining"
    CLOSED = "closed"


def default_project_settings() -> dict:
    """Patron-tunable gates (LLD §2.2). Conservative defaults: review before done."""
    return {
        "require_review_before_done": True,
        "comment_required_for_review": False,
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
    due_soon_hours: tuple[int, ...]
    patron_reminder_hours: tuple[int, ...]
    level1_recovery_attempts: int
    rejection_round_cap: int
    # Ceiling on cadence wakes per hour (FR-055). Zero means *no ceiling configured*,
    # never *never wake anyone* — see `within_hourly_cap`.
    orchestration_wakes_per_hour: int = 4

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
