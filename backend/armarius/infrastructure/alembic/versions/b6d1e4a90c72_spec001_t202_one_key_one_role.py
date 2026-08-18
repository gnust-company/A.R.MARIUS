"""spec001 T202: one key, one role, inside a project

Everything that addresses a role addresses it by key — the roster API, the onboarding plan
the Leader drafts, `_role_by_key`, `leader_role_ids`. Two rows sharing a key inside one
project make every one of those answer from whichever row the database handed back first.

`add_role` already refused a colliding key, but only one role at a time. A whole roster
arriving at once never passed that check, and the onboarding door hands the agent's own
drafted keys straight through — so two roles both titled "Backend" became two rows keyed
`backend`. The application now refuses that at `validate_plan`; this makes the database
refuse it too, which is the half that also covers rows already written.

The rename keeps the row the running code would have picked (oldest by `created_at`, then
by `id` — the same tie-break the seat migration used) on the original key, and renumbers
the rest. Seats are untouched: since T199 a seat points at `role_id`, not at the key, so
renaming a role does not move anybody out of their seat.

Revision ID: b6d1e4a90c72
Revises: e9c2a4d7f0b3
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b6d1e4a90c72"
down_revision = "e9c2a4d7f0b3"
branch_labels = None
depends_on = None

_KEY_MAX = 120


def _unique_key(base: str, taken: set[str]) -> str:
    """`backend` → `backend2` → `backend3`, the shape the project-key door already uses.

    Loops against the keys actually present rather than assuming a suffix is free: a
    project may already hold a hand-made `backend2`, and a rename that collided would
    trade one duplicate for another right as the constraint goes on.
    """
    suffix = 2
    while True:
        tail = str(suffix)
        candidate = base[: _KEY_MAX - len(tail)] + tail
        if candidate not in taken:
            return candidate
        suffix += 1


def _make_keys_unique() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, project_id, key FROM roles "
            "ORDER BY project_id, key, (created_at IS NULL), created_at, id"
        )
    ).fetchall()

    by_project: dict[object, set[str]] = {}
    for _, project_id, key in rows:
        by_project.setdefault(project_id, set()).add(key)

    seen: set[tuple[object, str]] = set()
    for role_id, project_id, key in rows:
        if (project_id, key) not in seen:
            seen.add((project_id, key))
            continue
        # A repeat: this row lost the tie-break, so it is the one that moves.
        fresh = _unique_key(key, by_project[project_id])
        by_project[project_id].add(fresh)
        seen.add((project_id, fresh))
        bind.execute(
            sa.text("UPDATE roles SET key = :fresh WHERE id = :id"),
            {"fresh": fresh, "id": role_id},
        )


def upgrade() -> None:
    _make_keys_unique()
    with op.batch_alter_table("roles") as batch:
        batch.create_unique_constraint("uq_roles_project_key", ["project_id", "key"])


def downgrade() -> None:
    # Only the constraint comes off. The renames stay: the old keys are not recoverable,
    # and inventing them back would re-create the ambiguity this migration existed to end.
    with op.batch_alter_table("roles") as batch:
        batch.drop_constraint("uq_roles_project_key", type_="unique")
