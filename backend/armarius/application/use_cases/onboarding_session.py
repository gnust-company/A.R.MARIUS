"""Onboarding use case (LLD §2.10, Sprint 7 / Phase G) — the Workspace Agent interviews
the Patron and, on ``finalize``, materialises the agreed plan into a real Project + roster.

The Workspace Agent is the workspace's host Marius (designated by ``WorkspaceAgentService``).
Sprint 7 wires the chat: the Patron talks, the Agent runs a **scripted playbook** (greet →
propose a roster derived from the objective → confirm), and ``finalize`` hands the plan to
``ProjectService.create_project`` (which enforces the hard one-leader-plus-workers rule).

The playbook is a small, pure, keyword-driven brain isolated below (``propose_plan`` /
``_respond``). That is deliberate: the repo runs end-to-end on the ``echo`` adapter with no
real gateway, so a deterministic brain keeps the onboarding tab honest and useful. Swapping
in a real LLM later means replacing exactly that brain — the session FSM, persistence and
``finalize → ProjectService`` path stay untouched.
"""

from __future__ import annotations

import re
from uuid import UUID

from armarius.application.use_cases.projects import ProjectService, RoleSpec
from armarius.application.use_cases.types import UowFactory
from armarius.application.use_cases.workspace_agent import WorkspaceAgentService
from armarius.domain.entities.onboarding import OnboardingSession
from armarius.shared.clock import utcnow

# ── the scripted onboarding brain (pure; swap for a real LLM later) ──────────────

_GREETING = (
    "Hi — I'm the Workspace Agent. Tell me what you'd like to build and I'll propose a "
    "team for it: the objective, who you need (e.g. frontend, backend, design), and I'll "
    "stand up the project with a Project Leader plus those worker roles."
)

# objective keyword → (role title, blurb). The first match per title becomes a worker seat.
_ROLE_KEYWORDS: list[tuple[list[str], str, str]] = [
    (["frontend", "ui", "react", "vue", "css", "web", "interface"],
     "Frontend", "Builds the user-facing UI."),
    (["backend", "api", "server", "database", "db", "endpoint", "service"],
     "Backend", "Builds the API and data layer."),
    (["design", "ux", "figma", "visual", "brand"],
     "Design", "Owns the visual and interaction design."),
    (["test", "qa", "review", "security", "quality", "audit"],
     "QA / Reviewer", "Reviews work and guards quality."),
    (["data", "ml", "analytics", "pipeline", "etl"],
     "Data", "Owns data and analytics."),
    (["devops", "infra", "deploy", "ci", "cloud"],
     "DevOps", "Owns infrastructure and releases."),
]

_STOPWORDS = {
    "a", "an", "the", "build", "create", "make", "for", "to", "of", "and", "with",
    "want", "need", "we", "i", "our", "my", "project", "app", "application", "system",
    "that", "this", "it", "on", "in", "new",
}

_CONFIRM = ["looks good", "looks right", "yes", "confirm", "confirmed", "ok", "okay",
            "create", "go ahead", "go for it", "perfect", "lgtm", "ship", "finalize", "do it"]
_RECONSIDER = ["no", "don't", "dont", "change", "add", "remove", "instead", "swap", "replace"]


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:120]
    return slug or "role"


def _project_name(objective: str) -> str:
    """Derive a short, human project name from the objective text."""
    words = [w for w in re.split(r"[^a-z0-9]+", objective.lower()) if w and w not in _STOPWORDS]
    name = " ".join(w.capitalize() for w in words[:4]) if words else "New Project"
    return name[:80]


def _leader_role() -> dict:
    return {"key": "leader", "title": "Project Leader", "seats": 1, "is_leader": True,
            "description": "Owns the plan and coordinates the roster."}


def _worker_spec(title: str) -> dict:
    """A worker role spec for ``title`` (title → blurb from the known vocabulary)."""
    blurb = next((b for ks, t, b in _ROLE_KEYWORDS if t == title), "")
    return {"key": _slug(title), "title": title, "seats": 1, "is_leader": False,
            "description": blurb}


def _match_role_titles(text: str) -> list[str]:
    """Every known role title the text mentions (by keyword), in vocab order, deduped.

    Used to resolve '<frontend>', 'the backend', 'a design role', … against the same
    keyword table ``propose_plan`` uses, so edits name roles the same way the initial
    proposal does.
    """
    low = text.lower()
    titles: list[str] = []
    seen: set[str] = set()
    for keywords, title, _blurb in _ROLE_KEYWORDS:
        if title in seen:
            continue
        if any(k in low for k in keywords):
            titles.append(title)
            seen.add(title)
    return titles


