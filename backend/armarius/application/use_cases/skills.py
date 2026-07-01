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

from armarius.application.use_cases.types import UowFactory
from armarius.domain.entities.skill import Skill
from armarius.shared.clock import utcnow

BACKEND_ROOT = Path(__file__).resolve().parents[3]
BUILTIN_SKILL_FILE = BACKEND_ROOT / "static" / "skills" / "armarius-http" / "SKILL.md"
BUILTIN_MCP_SKILL_FILE = BACKEND_ROOT / "static" / "skills" / "armarius-mcp" / "SKILL.md"

# The built-in skills seeded into every workspace. `armarius-mcp` is the preferred path
# (typed MCP tools — the agent never curls); `armarius-http` stays as a curl fallback for
# runtimes that can't host an MCP server.
BUILTIN_SKILLS: list[dict] = [
    {
        "slug": "armarius-mcp",
        "name": "Armarius MCP",
        "description": (
            "Work the Armarius workspace through typed MCP tools — enroll, claim tasks, "
            "comment & @mention, update status, publish artifacts. No curl."
        ),
        "source": "builtin",
        "source_url": "/static/skills/armarius-mcp/SKILL.md",
        "file": BUILTIN_MCP_SKILL_FILE,
    },
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
        """Idempotently ensure each built-in skill exists in the workspace."""
        async with self._uow() as uow:
            changed = False
            for spec in BUILTIN_SKILLS:
                if await uow.skills.get_by_slug(workspace_id, spec["slug"]) is not None:
                    continue
                files = {"SKILL.md": _read_text(spec["file"])}
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
            if changed:
                await uow.commit()

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
                raise LookupError("workspace not found")
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
            raise ValueError(
                "No SKILL.md found at that URL. Point at a folder (or repo) containing one."
            )
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
                raise LookupError("skill not found")
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
        raise ValueError("That doesn't look like a GitHub URL.")
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
        raise ValueError(f"GitHub returned {e.code}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise ValueError(f"Could not reach GitHub: {e.reason}") from e
    return out
