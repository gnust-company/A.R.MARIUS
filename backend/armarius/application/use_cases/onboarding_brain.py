"""Onboarding guide — the prompt injected into a real Workspace Agent (#61, v3).

There is NO scripted brain here. Project setup is the Workspace Agent's job: the agent is a
real runtime behind Hermes that must be **online and wake-able**. On ``start``/``answer`` the
``OnboardingService`` wakes it through its adapter with the guide prompt below; the guided agent
interviews the Patron ONE question at a time and posts each question (or its final draft) back
through the agent-facing callbacks in ``presentation/api/agent.py``. If the agent is not online,
or a wake fails, the service abandons the session and surfaces a 409 — there is no fallback.

The shared question/answer/complete contract lives on ``OnboardingSession.collected`` so the API
and the UI read one shape::

    collected = {
        "phase": "asking" | "complete",
        "answers": {<key>: <resolved answer text>},
        "pending_question": {"key","question","options":[{"id","label"}],"multi"} | None,
        "draft": {name, objective, success_metrics, target_date, context, roster:[...]} | None,
    }
"""

from __future__ import annotations

import re

_STOPWORDS = {
    "a", "an", "the", "build", "create", "make", "for", "to", "of", "and", "with",
    "want", "need", "we", "i", "our", "my", "project", "app", "application", "system",
    "that", "this", "it", "on", "in", "new",
}


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:120]
    return slug or "role"


def _project_name(objective: str) -> str:
    """Derive a short, human project name from the objective text (finalize fallback)."""
    words = [w for w in re.split(r"[^a-z0-9]+", objective.lower()) if w and w not in _STOPWORDS]
    name = " ".join(w.capitalize() for w in words[:4]) if words else "New Project"
    return name[:80]


def _leader_role() -> dict:
    """The canonical Project Leader roster row (finalize fallback when the draft omits it)."""
    return {"key": "leader", "title": "Project Leader", "seats": 1, "is_leader": True,
            "description": "Owns the plan and coordinates the roster.", "skills": []}


def is_free_text_option(label: str) -> bool:
    """An option whose label invites a typed answer (mirrors the guide's free-text escape)."""
    return bool(re.search(r"i'?ll type|type it|type my|other|custom|free\s*text", label, re.I))


def build_onboarding_guide_prompt(*, base_url: str, session_id: str, workspace_name: str) -> str:
    """The guide injected into the real Workspace Agent on the first wake of a session.

    Onboarding is injected into the prompt, not shipped as a skill. The agent interviews the
    Patron ONE question at a time following the ordered FIELD PLAN below (each field maps to the
    final draft body), then posts the draft. The agent posts its questions/completion back
    through the agent-facing endpoints; the service reconciles them onto
    ``OnboardingSession.collected``. The ordered plan keeps a weak model on the rails instead of
    circling implementation detail.
    """
    endpoint = f"{base_url}/agent/onboarding/{session_id}"
    return (
        "ARMARIUS · PROJECT ONBOARDING\n\n"
        f"You are the Workspace Agent for '{workspace_name}'. Interview the owner and stand up a "
        "new project by working through the FIELD PLAN below, ONE question per turn, in order.\n\n"
        "PROTOCOL — one question per call:\n"
        f"- POST each question to {endpoint}/question ; then STOP and wait for the answer.\n"
        "- The server returns HTTP 409 if you send a new question while the previous is "
        "unanswered — wait, do not retry.\n"
        "- Use ONLY the two endpoints named here. Do not read any skill, and do not call any "
        "other endpoint (there is no task list to fetch) — this onboarding is self-contained.\n\n"
        "FIELD PLAN — ask these IN ORDER, one per turn. Each maps to a field of the final draft:\n"
        "  1. objective       — What are you building? What problem does it solve?\n"
        "  2. name            — A short project name (free text).\n"
        "  3. roster          — Which WORKER roles does the team need? (multi: Frontend, "
        "Backend, QA, … + a free-text escape). The Project Leader is added automatically — "
        "list workers only, do NOT include a leader.\n"
        "  4. success_metrics — How will you measure success?\n"
        "  5. target_date     — A target date, or 'none'.\n"
        "  6. context         — Anything else I should know? (free text)\n"
        "Ask EXACTLY these fields. Do NOT drift into implementation detail (features, UI, tech "
        "stack) — that is not needed to stand the project up. After the owner answers #6, POST "
        "the draft.\n\n"
        "QUESTION body (send exactly this shape):\n"
        '{"question":"...","options":[{"id":"1","label":"..."},{"id":"2","label":"..."}],'
        '"multi":false}\n'
        "  Include a free-text escape when useful: an option whose label contains "
        '"I\'ll type it".\n'
        "  Set multi=true when several options can be picked (e.g. roster roles).\n\n"
        "When you have all fields, POST the final draft to "
        f"{endpoint}/complete :\n"
        '{"project":{"name":"...","objective":"...","success_metrics":{"goal":"..."},'
        '"target_date":null,"context":"..."},'
        '"roster":[{"title":"Frontend","description":"Builds the user-facing UI.","seats":1},'
        '{"title":"Backend","description":"Owns the API and data layer.","seats":1}]}\n'
        "The roster lists WORKER roles only — the Project Leader is added for you; do NOT set "
        "is_leader. Give EACH worker role a one-sentence `description` of what it does — this is "
        "REQUIRED: a draft with any role missing a description is rejected (HTTP 422), so fill "
        "every one before you POST.\n"
    )