def propose_plan(objective: str) -> dict:
    """Derive ``{project_name, roles}`` from the objective (keyword heuristic).

    Always returns one Project Leader plus at least one worker role, so ``finalize`` can
    always satisfy the roster's hard rule. ``roles`` is a list of plain dicts the service
    turns into ``RoleSpec`` on finalize.
    """
    titles = _match_role_titles(objective)
    workers = ([_worker_spec(t) for t in titles] if titles else
               [_worker_spec("Frontend"), _worker_spec("Backend")])
    return {"project_name": _project_name(objective), "roles": [_leader_role(), *workers]}


def is_confirmation(text: str) -> bool:
    low = text.lower()
    if any(w in low for w in _RECONSIDER):
        return False
    return any(w in low for w in _CONFIRM)


# ── editing the running plan (#55) ───────────────────────────────────────────────
# The plan accumulates across turns: later messages edit the agreed roles instead of
# replacing the whole plan (which made every reply look the same — "100 lần như 1").
# Intent is read from verbs + the roles named in the message:

_REMOVE = ["remove", "drop", "without", "no more", "get rid", "delete"]
_ADD = ["add", "include", "also need", "need a", "need some", "bring in", "plus a", "plus an"]
_SWAP = ["swap", "replace", "switch", "instead of", "change to", "change for"]


def _apply_edit(roles: list[dict], text: str) -> tuple[list[dict], str | None]:
    """Apply a single add/remove/swap edit to ``roles`` (worker roles only).

    Returns ``(new_roles, note)`` where ``note`` is a short phrase describing what changed
    (or ``None`` when the message isn't an edit). Mutates a copy. Worker order is stable;
    a swap keeps the edited seat in place so the roster doesn't reshuffle on every turn.
    """
    low = text.lower()
    mentioned = _match_role_titles(text)
    current_titles = [r["title"] for r in roles]

    # swap X for/with Y → drop X, insert Y at X's position.
    if any(v in low for v in _SWAP) and len(mentioned) >= 1:
        out_target = next((t for t in mentioned if t in current_titles), None)
        in_target = next((t for t in mentioned if t not in current_titles), None)
        if out_target is not None and in_target is not None:
            idx = current_titles.index(out_target)
            new_roles = [r for r in roles if r["title"] != out_target]
            new_roles.insert(idx, _worker_spec(in_target))
            return new_roles, f"swapped {out_target} → {in_target}"

    # remove X → drop the first mentioned role that's present.
    if any(v in low for v in _REMOVE) and mentioned:
        target = next((t for t in mentioned if t in current_titles), None)
        if target is not None:
            new_roles = [r for r in roles if r["title"] != target]
            return new_roles, f"removed {target}"

    # add Y → append any mentioned role not already seated (keep one seat per title).
    if any(v in low for v in _ADD):
        additions = [t for t in mentioned if t not in current_titles]
        if additions:
            new_roles = [*roles, *(_worker_spec(t) for t in additions)]
            return new_roles, f"added {', '.join(additions)}"

    return roles, None


def _respond(collected: dict, patron_text: str) -> tuple[str, dict]:
    """Produce the Workspace Agent's next reply + the updated plan (pure).

    The plan is cumulative: the first objective proposes an initial roster, and every
    later message either locks the plan (confirmation), edits it (add/remove/swap), or
    folds in any new roles it mentions. The project name is set once from the first
    objective and kept stable afterwards (#55)."""
    text = patron_text.strip()
    roles = [r for r in (collected.get("roles") or []) if not r.get("is_leader")]
    has_plan = bool(roles)

    # Confirming an existing plan locks it (no rewrite).
    if has_plan and is_confirmation(text):
        updated = {**collected, "ready": True}
        reply = (
            "Locked in. Hit “Create project” and I'll stand it up — a Project "
            "Leader seat plus the worker roles we agreed on, all in setup so you can grant "
            "agents next. Want anything else first? Just tell me."
        )
        return reply, updated

    project_name = collected.get("project_name")
    objective = collected.get("objective") or text.strip()

    note = None
    if has_plan:
        # Editing a running plan: try add/remove/swap first, then fold in any newly
        # mentioned roles. Roles already seated are never duplicated.
        roles, note = _apply_edit(roles, text)
        if note is None:
            extras = [t for t in _match_role_titles(text)
                      if t not in {r["title"] for r in roles}]
            if extras:
                roles = [*roles, *(_worker_spec(t) for t in extras)]
                note = f"added {', '.join(extras)}"
    else:
        # First proposal: derive name + roster from the objective.
        plan = propose_plan(text)
        roles = [r for r in plan["roles"] if not r["is_leader"]]
        if project_name is None:
            project_name = plan["project_name"]

    if not project_name:
        project_name = _project_name(objective)

    updated = {
        **collected,
        "objective": objective,
        "project_name": project_name,
        "roles": [_leader_role(), *roles],
        "ready": False,
    }

    worker_lines = "\n".join(
        f"  • {r['title']} — {r['description']}" for r in roles if r.get("description")
    ) or "  (no worker seats yet)"
    lead = (
        f"{note.capitalize()} — the plan now is **{project_name}** with one Project Leader plus:\n"
        if note else
        f"Got it — I'll set up **{project_name}** with one Project Leader plus:\n"
    )
    reply = (
        f"{lead}{worker_lines}\n\n"
        "If that looks right, say “looks good” (or hit Create). Want to add or swap a "
        "role? Tell me what you need and I'll revise."
    )
    return reply, updated


