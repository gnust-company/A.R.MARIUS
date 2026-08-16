"""spec001 T179: sweep the retired *silent* threshold out of project settings

No column is dropped here, and none was ever added — which is the whole reason this file
had to exist separately. Per-project timing overrides do not live in named columns; they
live inside the free-form ``projects.settings`` blob under a ``thresholds`` key. Removing
``task_silence_seconds`` from :class:`ProjectThresholds` therefore changed nothing about
the schema, and left the stored key behind on every project that had ever overridden it.

That leftover is inert — ``with_overrides`` drops keys it does not recognise, deliberately,
so a bad value in settings can never stop a watchdog — and it self-heals the next time
anybody saves thresholds, because that path rewrites the whole ``thresholds`` dict filtered
to known names. But "inert" and "self-heals if someone happens to touch it" are not the
same as gone: a project nobody edits again keeps a knob that controls nothing, and an
operator reading the row has no way to tell it apart from one that still works.

Unlike the sweep log, this is configuration and not history, so there is nothing to
preserve by leaving it. The spec keeps *history* forever and read-only (Giả định); it makes
no such promise about a dead config key.

Revises: a5d2c9f7e134
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b4e7f1a9c206"
down_revision = "a5d2c9f7e134"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Both statements are no-ops on a row that never held the key, so neither needs a
    # WHERE clause narrower than "has settings at all".
    if op.get_bind().dialect.name == "postgresql":
        # The column is `json`, not `jsonb`, so the path-delete operator needs a cast on
        # the way in and another on the way back.
        op.execute(
            sa.text(
                "UPDATE projects "
                "SET settings = ((settings)::jsonb #- "
                "'{thresholds,task_silence_seconds}')::json "
                "WHERE settings IS NOT NULL"
            )
        )
    else:
        op.execute(
            sa.text(
                "UPDATE projects "
                "SET settings = json_remove(settings, "
                "'$.thresholds.task_silence_seconds') "
                "WHERE settings IS NOT NULL"
            )
        )


def downgrade() -> None:
    """Deliberately empty.

    There is no value to put back. The key named a threshold that no code reads any more,
    so restoring it would recreate the exact confusion this migration removes — and the
    original numbers are gone regardless. Downgrading the schema past this point leaves
    projects on the system floor, which is what they were already effectively running on.
    """