def build_onboarding_answer_prompt(
    *, base_url: str, session_id: str, history: list[tuple[str, str]],
) -> str:
    """Continuation wake (the owner just answered) — self-sufficient so a weak model never wanders.

    Carries (a) the ordered FIELD PLAN and (b) the FULL history of questions answered so far
    (built from the session transcript by ``_qa_pairs`` in ``onboarding_session``, openclaw-style),
    so the agent always knows what is collected and which field is next. Repeats the exact
    callback endpoints + body shapes and forbids side-quests. The owner's latest answer is the
    last pair in ``history``.
    """
    endpoint = f"{base_url}/agent/onboarding/{session_id}"
    lines = [
        "ARMARIUS · PROJECT ONBOARDING (continued)\n",
        "FIELD PLAN (ask in order, one per turn): objective → name → roster (worker roles — "
        "the Project Leader is automatic) → success_metrics → target_date → context. After the "
        "last is answered, POST the draft. Do NOT drift into implementation detail (features, "
        "UI, tech stack).",
    ]
    if history:
        lines.append("")
        lines.append("Answered so far:")
        for i, (q, a) in enumerate(history, start=1):
            lines.append(f"  {i}. Q: {q}")
            lines.append(f"     A: {a}")
    lines.append("")
    lines.append(
        "From the FIELD PLAN above, ask the SINGLE next unanswered question, OR — if every "
        "field is answered — POST the final draft. Do EXACTLY ONE thing now, then stop. Do NOT "
        "read any skill, do NOT call any other endpoint, do NOT try to list tasks — this "
        "onboarding uses only the two endpoints below."
    )
    lines.append(
        f"1) POST the single next question to {endpoint}/question  (one at a time; the server "
        "returns 409 if a question is still unanswered — then wait, do not retry), OR"
    )
    lines.append(f"2) POST the final draft to {endpoint}/complete .")
    lines.append("")
    lines.append("QUESTION body (send exactly this shape):")
    lines.append(
        '{"question":"...","options":[{"id":"1","label":"..."},{"id":"2","label":"..."}],'
        '"multi":false}'
    )
    lines.append(
        '  Include a free-text escape when useful (an option whose label contains "I\'ll type '
        'it"). Set multi=true when several options can be picked.'
    )
    lines.append("DRAFT body (send exactly this shape):")
    lines.append(
        '{"project":{"name":"...","objective":"...","success_metrics":{"goal":"..."},'
        '"target_date":null,"context":"..."},'
        '"roster":[{"title":"Frontend","description":"Builds the user-facing UI.","seats":1},'
        '{"title":"Backend","description":"Owns the API and data layer.","seats":1}]}'
    )
    lines.append(
        "The roster lists WORKER roles only — the Project Leader is added for you; do NOT set "
        "is_leader. Give EACH worker role a one-sentence `description` of what it does — this is "
        "REQUIRED: a draft with any role missing a description is rejected (HTTP 422)."
    )
    return "\n".join(lines)