def plan_from_collected(collected: dict) -> dict:
    """Materialise the accumulated plan into ``{name, objective, roles: [RoleSpec]}``.

    Falls back to a sensible default if the Patron never gave an objective, so finalize is
    always able to create a valid project + roster (the Sprint-7 DoD).
    """
    raw_roles = collected.get("roles") or propose_plan("")["roles"]
    roles = [
        RoleSpec(
            key=r["key"],
            title=r.get("title", r["key"]),
            seats=int(r.get("seats", 1)),
            is_leader=bool(r.get("is_leader", False)),
            description=r.get("description", ""),
        )
        for r in raw_roles
    ]
    name = collected.get("project_name") or "New Project"
    objective = collected.get("objective") or name
    return {"name": name, "objective": objective, "roles": roles}


# ── the use case ──────────────────────────────────────────────────────────────────


class OnboardingService:
    def __init__(
        self,
        uow_factory: UowFactory,
        projects: ProjectService,
        workspace_agent: WorkspaceAgentService,
    ) -> None:
        self._uow = uow_factory
        self._projects = projects
        self._ws_agent = workspace_agent

    async def start(self, workspace_id: UUID) -> OnboardingSession:
        """Open an onboarding chat for a workspace (idempotent agent designation first)."""
        # Designate the Workspace Agent + onboarder skill so the host exists before we greet.
        await self._ws_agent.ensure_workspace_agent(workspace_id)
        now = utcnow()
        async with self._uow() as uow:
            if await uow.workspaces.get(workspace_id) is None:
                raise LookupError("workspace not found")
            session = OnboardingSession(
                workspace_id=workspace_id, created_at=now, updated_at=now
            )
            session.add_turn("agent", _GREETING, now)
            await uow.onboardings.add(session)
            await uow.commit()
            return session

    async def message(self, session_id: UUID, text: str) -> OnboardingSession:
        """Append a Patron turn and let the Workspace Agent respond (scripted)."""
        now = utcnow()
        async with self._uow() as uow:
            session = await self._open(uow, session_id)
            session.add_turn("patron", text, now)
            reply, collected = _respond(session.collected, text)
            session.collected = collected
            session.add_turn("agent", reply, now)
            session.updated_at = now
            await uow.onboardings.update(session)
            await uow.commit()
            return session

    async def finalize(
        self, session_id: UUID, *, created_by_user_id: str | None = None
    ) -> OnboardingSession:
        """Materialise the agreed plan into a real Project + roster (``setup`` status)."""
        async with self._uow() as uow:
            session = await self._open(uow, session_id)
            plan = plan_from_collected(session.collected)
            workspace_id = session.workspace_id
            # Snapshot the plan into the transcript so the resolved chat records what was built.
            role_names = ", ".join(r.title for r in plan["roles"])
            session.add_turn(
                "agent",
                f"Creating **{plan['name']}** with: {role_names}.",
                utcnow(),
            )

        # ProjectService opens its own UoW (separate session) and enforces the roster rule.
        project = await self._projects.create_project(
            workspace_id=workspace_id,  # type: ignore[arg-type]
            name=plan["name"],
            roles=plan["roles"],
            objective=plan["objective"],
            created_by_user_id=created_by_user_id,
        )

        async with self._uow() as uow:
            fresh = await uow.onboardings.get(session_id)
            if fresh is None:
                raise LookupError("onboarding session not found")
            fresh.finalize(project.id)  # OPEN → FINALIZED
            fresh.updated_at = utcnow()
            await uow.onboardings.update(fresh)
            await uow.commit()
            return fresh

    async def abandon(self, session_id: UUID) -> OnboardingSession:
        now = utcnow()
        async with self._uow() as uow:
            session = await self._open(uow, session_id)
            session.abandon()  # OPEN → ABANDONED
            session.updated_at = now
            await uow.onboardings.update(session)
            await uow.commit()
            return session

    async def get(self, session_id: UUID) -> OnboardingSession | None:
        async with self._uow() as uow:
            return await uow.onboardings.get(session_id)

    async def active_for(self, workspace_id: UUID) -> OnboardingSession | None:
        """The workspace's most recent OPEN session, if any (one live chat at a time)."""
        async with self._uow() as uow:
            sessions = await uow.onboardings.list_by_workspace(workspace_id)
        return next((s for s in sessions if s.status.value == "open"), None)

    async def _open(self, uow, session_id: UUID) -> OnboardingSession:  # noqa: ANN001
        session = await uow.onboardings.get(session_id)
        if session is None:
            raise LookupError("onboarding session not found")
        return session
