"""spec001 T199: a seat is one live row, pointing at its role by identity

Three changes to `seat_grants`, all of them the same idea — the table should say who is
seated *now*, and nothing else:

* **No history.** `status` and every `revoked` row go. Re-granting used to write a second
  row beside the spent one, so "who holds this seat" meant "the newest row that still says
  granted" — a filter each of eight readers had to remember, and the one that forgot read a
  dead row and concluded the project's own Leader held no role.
* **The role by identity.** `role_key` is a label the patron may edit; a seat that points at
  the label empties itself when the label changes. It points at `roles.id` now.
* **Both ends are foreign keys, and a seat is unique.** A deleted agent or a dropped role can
  no longer leave a seat pointing at nothing, and one agent cannot fill the same role twice
  — which used to read as two filled seats for one agent.

The table is rebuilt rather than altered in place: SQLite cannot add a foreign key to an
existing column, and a rebuild is the same statement sequence on both databases.

Three kinds of row do not survive, on purpose. A revoked row is history the new shape has no
place for. A row with no agent was never a seat. A row whose `role_key` matches no role in
its project was already unreadable — every reader joined it to a role and skipped it. Where
one agent somehow held the same role twice, the most recent row is the one kept.

**A key can name more than one role.** `roles` has no unique constraint on
`(project_id, key)`: the HTTP door renumbers a clash (`backend`, `backend-2`), but the
onboarding door takes the roster an agent wrote and passes its keys straight through, and
two workers titled "Backend" is an ordinary thing for an agent to draft. Joining on the key
alone therefore copies one seat once per matching role and breaks the primary key — which
kills the upgrade mid-chain, on a live cluster, exactly once. So the join pins the role the
running code would have picked: `roles.list_by_project` orders by `created_at` and
`_role_by_key` takes the first match, so the seat lands where the application already had
it. `tests/test_the_seat_migration_survives_real_rows.py` runs this chain over rows shaped
like that.

Revises: d3f7b2a6c1e8
Create Date: 2026-08-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e9c2a4d7f0b3"
down_revision = "d3f7b2a6c1e8"
branch_labels = None
depends_on = None

_INDEXED = ("project_id", "role_id", "marius_id", "granted_by_user_id")

# Two things have to be picked, and both are picked the way the running code already picks
# them. The correlated form is spelled out rather than done with window functions so the
# same statement runs on SQLite and on PostgreSQL.
#
# `(x IS NULL)` leads both orderings because the two databases disagree about where a NULL
# sorts, and a migration that moves a seat to a different role depending on which database
# it ran on is worse than either answer on its own.
_COPY_FORWARD = """
INSERT INTO seat_grants_rebuilt
    (id, project_id, role_id, marius_id, granted_by_user_id, granted_at, created_at)
SELECT g.id, g.project_id, r.id, g.marius_id, g.granted_by_user_id, g.granted_at, g.created_at
FROM seat_grants g
JOIN roles r ON r.project_id = g.project_id AND r.key = g.role_key
WHERE g.status = 'granted'
  AND g.marius_id IS NOT NULL
  AND r.id = (
      SELECT r2.id
      FROM roles r2
      WHERE r2.project_id = g.project_id
        AND r2.key = g.role_key
      ORDER BY (r2.created_at IS NULL), r2.created_at, r2.id
      LIMIT 1
  )
  AND g.id = (
      SELECT g2.id
      FROM seat_grants g2
      WHERE g2.status = 'granted'
        AND g2.marius_id IS NOT NULL
        AND g2.project_id = g.project_id
        AND g2.role_key = g.role_key
        AND g2.marius_id = g.marius_id
      ORDER BY (g2.created_at IS NULL), g2.created_at DESC, g2.id DESC
      LIMIT 1
  )
"""

_COPY_BACK = """
INSERT INTO seat_grants_rebuilt
    (id, project_id, role_key, marius_id, status, granted_by_user_id, granted_at, created_at)
SELECT g.id, g.project_id, r.key, g.marius_id, 'granted',
       g.granted_by_user_id, g.granted_at, g.created_at
FROM seat_grants g
JOIN roles r ON r.id = g.role_id
"""


def _swap_in() -> None:
    op.drop_table("seat_grants")
    op.rename_table("seat_grants_rebuilt", "seat_grants")
    for column in _INDEXED:
        op.create_index(f"ix_seat_grants_{column}", "seat_grants", [column])


def upgrade() -> None:
    op.create_table(
        "seat_grants_rebuilt",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("marius_id", sa.Uuid(), nullable=False),
        sa.Column("granted_by_user_id", sa.String(length=200), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        # Named explicitly, all of them: the table is created under a scratch name and
        # renamed, and a rename does not rename the constraints a database invented for
        # itself — so anything left unnamed would answer to `seat_grants_rebuilt_*` forever.
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_seat_grants_project_id"
        ),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name="fk_seat_grants_role_id"),
        sa.ForeignKeyConstraint(
            ["marius_id"], ["mariuses.id"], name="fk_seat_grants_marius_id"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_seat_grants"),
        sa.UniqueConstraint(
            "project_id", "role_id", "marius_id", name="uq_seat_grants_seat"
        ),
    )
    op.execute(sa.text(_COPY_FORWARD))
    _swap_in()


def downgrade() -> None:
    """Back to the status column and the role key. The revoked rows are not coming back."""
    op.create_table(
        "seat_grants_rebuilt",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("role_key", sa.String(length=120), nullable=False),
        sa.Column("marius_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("granted_by_user_id", sa.String(length=200), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_seat_grants_project_id"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_seat_grants"),
    )
    op.execute(sa.text(_COPY_BACK))
    op.drop_table("seat_grants")
    op.rename_table("seat_grants_rebuilt", "seat_grants")
    for column in ("project_id", "marius_id", "granted_by_user_id"):
        op.create_index(f"ix_seat_grants_{column}", "seat_grants", [column])
