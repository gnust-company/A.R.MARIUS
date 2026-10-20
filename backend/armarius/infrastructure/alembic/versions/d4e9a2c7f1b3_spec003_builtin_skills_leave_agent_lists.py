"""spec003 — built-in skills leave every agent's own list (FR-123).

A built-in skill reaches every run by a road of its own (`SkillService.builtins_for`), so an
agent's `skill_ids` is meant to hold only what a person chose. Some hold a built-in anyway:
until 2026-09-06 the sheet only arrived if somebody ticked its chip, and people did. From spec
003 no screen shows a built-in, so a built-in left in an agent's list would surface as an
unexplained entry on the agent's skills tab — the one place that still reads the list.

Data only. Each agent loses the ids of its own workspace's built-ins from `skill_ids`. Only
an agent that actually lost one is touched, and its `skills` (the names shown beside the ids)
is then **rebuilt from the ids that are left** — the way `SkillService._forget_everywhere`
rebuilds it after a deletion — rather than filtered by matching titles. A person's own skill may
carry exactly a built-in's name, and filtering by name would strip its name and keep its id.

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
    builtins: dict[str, set[str]] = {}
    name_of: dict[str, str] = {}
    for skill_id, workspace_id, name, source in bind.execute(
        sa.select(_skills.c.id, _skills.c.workspace_id, _skills.c.name, _skills.c.source)
    ):
        name_of[_same(skill_id)] = name
        if source == "builtin":
            builtins.setdefault(_same(workspace_id), set()).add(_same(skill_id))
    if not builtins:
        return

    rows = bind.execute(
        sa.select(_mariuses.c.id, _mariuses.c.workspace_id, _mariuses.c.skill_ids)
    ).all()
    for marius_id, workspace_id, skill_ids in rows:
        ids_here = builtins.get(_same(workspace_id), set())
        before = list(skill_ids or [])
        kept = [i for i in before if _same(i) not in ids_here]
        if len(kept) == len(before):
            continue
        bind.execute(
            _mariuses.update()
            .where(_mariuses.c.id == marius_id)
            .values(
                skill_ids=kept,
                skills=[name_of[_same(i)] for i in kept if _same(i) in name_of],
            )
        )


def downgrade() -> None:
    pass
