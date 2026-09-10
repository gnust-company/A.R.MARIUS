"""Onboarding guide — the prompt injected into a real Workspace Agent (#61, v3).

There is NO scripted brain here. Project setup is the Workspace Agent's job: the agent is a
real runtime that must be **online and wake-able**. On ``start``/``answer`` the
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
        "draft": {name, objective, success_metrics, target_date, context} | None,
    }
"""

from __future__ import annotations

import re

_STOPWORDS = {
    "a", "an", "the", "build", "create", "make", "for", "to", "of", "and", "with",
    "want", "need", "we", "i", "our", "my", "project", "app", "application", "system",
    "that", "this", "it", "on", "in", "new",
}


def _project_name(objective: str) -> str:
    """Derive a short, human project name from the objective text (finalize fallback)."""
    words = [w for w in re.split(r"[^a-z0-9]+", objective.lower()) if w and w not in _STOPWORDS]
    name = " ".join(w.capitalize() for w in words[:4]) if words else "New Project"
    return name[:80]


# What the Leader of a project built through the interview is there to do.
#
# Canned rather than asked, and it is the one sentence about the roster this flow still has:
# the interview is about the project, the team is the patron's own agents, and who is on it is
# something they pick by name on the roster screen afterwards. The agent used to draft worker
# roles here — titles and descriptions of work, invented by a model, standing beside the
# instructions actually written on each agent (FR-007l).
LEADER_DESCRIPTION = "Owns the plan and coordinates the team."


# The fields the interview collects, in order — and the ONE place they are written down.
#
# There are two prompts: the opening turn, and every turn after it. Each used to carry its own
# copy of this list, and that is exactly how `worker_count` came to exist in one of them and not
# the other. The field was added to the opening prompt — which only ever asks question #1 — while
# the prompt that asks questions 2..n still listed five fields and told the agent to post the
# draft after `context`. So the interview never reached the question, every interviewed project
# came out asking for one worker, and the feature looked implemented from every angle except the
# one that mattered. Caught in review of PR #272.
#
# Two copies of one list is the defect; one list read twice is the fix. A test asserts every name
# here appears in BOTH prompts, so the copies cannot come apart again.
FIELD_PLAN: tuple[tuple[str, str], ...] = (
    ("objective", "What are you building? What problem does it solve?"),
    ("name", "A short project name (free text)."),
    ("success_metrics", "How will you measure success?"),
    ("target_date", "A target date, or 'none'."),
    ("context", "Anything else I should know? (free text)"),
    (
        "worker_count",
        "Besides the Project Leader, how many people should work on this? Offer a few numbers "
        "as options and accept a typed one.",
    ),
)

# The draft shape, once. `worker_count` is a plain integer here for the same reason the field
# plan is shared: a JSON example that disagrees with the field plan teaches the model to send a
# draft the server then has to guess at.
DRAFT_SHAPE = (
    'project={"name":"...","objective":"...","success_metrics":{"goal":"..."},'
    '"target_date":null,"context":"...","worker_count":3}'
)

# The one rule that keeps the last field from turning back into a roster question. Said in both
# prompts, because a weak model reading only the later one would otherwise have nothing to hold.
HOW_MANY_NOT_WHO = (
    "The last field asks HOW MANY, never WHO and never WHAT EACH ONE DOES. Do NOT ask which "
    "agents should be on the team, do not name any agent, and do not describe anybody's job: "
    "the owner puts their own agents on the project, and what each agent does is already "
    "written on that agent. The number only says how large this project is, so the owner sees "
    "that many places waiting to be filled."
)


def _numbered_field_plan() -> str:
    """The long form, for the opening turn: one field per line, numbered, with its question."""
    width = max(len(name) for name, _ in FIELD_PLAN)
    return "".join(
        f"  {i}. {name.ljust(width)} — {question}\n"
        for i, (name, question) in enumerate(FIELD_PLAN, start=1)
    )


def _field_plan_arrow() -> str:
    """The compact form, for every turn after the first: the order on one line."""
    return " → ".join(name for name, _ in FIELD_PLAN)


def is_free_text_option(label: str) -> bool:
    """An option whose label invites a typed answer (mirrors the guide's free-text escape)."""
    return bool(re.search(r"i'?ll type|type it|type my|other|custom|free\s*text", label, re.I))


