"""The orchestration cadence, as pure functions (spec 001 FR-052 → FR-055).

A Leader that is woken on a timer learns nothing: most ticks it opens its eyes onto a board
where everything is fine, and the wake costs a turn to discover that. A Leader that is
never woken misses the task that quietly stopped. So the loop does the looking, every
tick, and only spends a wake when the looking found something.

This module is the *looking*, and nothing else — no I/O, no clock of its own. Two jobs:

  * **find the snags** (FR-052). Three kinds, each one field on the board read against a
    definition that two people would implement the same way. "The board looks stuck" is
    not one of those, and neither is "is anything about to touch this task" — that
    question belongs to the stall sweep (FR-057), which has the drive (FR-056) to answer
    it correctly and the recovery ladder (FR-059) to act on the answer.
  * **set the rhythm** (FR-055). Stretch while the project runs smoothly, tighten when work
    backs up, and never exceed a ceiling of wakes per hour.

The caller hands over a snapshot of the board plus what the last sweeps saw, and gets back
what this sweep should do.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from armarius.domain.entities.task import TaskStatus


class SnagKind(StrEnum):
    """The three things worth waking a Leader for. Closed list — FR-052 names all three."""

    DUE_SOON = "due_soon"  # the deadline just crossed a warning mark
    BLOCKED = "blocked"  # sitting in *blocked*
    AWAITING_LEADER = "awaiting_leader"  # waiting on the Leader itself to act

    # Retired. This cadence used to ask "has this task gone quiet", which is the stall
    # sweep's question and which this loop had no drive to answer correctly — a task whose
    # wake was queued but not yet running, and a task being retried because its assignee is
    # offline, both read as silent here, and FR-063 says the second must not count. The
    # member survives so sweeps recorded before the retirement still load; nothing produces
    # it. Do not reintroduce a kind that needs this question.
    SILENT = "silent"


# Tasks that are finished with. Never a snag, however long ago they last moved.
_CLOSED: frozenset[TaskStatus] = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED})

# A *draft* is the Leader's own proposal waiting on the patron, not work sitting idle on
# the board. Waking the Leader about it would be telling it to chase itself.
_NOT_ON_THE_BOARD: frozenset[TaskStatus] = frozenset({TaskStatus.DRAFT})


@dataclass(frozen=True)
class TaskSnapshot:
    """One task as the sweep sees it — everything the rules need, and nothing else.

    Deliberately not the ``Task`` entity: ``awaiting_leader_decision`` is an answer about
    *another* table, and passing the entity would either hide that lookup inside the rule
    or leave the rule unable to ask it. The other three fields are read straight off the
    board, which is the whole of what FR-052 allows this cadence to look at.
    """

    task_id: UUID
    identifier: str
    title: str
    status: TaskStatus
    due_date: datetime | None
    awaiting_leader_decision: bool


@dataclass(frozen=True)
class Snag:
    """One thing on the board that wants the Leader's eyes, named well enough to act on."""

    kind: SnagKind
    task_id: UUID
    identifier: str
    # The agent's copy, English (Constitution VII). The patron reads the same snag on the
    # project board, so the screen builds its own sentence from `kind` plus the fields
    # below rather than showing this one — the two readers do not share a language.
    detail: str
    title: str = ""
    # For *due soon* only: which warning mark this snag is reporting, so the next sweep
    # knows it has already been told (FR-052 says *just crossed*, not *is under*).
    mark_hours: int | None = None


def tightest_mark_crossed(
    *, due_date: datetime | None, now: datetime, marks: Sequence[int]
) -> int | None:
    """The smallest warning mark the remaining time has fallen under, or None.

    A task past its deadline has crossed every mark, so it reports the tightest one — the
    alternative (reporting nothing once the deadline passes) would go quiet at exactly the
    moment the news matters most.
    """
    if due_date is None or not marks:
        return None
    remaining_hours = (due_date - now).total_seconds() / 3600.0
    crossed = [m for m in marks if remaining_hours <= m]
    return min(crossed) if crossed else None


