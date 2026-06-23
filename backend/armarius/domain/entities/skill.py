"""Skill entity — an installable capability listed in a workspace's Skill Shop.

A Skill is workspace-scoped (not shared across all workspaces). Every workspace is
seeded with the built-in `armarius-http` skill; in a later phase users will be able
to submit their own. When a Marius is provisioned, the skills linked to it drive the
per-skill install instructions embedded in the invitation prompt.
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
    kind: str = "http"  # "http" (direct API) | "mcp" (future MCP server)
    source: str = "builtin"  # "builtin" | "custom"
    # Where the SKILL.md lives. A leading "/" means it is served by THIS API
    # (e.g. /static/skills/armarius-http/SKILL.md) and is resolved against the
    # public base URL when advertised to an agent.
    install_url: str | None = None
    # Optional inline install notes for custom skills.
    instructions: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def absolute_install_url(self, public_base_url: str) -> str | None:
        """Resolve install_url against the public base URL when it is relative."""
        if not self.install_url:
            return None
        if self.install_url.startswith("/"):
            return f"{public_base_url.rstrip('/')}{self.install_url}"
        return self.install_url
