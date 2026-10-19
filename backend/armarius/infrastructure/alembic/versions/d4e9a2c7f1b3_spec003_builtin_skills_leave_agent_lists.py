"""spec003 — built-in skills leave every agent's own list (FR-123).

A built-in skill reaches every run by a road of its own (`SkillService.builtins_for`), so an
agent's `skill_ids` is meant to hold only what a person chose. Some hold a built-in anyway:
until 2026-09-06 the sheet only arrived if somebody ticked its chip, and people did. From spec
003 no screen shows a built-in, so a built-in left in an agent's list would surface as an
unexplained entry on the agent's skills tab — the one place that still reads the list.

Data only. Each agent loses the ids of its own workspace's built-ins from `skill_ids`, and
their names from `skills` (the list of names shown beside the ids). Nothing else is touched.

`downgrade` puts nothing back, on purpose: the built-in still reaches every run whether or not
an agent's list names it, so there is no behaviour to restore — only an entry nobody can see.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "d4e9a2c7f1b3"
down_revision = "b8d2f4a6c1e3"
branch_labels = None
depends_on = None

# Ids are read and written back untyped, in whatever form the row holds them. SQLite keeps a
# UUID either as 32 hex characters (what the ORM writes) or with dashes (what older hand-written
# migrations and seeds wrote), and a typed bind would turn one into the other and match nothing.
# They are only normalised to compare.
_skills = sa.table(
    "skills",
    sa.column("id"),
    sa.column("workspace_id"),
    sa.column("name", sa.String),
    sa.column("source", sa.String),
)
_mariuses = sa.table(
    "mariuses",
    sa.column("id"),
    sa.column("workspace_id"),
    sa.column("skills", sa.JSON),
    sa.column("skill_ids", sa.JSON),
)


def _same(value: object) -> str:
    """One spelling for a UUID however it was stored, or the text itself if it is not one."""
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        return str(value)


def upgrade() -> None:
    bind = op.get_bind()
    builtins: dict[str, tuple[set[str], set[str]]] = {}
    for skill_id, workspace_id, name in bind.execute(
        sa.select(_skills.c.id, _skills.c.workspace_id, _skills.c.name).where(
            _skills.c.source == "builtin"
        )
    ):
        ids, names = builtins.setdefault(_same(workspace_id), (set(), set()))
        ids.add(_same(skill_id))
        names.add(name)
    if not builtins:
        return

    rows = bind.execute(
        sa.select(
            _mariuses.c.id, _mariuses.c.workspace_id, _mariuses.c.skill_ids, _mariuses.c.skills
        )
    ).all()
    for marius_id, workspace_id, skill_ids, names in rows:
        ids_here, names_here = builtins.get(_same(workspace_id), (set(), set()))
        before_ids, before_names = list(skill_ids or []), list(names or [])
        kept_ids = [i for i in before_ids if _same(i) not in ids_here]
        kept_names = [n for n in before_names if n not in names_here]
        if kept_ids == before_ids and kept_names == before_names:
            continue
        bind.execute(
            _mariuses.update()
            .where(_mariuses.c.id == marius_id)
            .values(skill_ids=kept_ids, skills=kept_names)
        )


def downgrade() -> None:
    pass
