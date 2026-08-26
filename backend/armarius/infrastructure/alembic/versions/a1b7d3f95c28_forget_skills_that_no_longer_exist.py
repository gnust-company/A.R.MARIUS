"""spec002: take deleted skills out of everything that still names them

An agent's skill links are three lists that have to agree: the ids it is linked to, the
display names beside them, and the record of what it has installed. Deleting a skill until
now removed the row and left all three pointing at it. Nothing broke, which is why it
accumulated: whoever resolves those ids drops the ones it cannot find, so the only visible
symptom was two lists of different lengths and an install record naming a skill that is not
in the Shop.

`armarius-mcp` was deleted on 2026-08-26 and `armarius-onboarder` before it, so there is
already a generation of this in the database. This clears all of it — not only those two
slugs, but every id in `mariuses.skill_ids` and `roles.skill_ids` with no skill behind it.

Done in Python rather than in SQL: the columns are JSON on both SQLite and Postgres, and one
statement that reads correctly on both would be longer and harder to check than the loop.

Revision ID: a1b7d3f95c28
Revises: e4c9f7b21a63
Create Date: 2026-08-26

"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision: str = "a1b7d3f95c28"
down_revision: str | None = "e4c9f7b21a63"
branch_labels: str | None = None
depends_on: str | None = None


def _as_list(raw: object) -> list[str]:
    """The column comes back as a list on one driver and as a JSON string on another."""
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if isinstance(raw, str) and raw.strip():
        try:
            loaded = json.loads(raw)
        except ValueError:
            return []
        return [str(x) for x in loaded] if isinstance(loaded, list) else []
    return []


def _as_dict(raw: object) -> dict[str, str]:
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, str) and raw.strip():
        try:
            loaded = json.loads(raw)
        except ValueError:
            return {}
        return (
            {str(k): str(v) for k, v in loaded.items()}
            if isinstance(loaded, dict)
            else {}
        )
    return {}


def upgrade() -> None:
    bind = op.get_bind()

    skills = {
        str(row.id): (str(row.name), str(row.slug))
        for row in bind.execute(sa.text("SELECT id, name, slug FROM skills"))
    }
    live_slugs = {slug for _, slug in skills.values()}

    for row in bind.execute(
        sa.text("SELECT id, skill_ids, skills, skill_installs FROM mariuses")
    ):
        linked = _as_list(row.skill_ids)
        kept = [s for s in linked if s in skills]
        # The names are rebuilt from the ids that survived rather than filtered alongside
        # them. Filtering both would keep whatever disagreement was already there; deriving
        # one from the other cannot.
        names = [skills[s][0] for s in kept]
        installs = _as_dict(row.skill_installs)
        pruned_installs = {
            slug: state for slug, state in installs.items() if slug in live_slugs
        }
        if (
            kept == linked
            and names == _as_list(row.skills)
            and pruned_installs == installs
        ):
            continue
        bind.execute(
            sa.text(
                "UPDATE mariuses SET skill_ids = :ids, skills = :names, "
                "skill_installs = :installs WHERE id = :id"
            ),
            {
                "ids": json.dumps(kept),
                "names": json.dumps(names),
                "installs": json.dumps(pruned_installs),
                "id": row.id,
            },
        )

    for row in bind.execute(sa.text("SELECT id, skill_ids FROM roles")):
        linked = _as_list(row.skill_ids)
        kept = [s for s in linked if s in skills]
        if kept == linked:
            continue
        bind.execute(
            sa.text("UPDATE roles SET skill_ids = :ids WHERE id = :id"),
            {"ids": json.dumps(kept), "id": row.id},
        )


def downgrade() -> None:
    """Nothing to put back.

    What this migration removed was a set of references to rows that do not exist. There is
    no earlier state to restore them to, and inventing one would mean writing ids that point
    nowhere back into the database on purpose.
    """
