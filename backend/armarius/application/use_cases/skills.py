"""Skill Shop use cases — author, import, edit, and list skills.

A skill is a small file tree rooted at SKILL.md. Three ways to create one:
- built-in: shipped with every workspace (armarius-http).
- manual: generated from a SKILL.md template; the author edits it and may add sibling
  files/folders (scripts/, references/, …).
- imported: cloned from a GitHub folder URL — we detect SKILL.md, pull only that
  folder, and let the user view/edit the sibling files and save.

name/description always come from the SKILL.md YAML frontmatter. Skills are
workspace-scoped (not shared across workspaces).
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from armarius.application.ports.unit_of_work import UnitOfWork
from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.skill import Skill
from armarius.shared.clock import utcnow
from armarius.shared.errors import BadRequest, NotFound

BACKEND_ROOT = Path(__file__).resolve().parents[3]
BUILTIN_SKILL_FILE = BACKEND_ROOT / "static" / "skills" / "armarius-http" / "SKILL.md"

# The built-in skills seeded into every workspace.
#
# `armarius-mcp` used to sit above this one and was described as the preferred path. It was
# removed on 2026-08-26 along with the package it pointed at. Both halves of it had stopped
# being true: it authenticated with the agent's long-lived token, which FR-014a leaves no
# room for, and it asked the agent to install a tool server into its own machine-wide
# configuration, which FR-013a forbids outright. A skill that teaches an agent to do a thing
# the system will refuse is worse than no skill.
#
# The callback toolset itself is not gone as an idea — it comes back per run, injected by the
# daemon and carrying that run's own token (FR-013, FR-013a, T061). It is simply not
# something an agent installs for itself any more.
BUILTIN_SKILLS: list[dict] = [
    {
        "slug": "armarius-http",
        "name": "Armarius HTTP API",
        "description": (
            "Call the Armarius workspace API directly with curl — claim tasks, "
            "comment & @mention teammates, update status, publish artifacts."
        ),
        "source": "builtin",
        "source_url": "/static/skills/armarius-http/SKILL.md",
        "file": BUILTIN_SKILL_FILE,
    },
]

_SKILL_MD_NAMES = ("SKILL.md", "skill.md")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "skill"


def parse_frontmatter(text: str) -> dict[str, str]:
    """Read name/description from a SKILL.md YAML frontmatter block."""
    m = re.match(r"^\s*---\s*\n(.*?)\n---\s*\n?", text, re.DOTALL)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).split("\n"):
        kv = re.match(r"^(\w+)\s*:\s*(.*)$", line)
        if not kv:
            continue
        key, val = kv.group(1), kv.group(2).strip()
        out[key] = val[1:-1] if len(val) >= 2 and val[0] in "\"'" else val
    return out


def _build_frontmatter(meta: dict[str, str]) -> str:
    lines = ["---"]
    for key in ("name", "description"):
        if meta.get(key):
            lines.append(f"{key}: {meta[key]}")
    lines.append("---")
    return "\n".join(lines)


def derive_meta(files: dict[str, str]) -> tuple[str, str]:
    """Return (name, description) parsed from the skill's SKILL.md."""
    for name in _SKILL_MD_NAMES:
        if name in files:
            fm = parse_frontmatter(files[name])
            return fm.get("name", ""), fm.get("description", "")
    return "", ""


def manual_template(name: str, description: str = "") -> str:
    """A starter SKILL.md the author fleshes out."""
    fm = _build_frontmatter({"name": name or "Untitled skill", "description": description})
    return (
        f"{fm}\n\n"
        f"# {name or 'Untitled skill'}\n\n"
        "Describe what this skill lets an agent do, and when the agent should reach for it.\n\n"
        "## When to use\n\n"
        "- ...\n\n"
        "## How it works\n\n"
        "1. ...\n\n"
        "## Files in this skill\n\n"
        "- `SKILL.md` — this file (instructions).\n"
        "- Add sibling files/folders (e.g. `scripts/`, `references/`) as needed.\n"
    )


