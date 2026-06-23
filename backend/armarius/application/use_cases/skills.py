"""Skill Shop use cases — list/create skills and seed the built-in skill.

Skills are workspace-scoped. Every workspace ships with the built-in `armarius-http`
skill (direct BE API access). Users can submit custom skills to their own workspace;
those are NOT shared across workspaces.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from uuid import UUID

from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.skill import Skill
from armarius.shared.clock import utcnow

# The single built-in skill seeded into every workspace. `install_url` is relative —
# it is resolved against the public base URL when advertised to an agent, so it stays
# correct behind any host/port/proxy (mirrors how the rest of the API is addressed).
BUILTIN_SKILLS: list[dict] = [
    {
        "slug": "armarius-http",
        "name": "Armarius HTTP API",
        "description": (
            "Call the Armarius workspace API directly with curl — claim tasks, "
            "comment & @mention teammates, update status, publish artifacts."
        ),
        "kind": "http",
        "source": "builtin",
        "install_url": "/static/skills/armarius-http/SKILL.md",
    },
]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "skill"


class SkillService:
    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow = uow_factory

    async def seed_builtins(self, workspace_id: UUID) -> None:
        """Idempotently ensure each built-in skill exists in the workspace."""
        async with self._uow() as uow:
            changed = False
            for spec in BUILTIN_SKILLS:
                existing = await uow.skills.get_by_slug(workspace_id, spec["slug"])
                if existing is not None:
                    continue
                await uow.skills.add(
                    Skill(
                        workspace_id=workspace_id,
                        slug=spec["slug"],
                        name=spec["name"],
                        description=spec["description"],
                        kind=spec["kind"],
                        source=spec["source"],
                        install_url=spec.get("install_url"),
                        created_at=utcnow(),
                    )
                )
                changed = True
            if changed:
                await uow.commit()

    async def list_skills(self, workspace_id: UUID) -> Sequence[Skill]:
        """List a workspace's skills, seeding built-ins on first read (backfill)."""
        await self.seed_builtins(workspace_id)
        async with self._uow() as uow:
            return await uow.skills.list_by_workspace(workspace_id)

    async def create_skill(
        self,
        *,
        workspace_id: UUID,
        name: str,
        description: str = "",
        kind: str = "http",
        install_url: str | None = None,
        instructions: str | None = None,
    ) -> Skill:
        """Submit a custom skill to a workspace's Skill Shop."""
        async with self._uow() as uow:
            if await uow.workspaces.get(workspace_id) is None:
                raise LookupError("workspace not found")
            slug = _slugify(name)
            # Disambiguate against an existing slug in this workspace.
            if await uow.skills.get_by_slug(workspace_id, slug) is not None:
                slug = f"{slug}-{utcnow().strftime('%H%M%S')}"
            skill = Skill(
                workspace_id=workspace_id,
                slug=slug,
                name=name,
                description=description,
                kind=kind,
                source="custom",
                install_url=install_url,
                instructions=instructions,
                created_at=utcnow(),
            )
            created = await uow.skills.add(skill)
            await uow.commit()
            return created

    async def resolve(self, skill_ids: list[str]) -> Sequence[Skill]:
        """Resolve a list of skill-id strings to Skill entities (order-preserving)."""
        if not skill_ids:
            return []
        uuids: list[UUID] = []
        for s in skill_ids:
            try:
                uuids.append(UUID(s))
            except (ValueError, TypeError):
                continue
        async with self._uow() as uow:
            found = {str(sk.id): sk for sk in await uow.skills.list_by_ids(uuids)}
        return [found[s] for s in skill_ids if s in found]
