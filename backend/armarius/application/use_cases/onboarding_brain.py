"""The onboarding brain — turns a Patron conversation into a project + roster draft (#61).

Two implementations behind one shape:

* ``DeterministicBrain`` (the active default) walks a fixed, ordered plan of questions, each
  a *window of tick-select options* (with a free-text "Other" escape), accumulates the answers,
  and on the last one emits a ``complete`` draft. It is pure and fully testable — it replaces
  the old keyword template that re-rendered "Got it — I'll set up **D**…" every turn.
* A real Workspace-Agent runtime can drive the SAME contract instead: it receives
  ``build_onboarding_guide_prompt`` and posts its questions/completion back through the
  agent-facing endpoints. ``DeterministicBrain`` is the guaranteed fallback when no such
  runtime is wired, so onboarding always works.

The question/answer/complete shapes are stored on ``OnboardingSession.collected`` so both the
API and the UI read one contract:

    collected = {
        "phase": "asking" | "complete",
        "answers": {<key>: <resolved answer text>},
        "pending_question": {"key","question","options":[{"id","label"}],"multi"} | None,
        "draft": {name, objective, success_metrics, target_date, context, roster:[...]} | None,
    }
"""

from __future__ import annotations

import re

# ── role vocabulary (shared by the brain, proposal and finalize) ─────────────────
# objective/role keyword → (role title, blurb). One worker seat per matched title.
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

_ROLE_TITLES = [title for _kw, title, _blurb in _ROLE_KEYWORDS]

_STOPWORDS = {
    "a", "an", "the", "build", "create", "make", "for", "to", "of", "and", "with",
    "want", "need", "we", "i", "our", "my", "project", "app", "application", "system",
    "that", "this", "it", "on", "in", "new",
}


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
            "description": "Owns the plan and coordinates the roster.", "skills": []}


def _worker_spec(title: str) -> dict:
    """A worker role spec for ``title`` (title → blurb from the known vocabulary)."""
    blurb = next((b for _ks, t, b in _ROLE_KEYWORDS if t == title), "")
    return {"key": _slug(title), "title": title, "seats": 1, "is_leader": False,
            "description": blurb, "skills": []}


def _match_role_titles(text: str) -> list[str]:
    """Every known role title the text mentions (by keyword), in vocab order, deduped."""
    low = text.lower()
    titles: list[str] = []
    for keywords, title, _blurb in _ROLE_KEYWORDS:
        if title in titles:
            continue
        if any(k in low for k in keywords):
            titles.append(title)
    return titles


# ── the question plan (the injected guide, encoded as code) ──────────────────────
_FREE_TEXT = {"id": "other", "label": "Other (I'll type it)"}
# One key per ordered step; the brain asks them in this order.
_STEPS = ["objective", "name", "roles", "metric", "target", "context"]


def _options(*labels: str) -> list[dict]:
    return [{"id": str(i + 1), "label": label} for i, label in enumerate(labels)]


def is_free_text_option(label: str) -> bool:
    return bool(re.search(r"i'?ll type|type it|type my|other|custom|free\s*text", label, re.I))


def _question_for(step: str, answers: dict) -> dict:
    """Build the next question (options may depend on earlier answers)."""
    if step == "objective":
        return {
            "key": "objective",
            "question": "What are you building?",
            "options": [
                *_options(
                    "A web app", "An API / backend service",
                    "A mobile app", "A data pipeline / automation",
                ),
                _FREE_TEXT,
            ],
            "multi": False,
        }
    if step == "name":
        suggested = _project_name(str(answers.get("objective", "")))
        return {
            "key": "name",
            "question": "What should we call the project?",
            "options": [{"id": "suggested", "label": suggested},
                        {"id": "other", "label": "Something else (I'll type it)"}],
            "multi": False,
        }
    if step == "roles":
        return {
            "key": "roles",
            "question": "Which roles should the team have? (pick one or more)",
            "options": _options(*_ROLE_TITLES),
            "multi": True,
        }
    if step == "metric":
        return {
            "key": "metric",
            "question": "How will you measure success? (optional)",
            "options": [
                *_options("Ship it", "Users adopt it", "Hit a performance target",
                          "Skip for now"),
                _FREE_TEXT,
            ],
            "multi": False,
        }
    if step == "target":
        return {
            "key": "target",
            "question": "Any target date?",
            "options": [
                *_options("This week", "This month", "This quarter", "No deadline"),
                _FREE_TEXT,
            ],
            "multi": False,
        }
    # context
    return {
        "key": "context",
        "question": "Anything else we should know?",
        "options": [{"id": "1", "label": "No, that's it"},
                    {"id": "other", "label": "Yes (I'll type it)"}],
        "multi": False,
    }


