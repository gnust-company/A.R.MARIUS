"""Pure project rules (LLD §3.1, §4) — no I/O.

Two decisions the application layer leans on:
  - `validate_plan` — the hard roster rule at create time: exactly one leader role with
    `seats == 1`, plus at least one non-leader role with `seats >= 1`.
  - `recompute_active` — the activation rule: a project flips `setup → active` ONCE, when
    every role seat is granted AND every seated agent is ONLINE; it never rolls back.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from uuid import UUID

from armarius.domain.entities.marius import Liveness
from armarius.domain.entities.project import Project, ProjectStatus
from armarius.domain.entities.role import Role
from armarius.domain.entities.seat_grant import SeatGrant, SeatGrantStatus


class InvalidProjectPlan(Exception):
    """Raised when a roster plan violates the leader/worker rule (LLD §4)."""


def validate_plan(roles: Iterable[Role]) -> None:
    """Enforce the create-time roster rule (LLD §2.3, §4; spec 03 §1.1, §3.1).

    Exactly one leader role, the leader has `seats == 1`, there is at least one non-leader
    role with `seats >= 1`, AND **every** role carries a non-empty description (so the wake /
    leader-chat prompts can tell each agent what its role — and its teammates' roles — do).

    Composition is checked first so a plan that is invalid for a stronger reason (no leader,
    wrong seat count) fails on that, not on a missing description.
    """
    roles = list(roles)
    leaders = [r for r in roles if r.is_leader]
    if len(leaders) != 1:
        raise InvalidProjectPlan(
            f"A project needs exactly one leader role, found {len(leaders)}."
        )
    if leaders[0].seats != 1:
        raise InvalidProjectPlan("The leader role must have exactly one seat.")
    workers = [r for r in roles if not r.is_leader and r.seats >= 1]
    if not workers:
        raise InvalidProjectPlan("A project needs at least one worker role with a seat.")
    undescribed = [r for r in roles if not (r.description or "").strip()]
    if undescribed:
        titles = ", ".join(r.title or r.key for r in undescribed)
        raise InvalidProjectPlan(
            f"Every role needs a description of what it does — missing for: {titles}."
        )


def _active_grants(grants: Iterable[SeatGrant]) -> list[SeatGrant]:
    return [g for g in grants if g.status == SeatGrantStatus.GRANTED]


def seats_filled(roles: Iterable[Role], grants: Iterable[SeatGrant]) -> bool:
    """True when every role has at least `seats` active grants."""
    filled = Counter(g.role_key for g in _active_grants(grants))
    return all(filled.get(r.key, 0) >= r.seats for r in roles)


def all_seated_online(
    grants: Iterable[SeatGrant],
    liveness_by_marius: Mapping[UUID, Liveness],
) -> bool:
    """True when there is at least one grant and every seated agent is ONLINE."""
    active = _active_grants(grants)
    if not active:
        return False
    return all(liveness_by_marius.get(g.marius_id) == Liveness.ONLINE for g in active)


def should_activate(
    roles: Iterable[Role],
    grants: Iterable[SeatGrant],
    liveness_by_marius: Mapping[UUID, Liveness],
) -> bool:
    """The activation predicate: all seats granted AND all seated agents ONLINE."""
    roles = list(roles)
    grants = list(grants)
    return seats_filled(roles, grants) and all_seated_online(grants, liveness_by_marius)


def recompute_active(
    project: Project,
    roles: Iterable[Role],
    grants: Iterable[SeatGrant],
    liveness_by_marius: Mapping[UUID, Liveness],
) -> bool:
    """Flip `setup → active` once the predicate holds. Returns True iff it just activated.

    Idempotent and one-way: an already-active (or archived) project is left untouched,
    and a later offline agent does NOT roll an active project back to setup.
    """
    if project.status != ProjectStatus.SETUP:
        return False
    if should_activate(roles, grants, liveness_by_marius):
        project.status = ProjectStatus.ACTIVE
        return True
    return False
