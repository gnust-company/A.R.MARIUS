"""Skill entity — an installable capability authored in a workspace's Skill Shop.

A Skill is a small file tree rooted at SKILL.md. `files` maps path → content
(SKILL.md plus any sibling files/folders the author adds, e.g. scripts/ or
references/). Built-in skills ship their content; manual skills start from a
generated SKILL.md template; imported skills are cloned from a GitHub folder. The
skill's `name`/`description` come from the SKILL.md YAML frontmatter. `source_url`
records provenance (the GitHub link for imports, the served path for built-ins) and
is what gets advertised to agents in the invitation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4


@dataclass
class Skill:
    """An installable skill seated in a workspace's Skill Shop."""

    id: UUID = field(default_factory=uuid4)
    workspace_id: UUID | None = None
    slug: str = ""
    name: str = ""
    description: str = ""
    source: str = "builtin"  # "builtin" | "manual" | "imported"
    # Provenance / agent-facing URL. Relative ("/static/...") for built-ins, absolute
    # (https://github.com/...) for imports. Resolved against the public base URL.
    source_url: str = ""
    # path → content. Rooted at SKILL.md; may include sibling files/folders.
    files: dict[str, str] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def absolute_source_url(self, public_base_url: str) -> str:
        """Resolve source_url against the public base URL when it is relative."""
        if not self.source_url:
            return ""
        if self.source_url.startswith("/"):
            return f"{public_base_url.rstrip('/')}{self.source_url}"
        return self.source_url