class SkillService:
    def __init__(self, uow_factory: UowFactory) -> None:
        self._uow = uow_factory

    # ------------------------------------------------------------------ built-ins
    async def seed_builtins(self, workspace_id: UUID) -> None:
        """Idempotently ensure each built-in skill exists in the workspace.

        Also ships content updates: when the on-disk SKILL.md changed since this
        workspace was seeded, the stored copy is refreshed — unless the owner has
        edited it (update_files sets updated_at; a shipped copy never has one).

        And **prunes de-listed builtins**: a `source="builtin"` skill whose slug is no
        longer shipped (e.g. the retired `armarius-onboarder`) is deleted, so workspaces
        seeded by an older version self-clean on the next load. Only builtins are pruned —
        manual/imported skills are never touched.
        """
        builtin_slugs = {spec["slug"] for spec in BUILTIN_SKILLS}
        async with self._uow() as uow:
            changed = False
            for spec in BUILTIN_SKILLS:
                files = {"SKILL.md": _read_text(spec["file"])}
                existing = await uow.skills.get_by_slug(workspace_id, spec["slug"])
                if existing is not None:
                    if existing.updated_at is None and existing.files != files:
                        existing.files = files
                        existing.name = spec["name"]
                        existing.description = spec["description"]
                        await uow.skills.update(existing)
                        changed = True
                    continue
                await uow.skills.add(
                    Skill(
                        workspace_id=workspace_id,
                        slug=spec["slug"],
                        name=spec["name"],
                        description=spec["description"],
                        source="builtin",
                        source_url=spec["source_url"],
                        files=files,
                        created_at=utcnow(),
                    )
                )
                changed = True
            for sk in await uow.skills.list_by_workspace(workspace_id):
                if sk.source == "builtin" and sk.slug not in builtin_slugs:
                    await uow.skills.remove(sk.id)
                    await self._forget_everywhere(uow, workspace_id, sk)
                    changed = True
            if changed:
                await uow.commit()

    async def _forget_everywhere(
        self, uow: UnitOfWork, workspace_id: UUID, gone: Skill
    ) -> None:
        """Take a deleted skill out of everything that still names it.

        Deleting the row is only half of deleting the skill. What is left behind is a link
        on an agent — an id in a list, a name in the list beside it, a line in the install
        record — pointing at nothing. Nothing crashes: whoever resolves those ids drops the
        ones it cannot find, which is exactly why this rots quietly instead of being noticed.
        What it costs is that the two lists stop agreeing about how many skills an agent has,
        and the record keeps claiming an agent installed something that no longer exists.

        The names are rebuilt from what is actually left rather than filtered in place, so
        the two lists cannot drift apart even a little: one is derived from the other, here,
        in the same write.
        """
        doomed = str(gone.id)
        for marius in await uow.mariuses.list_by_workspace(workspace_id):
            if doomed not in marius.skill_ids:
                continue
            marius.skill_ids = [s for s in marius.skill_ids if s != doomed]
            kept = await uow.skills.list_by_ids([UUID(s) for s in marius.skill_ids])
            by_id = {str(sk.id): sk.name for sk in kept}
            marius.skills = [by_id[s] for s in marius.skill_ids if s in by_id]
            await uow.mariuses.update(marius)

        for project in await uow.projects.list_by_workspace(workspace_id):
            for role in await uow.roles.list_by_project(project.id):
                if doomed not in role.skill_ids:
                    continue
                role.skill_ids = [s for s in role.skill_ids if s != doomed]
                await uow.roles.update(role)

    # --------------------------------------------------------------------- queries
    async def list_skills(self, workspace_id: UUID) -> Sequence[Skill]:
        await self.seed_builtins(workspace_id)
        async with self._uow() as uow:
            return await uow.skills.list_by_workspace(workspace_id)

    async def get_skill(self, skill_id: UUID) -> Skill | None:
        async with self._uow() as uow:
            return await uow.skills.get(skill_id)

    # ---------------------------------------------------------------------- create
    async def _persist(self, workspace_id: UUID, skill: Skill) -> Skill:
        async with self._uow() as uow:
            if await uow.workspaces.get(workspace_id) is None:
                raise NotFound("workspace_not_found")
            name, desc = derive_meta(skill.files)
            if name:
                skill.name = name
            if desc:
                skill.description = desc
            slug = _slugify(skill.name)
            if await uow.skills.get_by_slug(workspace_id, slug) is not None:
                slug = f"{slug}-{utcnow().strftime('%H%M%S')}"
            skill.slug = slug
            skill.workspace_id = workspace_id
            skill.created_at = utcnow()
            created = await uow.skills.add(skill)
            await uow.commit()
            return created

    async def create_manual(
        self, *, workspace_id: UUID, name: str, description: str = ""
    ) -> Skill:
        """Create a skill from a generated SKILL.md template."""
        skill = Skill(
            name=name,
            source="manual",
            files={"SKILL.md": manual_template(name, description)},
        )
        return await self._persist(workspace_id, skill)

    async def import_from_url(
        self, *, workspace_id: UUID, url: str
    ) -> Skill:
        """Clone a skill from a GitHub folder URL (detect SKILL.md, pull that folder)."""
        files = await clone_github_folder(url)
        if not any(n in files for n in _SKILL_MD_NAMES):
            raise BadRequest("skill_md_not_found")
        name, desc = derive_meta(files)
        skill = Skill(
            name=name or _name_from_url(url),
            description=desc,
            source="imported",
            source_url=url,
            files=files,
        )
        return await self._persist(workspace_id, skill)

    # ---------------------------------------------------------------------- update
    async def update_files(self, skill_id: UUID, files: dict[str, str]) -> Skill:
        """Save the edited file tree; re-derive name/description from SKILL.md."""
        async with self._uow() as uow:
            skill = await uow.skills.get(skill_id)
            if skill is None:
                raise NotFound("skill_not_found")
            skill.files = {k: v for k, v in files.items() if v is not None}
            name, desc = derive_meta(skill.files)
            if name:
                skill.name = name
            if desc is not None:
                skill.description = desc
            skill.updated_at = utcnow()
            updated = await uow.skills.update(skill)
            await uow.commit()
            return updated

    async def delete_skill(self, skill_id: UUID) -> None:
        """Delete a workspace skill. Built-in skills are re-seeded on every list, so they
        can't be deleted (the guard keeps the Shop's shipped entries intact)."""
        async with self._uow() as uow:
            skill = await uow.skills.get(skill_id)
            if skill is None:
                raise NotFound("skill_not_found")
            if skill.source == "builtin":
                raise BadRequest("builtin_skill_undeletable")
            await uow.skills.remove(skill_id)
            if skill.workspace_id is not None:
                await self._forget_everywhere(uow, skill.workspace_id, skill)
            await uow.commit()

    async def resolve(self, skill_ids: list[str]) -> Sequence[Skill]:
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