def find_snags(
    snapshots: Iterable[TaskSnapshot],
    *,
    now: datetime,
    due_soon_hours: Sequence[int],
    reported_marks: Mapping[UUID, int] | None = None,
) -> list[Snag]:
    """Every snag on the board right now (FR-052).

    ``reported_marks`` carries what the previous sweeps already said about each task's
    deadline, so a mark is announced once rather than on every sweep for the rest of the
    day. Everything else is decided from the board as it stands.
    """
    already = reported_marks or {}
    snags: list[Snag] = []
    for task in snapshots:
        if task.status in _CLOSED or task.status in _NOT_ON_THE_BOARD:
            continue

        if task.status is TaskStatus.BLOCKED:
            snags.append(
                Snag(
                    kind=SnagKind.BLOCKED,
                    task_id=task.task_id,
                    identifier=task.identifier,
                    title=task.title,
                    detail=f"{task.identifier} — {task.title}: blocked.",
                )
            )

        if task.awaiting_leader_decision:
            snags.append(
                Snag(
                    kind=SnagKind.AWAITING_LEADER,
                    task_id=task.task_id,
                    identifier=task.identifier,
                    title=task.title,
                    detail=(
                        f"{task.identifier} — {task.title}: waiting on your own decision."
                    ),
                )
            )

        mark = tightest_mark_crossed(
            due_date=task.due_date, now=now, marks=due_soon_hours
        )
        if mark is not None and mark < already.get(task.task_id, 10**6):
            snags.append(
                Snag(
                    kind=SnagKind.DUE_SOON,
                    task_id=task.task_id,
                    identifier=task.identifier,
                    title=task.title,
                    detail=(
                        f"{task.identifier} — {task.title}: due in under {mark} hour(s)."
                    ),
                    mark_hours=mark,
                )
            )
    return snags


# ── the rhythm (FR-055) ──────────────────────────────────────────────────────────

# Two ceilings on the stretch, and the gap obeys **both**. Either one alone reads the
# spec's "widest gap: two hours" (Giả định, chốt 2026-07-30) in a way that goes wrong at one
# end of the configuration range:
#
#   * eight times the base alone — right at the default fifteen minutes, but a project
#     configured to sweep hourly would stretch to *eight hours*, far past anything the
#     assumption contemplates;
#   * a flat two hours alone — right for that project, but it would take one configured to
#     one minute (an operator saying "watch this closely") and stretch it a hundred and
#     twenty times over.
#
# Applying both keeps the relative promise at the fast end and the absolute one at the slow
# end. A project whose own base is already wider than two hours keeps its base: the ceiling
# is on the *stretch*, and it must never speed a project up past what its operator asked
# for.
#
# There is a ceiling at all because a quiet project is quiet, not finished.
#
# All three bounds arrive as arguments rather than living here as constants: they are
# thresholds like any other, so a project may raise or lower them, and a rule the caller
# cannot see is a rule the operator cannot change (`ProjectThresholds`).


@dataclass(frozen=True)
class CadenceState:
    """What the previous sweeps saw, reduced to the two facts the rhythm turns on."""

    quiet_streak: int  # sweeps *before* this one that found nothing, newest first
    found_snags: bool  # …and what *this* sweep found


def next_interval_seconds(
    base_seconds: int,
    *,
    state: CadenceState,
    max_stretch: int,
    max_interval_seconds: int,
    min_interval_seconds: int,
) -> int:
    """How long to wait before sweeping this project again.

    The configured cadence is what a project gets by default; slack is **earned**. A first
    quiet sweep buys nothing — an operator who sets fifteen minutes must get fifteen
    minutes, not thirty because the board happened to be clean the first time anyone
    looked. Each *further* consecutive quiet sweep doubles the gap, up to the cap.

    A sweep that finds something goes straight to a tighter-than-base rhythm, discarding
    the whole streak. Asymmetric on purpose: earning slack should be slow and losing it
    instant, because the cost of being slow to notice a stuck project is paid by the
    project, while the cost of an extra sweep is a few queries.

    The three bounds are required arguments, not defaults: a default here would be a
    threshold nobody can find and nobody can override.
    """
    if state.found_snags:
        return max(base_seconds // 2, min_interval_seconds)
    multiplier = int(min(2 ** max(state.quiet_streak, 0), max_stretch))
    stretched = min(base_seconds * multiplier, max_interval_seconds)
    # Never below the configured cadence: the ceiling caps how far a quiet project may
    # drift, and must not hurry along one whose operator asked for something slower.
    return max(stretched, base_seconds, min_interval_seconds)


def within_hourly_cap(*, wakes_in_last_hour: int, cap: int) -> bool:
    """Whether one more cadence wake fits under the ceiling (FR-055).

    A cap of zero or less reads as *no ceiling configured*, never as *never wake anyone*.
    The second reading turns a mistyped setting into a project nobody drives, which is the
    exact failure this whole feature exists to prevent.
    """
    if cap <= 0:
        return True
    return wakes_in_last_hour < cap


def quiet_streak(recent_snag_counts: Sequence[int]) -> int:
    """How many sweeps in a row found nothing, newest first."""
    streak = 0
    for count in recent_snag_counts:
        if count:
            break
        streak += 1
    return streak
