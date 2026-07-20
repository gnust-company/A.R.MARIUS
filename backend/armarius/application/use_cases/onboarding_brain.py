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

    Onboarding is injected into the prompt, not shipped as a skill. Teaches the agent to
    interview the Patron ONE question at a time as tick-select options and
    finish with a project + roster draft. The agent posts its questions/completion back through
    the agent-facing endpoints; the service reconciles them onto ``OnboardingSession.collected``.
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
        "- When the owner answers, decide the single next question from the running context.\n"
        "- Use ONLY the two endpoints named here. Do not read any skill, and do not call any "
        "other endpoint (there is no task list to fetch) — this onboarding is self-contained.\n\n"
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


def build_onboarding_answer_prompt(*, base_url: str, session_id: str, answer: str) -> str:
    """Continuation wake (the owner just answered) — self-sufficient so a weak model never wanders.

    Unlike the terse note it replaces, this repeats the exact callback endpoints + body shapes
    and forbids side-quests (loading skills, calling other endpoints). The agent must do exactly
    one thing: POST the single next question, or POST the final draft.
    """
    endpoint = f"{base_url}/agent/onboarding/{session_id}"
    return (
        "ARMARIUS · PROJECT ONBOARDING (continued)\n\n"
        f"The owner answered: {answer}\n\n"
        "Do EXACTLY ONE thing now, then stop. Do NOT read any skill, do NOT call any other "
        "endpoint, do NOT try to list tasks — this onboarding uses only the two endpoints below.\n"
        f"1) POST the single next question to {endpoint}/question  (one at a time; the server "
        "returns 409 if a question is still unanswered — then wait, do not retry), OR\n"
        f"2) POST the final draft to {endpoint}/complete once you have enough to stand the "
        "project up.\n\n"
        "QUESTION body (send exactly this shape):\n"
        '{"question":"...","options":[{"id":"1","label":"..."},{"id":"2","label":"..."}],'
        '"multi":false}\n'
        '  Include a free-text escape when useful (an option whose label contains "I\'ll type '
        'it"). Set multi=true when several options can be picked.\n\n'
        "DRAFT body (send exactly this shape):\n"
        '{"project":{"name":"...","objective":"...","success_metrics":{"goal":"..."},'
        '"target_date":null,"context":"..."},'
        '"roster":[{"title":"Project Leader","seats":1,"is_leader":true},'
        '{"title":"Frontend","seats":1,"is_leader":false}]}\n'
        "The roster MUST have exactly one leader (is_leader=true) plus at least one worker.\n"
    )