def build_onboarding_guide_prompt(*, session_id: str, workspace_name: str) -> str:
    """The guide the Workspace Agent is given on the first turn of a session.

    Onboarding is injected into the prompt, not shipped as a skill. The agent interviews the
    Patron ONE question at a time following the ordered FIELD PLAN below (each field maps to the
    final draft body), then posts the draft. The agent posts its questions/completion back
    through its own Armarius tools; the service reconciles them onto
    ``OnboardingSession.collected``. The ordered plan keeps a weak model on the rails instead of
    circling implementation detail.

    **It names tools, not addresses.** The turn runs on a machine that hands the agent a toolset,
    and that toolset *is* what this run may do (FR-013d). Spelling out an HTTP call instead would
    teach the agent to hand-write requests around the tools it was given — and the tools are the
    only half of the scope rule the agent can see.
    """
    return (
        "ARMARIUS · PROJECT ONBOARDING\n\n"
        f"You are the Workspace Agent for '{workspace_name}'. Interview the owner and stand up a "
        "new project by working through the FIELD PLAN below, ONE question per turn, in order.\n\n"
        f"This chat is `{session_id}` — every tool call below needs it as `session_id`.\n\n"
        "PROTOCOL — one question per turn:\n"
        "- Call `onboarding ask` with your question; then STOP and wait for the answer.\n"
        "- Asking again while the previous question is unanswered is refused — wait, do not "
        "retry.\n"
        "- Use ONLY the two tools named here. Do not read any skill and do not go looking for "
        "other work — this onboarding is self-contained.\n\n"
        "FIELD PLAN — ask these IN ORDER, one per turn. Each maps to a field of the final draft:\n"
        f"{_numbered_field_plan()}"
        "Ask EXACTLY these fields. Do NOT drift into implementation detail (features, UI, tech "
        "stack) — that is not needed to stand the project up.\n"
        f"{HOW_MANY_NOT_WHO} After the owner answers the last field, post the draft.\n\n"
        "ASKING — `onboarding ask`:\n"
        f'  session_id={session_id}\n'
        '  question="..."\n'
        '  options=[{"id":"1","label":"..."},{"id":"2","label":"..."}]\n'
        "  multi=true when several options can be picked\n"
        "  Include a free-text escape when useful: an option whose label contains "
        '"I\'ll type it".\n\n'
        "PROPOSING — when you have all fields, call `onboarding propose`:\n"
        f'  session_id={session_id}\n'
        f"  {DRAFT_SHAPE}\n"
        "That is the whole draft. `worker_count` is the answer to the last field as a plain "
        "integer. The project is created with a Project Leader seat and that many worker "
        "places, which the owner fills themselves — you do not name, choose or describe "
        "anybody.\n"
    )


def build_onboarding_answer_prompt(
    *, session_id: str, history: list[tuple[str, str]],
) -> str:
    """The next turn (the owner just answered) — self-sufficient so a weak model never wanders.

    Carries (a) the ordered FIELD PLAN and (b) the FULL history of questions answered so far
    (built from the session transcript by ``_qa_pairs`` in ``onboarding_session``, openclaw-style),
    so the agent always knows what is collected and which field is next. Repeats the exact tools
    and their shapes and forbids side-quests. The owner's latest answer is the last pair in
    ``history``.
    """
    lines = [
        "ARMARIUS · PROJECT ONBOARDING (continued)\n",
        f"FIELD PLAN (ask in order, one per turn): {_field_plan_arrow()}. After the LAST one "
        "is answered, post the draft. Do NOT drift into implementation detail (features, UI, "
        "tech stack).",
        "",
        HOW_MANY_NOT_WHO,
        "",
        f"This chat is `{session_id}` — every tool call below needs it as `session_id`.",
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
        "field is answered — post the final draft. Do EXACTLY ONE thing now, then stop. Do NOT "
        "read any skill and do not go looking for other work — this onboarding uses only the "
        "two tools below."
    )
    lines.append(
        "1) Call `onboarding ask` with the single next question (one at a time; asking again "
        "while the previous one is unanswered is refused — then wait, do not retry), OR"
    )
    lines.append("2) Call `onboarding propose` with the final draft.")
    lines.append("")
    lines.append("ASKING — `onboarding ask`:")
    lines.append(f"  session_id={session_id}")
    lines.append('  question="..."')
    lines.append('  options=[{"id":"1","label":"..."},{"id":"2","label":"..."}]')
    lines.append(
        '  Include a free-text escape when useful (an option whose label contains "I\'ll type '
        'it"). Set multi=true when several options can be picked.'
    )
    lines.append("PROPOSING — `onboarding propose`:")
    lines.append(f"  session_id={session_id}")
    lines.append(f"  {DRAFT_SHAPE}")
    lines.append(
        "That is the whole draft. `worker_count` is the answer to the last field as a plain "
        "integer. The project is created with a Project Leader seat and that many worker "
        "places, which the owner fills themselves — you do not name, choose or describe "
        "anybody."
    )
    return "\n".join(lines)