# --------------------------------------------------------------------- helpers
def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _name_from_url(url: str) -> str:
    m = re.search(r"github\.com[:/]([^/]+)/([^/]+)", url)
    if m:
        repo = re.sub(r"\.git$", "", m.group(2))
        return f"{m.group(1)}/{repo}"
    seg = url.rstrip("/").split("/")[-1]
    return re.sub(r"\.(md|markdown)$", "", seg) or "skill"


_GH_URL_RE = re.compile(
    r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?(?:/tree/([^/]+)(?:/(.+))?)?/?$"
)


def _parse_github_url(url: str) -> tuple[str, str, str, str]:
    """Return (owner, repo, ref, path) from a GitHub URL, or raise ValueError."""
    m = _GH_URL_RE.search(url.strip())
    if not m:
        raise BadRequest("not_a_github_url")
    owner, repo, ref, path = m.group(1), m.group(2), m.group(3) or "main", m.group(4) or ""
    return owner, repo, ref, path


def _gh_get(url: str) -> object:
    req = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json", "User-Agent": "Armarius"}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 — trusted GH API
        return json.loads(resp.read().decode("utf-8"))


def _walk_contents(owner: str, repo: str, ref: str, path: str, out: dict[str, str],
                   root: str, depth: int = 0) -> None:
    """Recursively fetch a GitHub folder into `out` keyed by path-relative-to-root."""
    if depth > 6:
        return
    api = (
        f"https://api.github.com/repos/{owner}/{repo}/contents/"
        f"{urllib.parse.quote(path, safe='/')}?ref={urllib.parse.quote(ref, safe='')}"
    )
    items = _gh_get(api)
    if isinstance(items, dict):  # a single file
        items = [items]
    if not isinstance(items, list):
        return
    for it in items:
        itype = it.get("type")
        ipath = it.get("path", "")
        rel = ipath[len(root):].lstrip("/") if root and ipath.startswith(root) else ipath
        if itype == "file":
            content_b64 = it.get("content")
            if content_b64 is None and it.get("url"):
                # Directory listings omit file content; fetch the file object. The
                # item `url` already carries the ?ref= query, so don't re-append it.
                fetched = _gh_get(it["url"])
                content_b64 = fetched.get("content") if isinstance(fetched, dict) else None
            if content_b64 is not None:
                try:
                    out[rel] = base64.b64decode(content_b64).decode("utf-8", errors="replace")
                except (ValueError, OSError):
                    continue
            if len(out) >= 100:
                return
        elif itype == "dir":
            _walk_contents(owner, repo, ref, ipath, out, root, depth + 1)
            if len(out) >= 100:
                return


async def clone_github_folder(url: str) -> dict[str, str]:
    """Fetch a GitHub folder as {relative_path: content}, rooted at the linked folder."""
    owner, repo, ref, path = _parse_github_url(url)
    out: dict[str, str] = {}
    try:
        await asyncio.to_thread(_walk_contents, owner, repo, ref, path, out, path)
    except urllib.error.HTTPError as e:
        raise BadRequest("github_error", status=e.code, reason=e.reason) from e
    except urllib.error.URLError as e:
        raise BadRequest("github_unreachable", reason=e.reason) from e
    return out
