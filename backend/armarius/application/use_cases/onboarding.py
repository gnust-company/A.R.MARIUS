"""Where an agent's credential file lives.

This module used to build the prompts the system pushed at an agent — one to set it up when
it was invited, one to make it install a skill. Both are gone with the gateway that carried
them (FR-007g, FR-011c): the daemon fetches its own work and its own skills, so there is
nothing left to push.

What survives is the one thing those prompts and every wake prompt had to agree on: the path
of the file the agent keeps its token in. It is here, in one function, for the same reason it
always was — two places naming that file separately is two places that can name it
differently.
"""

from __future__ import annotations

import re

from armarius.domain.entities.marius import Marius


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "workspace"


def credential_file_for(marius: Marius, workspace_name: str) -> str:
    """The file where the agent stores its token. Skills read the token from here.

    Shared by the invite (STEP 1) and every wake prompt so the two never name a
    different file — a multi-workspace agent has one file per workspace (#15).

    **Path note**: The file sits directly under ``$HOME/.armarius/`` (no ``tokens``/
    ``credentials`` subfolder) — a flat per-workspace JSON named ``<slug>.json``. We spell
    it ``$HOME`` (not ``~``) so weak runtimes don't fumble tilde expansion (#114).
    """
    return f"$HOME/.armarius/{_slugify(workspace_name)}_{marius.name.lower()}.json"