def _roster_from_titles(titles: list[str]) -> list[dict]:
    workers = [_worker_spec(t) for t in titles if t in _ROLE_TITLES]
    if not workers:  # a project needs at least one worker seat (hard roster rule)
        workers = [_worker_spec("Frontend"), _worker_spec("Backend")]
    return [_leader_role(), *workers]


def _build_draft(answers: dict) -> dict:
    """Assemble the final project + roster draft from the accumulated answers."""
    objective = str(answers.get("objective", "")).strip() or "New project"
    name = str(answers.get("name", "")).strip() or _project_name(objective)

    raw_roles = str(answers.get("roles", ""))
    titles = [t.strip() for t in raw_roles.split(",") if t.strip()]
    roster = _roster_from_titles(titles)

    metric = str(answers.get("metric", "")).strip()
    success_metrics = None if not metric or metric.lower().startswith("skip") else {"goal": metric}

    target = str(answers.get("target", "")).strip()
    extra = str(answers.get("context", "")).strip()
    context_bits = []
    if target and target.lower() != "no deadline":
        context_bits.append(f"Target: {target}")
    if extra and not extra.lower().startswith(("no", "that's it")):
        context_bits.append(extra)
    context = " · ".join(context_bits) or None

    return {
        "name": name,
        "objective": objective,
        "success_metrics": success_metrics,
        "target_date": None,  # kept in context; free-typed real dates handled at finalize
        "context": context,
        "roster": roster,
    }


class DeterministicBrain:
    """A fixed question plan — options + free-text — that accumulates a real draft (#61)."""

    def start(self, collected: dict) -> dict:
        answers: dict = {}
        return {
            **collected,
            "phase": "asking",
            "answers": answers,
            "pending_question": _question_for(_STEPS[0], answers),
            "draft": None,
        }

    def answer(self, collected: dict, value: str) -> dict:
        pending = collected.get("pending_question") or {}
        key = pending.get("key")
        answers = dict(collected.get("answers") or {})
        if key is not None:
            answers[key] = value

        # Advance to the next unanswered step in plan order.
        next_step = next((s for s in _STEPS if s not in answers), None)
        if next_step is None:
            draft = _build_draft(answers)
            return {**collected, "phase": "complete", "answers": answers,
                    "pending_question": None, "draft": draft}
        return {**collected, "phase": "asking", "answers": answers,
                "pending_question": _question_for(next_step, answers), "draft": None}


def build_onboarding_guide_prompt(*, base_url: str, session_id: str, workspace_name: str) -> str:
    """The guide injected into a real Workspace-Agent runtime (replaces the Onboarder skill).

    Teaches the agent to interview the Patron ONE question at a time as tick-select options and
    finish with a project + roster draft — the same contract ``DeterministicBrain`` produces.
    """
    endpoint = f"{base_url}/agent/onboarding/{session_id}"
    return (
        "ARMARIUS · PROJECT ONBOARDING\n\n"
        f"You are the Workspace Agent for '{workspace_name}'. Interview the owner and stand up a "
        "new project. Ask 5-8 focused questions, ONE AT A TIME, and WAIT for each answer.\n\n"
        "PROTOCOL — one question per call:\n"
        f"- POST each question to {endpoint}/question ; then STOP and wait for the answer.\n"
        "- The server returns HTTP 409 if you send a new question while the previous is "
        "unanswered — wait, do not retry.\n"
        "- When the owner answers, decide the single next question from the running context.\n\n"
        "Cover: what they're building (objective), a short project name, which worker roles the "
        "team needs, how success is measured, a target date, and finally 'anything else?'.\n\n"
        "QUESTION body (send exactly this shape):\n"
        '{"question":"...","options":[{"id":"1","label":"..."},{"id":"2","label":"..."}],'
        '"multi":false}\n'
        "  Include a free-text escape when useful: an option whose label contains "
        '"I\'ll type it".\n'
        "  Set multi=true when several options can be picked (e.g. roles).\n\n"
        "When you have enough, POST the final draft to "
        f"{endpoint}/complete :\n"
        '{"project":{"name":"...","objective":"...","success_metrics":{"goal":"..."},'
        '"target_date":null,"context":"..."},'
        '"roster":[{"title":"Project Leader","seats":1,"is_leader":true},'
        '{"title":"Frontend","seats":1,"is_leader":false}]}\n'
        "The roster MUST have exactly one leader (is_leader=true) plus at least one worker.\n"
    )
