"""Onboarding — build the invitation prompt an owner hands to their agent (§6.1).

The prompt advertises the *public* Armarius API URL (PUBLIC_BASE_URL), not the
browser's view, so it is correct even when the agent runs on a different machine.

It guides the agent to:
- save its credentials to a specific file,
- confirm it is online,
- install each skill linked to this Marius (per-skill instructions).
"""

from __future__ import annotations

import re

from armarius.domain.entities.marius import Marius
from armarius.domain.entities.skill import Skill


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "workspace"


def _credential_file_path(marius: Marius, workspace_slug: str) -> str:
    """The file where the agent stores its token. Skills read the token from here."""
    return f"~/.armarius/credentials/{workspace_slug}_{marius.name.lower()}.json"


def _skill_block(skills: list[Skill], base: str) -> str:
    """Render the per-skill installation section.

    Each skill is a small file tree (SKILL.md plus any sibling files/folders). The agent
    fetches the whole tree in ONE authenticated JSON call and writes every file verbatim
    under its runtime's skills directory — no curl-and-paste, no guessing at file layout.
    """
    if not skills:
        return (
            'No skills were linked to you yet. Ask your patron to link the "Armarius HTTP '
            'API" skill (at least) so you can drive the workspace.'
        )

    lines: list[str] = [
        "You have been granted the skills below. Install EVERY one before you start work.",
        "For each skill, make ONE authenticated call to fetch its full file tree, then",
        "write each file verbatim under your runtime's skills directory — for Claude Code",
        "that is  ~/.claude/skills/<slug>/<path>  (use your own runtime's equivalent).",
        "",
    ]
    for i, sk in enumerate(skills, start=1):
        lines.append(f"  {i}. {sk.name}  (slug: {sk.slug})")
        if sk.description:
            lines.append(f"     {sk.description}")
        lines.append(f"     Fetch:   GET {base}/agent/skills/{sk.slug}")
        lines.append("              Authorization: Bearer <your token from STEP 0>")
        lines.append(
            '     Returns: {"slug": "' + sk.slug + '", "files": {"SKILL.md": "...", ...}}'
        )
        lines.append(
            f"     Install: write each files[path] to  <skills dir>/{sk.slug}/<path>"
        )
        lines.append("")
    lines.append(
        f"List everything linked to you (slugs + file counts):  GET {base}/agent/skills"
    )
    return "\n".join(lines)


def build_invite_prompt(
    marius: Marius,
    public_base_url: str,
    *,
    workspace_name: str = "the workspace",
    project_name: str = "the project",
    skills: list[Skill] | None = None,
    enrollment_code: str | None = None,
) -> str:
    """Build the invitation prompt with credential storage + per-skill install steps.

    Enroll-and-wait (API_CONTRACT §4.1): when `enrollment_code` is given, the prompt
    carries the **code** (never a token) and tells the agent to POST `/agent/enroll`
    and hold — the minted `agent_token` is returned on that call once the Patron approves.
    """
    base = public_base_url.rstrip("/")
    workspace_slug = _slugify(workspace_name)
    cred_path = _credential_file_path(marius, workspace_slug)
    skills = skills or []

    safe_name = marius.name.replace('"', '\\"')
    safe_role = marius.role.replace('"', '\\"')
    skill_block = _skill_block(skills, base)

    if enrollment_code:
        token = "<the agent_token returned by your enroll call>"
        enroll_step = f"""───────────────────────────────────────────────────────────────────────────
STEP 0 · ENROLL AND WAIT FOR APPROVAL   (you have no token yet)
───────────────────────────────────────────────────────────────────────────

You join by presenting a one-time enrollment code and HOLDING while your patron
approves you. The call blocks, then returns your personal `agent_token`:

  POST {base}/agent/enroll
  Content-Type: application/json
  {{"marius_id": "{marius.id}", "enrollment_code": "{enrollment_code}"}}

  → 200 {{"agent_token": "arm_..."}}   ← save this in STEP 1.

Notes:
  • The request may hold for a while — that is expected; keep it open.
  • If the connection drops before approval lands, recover the token later with:
      POST {base}/agent/claim   (same body as above)
  • Do this ONCE. After you have a token, never enroll again.

"""
    else:
        token = marius.agent_token or "<token>"
        enroll_step = ""

    return f"""╔══════════════════════════════════════════════════════════════════════════╗
║  ARMARIUS · AGENT ONBOARDING                                               ║
╚══════════════════════════════════════════════════════════════════════════╝

You are "{safe_name}", joining the "{workspace_name}" workspace as its {safe_role}
(project: {project_name}).

Armarius is a shared workshop where agents and humans collaborate on tasks. You will
be woken with a task, its thread, and a directory of teammates. The loop is always:
read the task → do the work → talk to teammates (@mention) → publish an artifact →
update status → record your next action. This document gets you set up to do that.

Work through the steps IN ORDER. Each one has a single clear check before the next.

{enroll_step}───────────────────────────────────────────────────────────────────────────
STEP 1 · SAVE YOUR CREDENTIALS
───────────────────────────────────────────────────────────────────────────

Create this file (0600, keep it private) — your skills read the token from here:

  {cred_path}

Contents:

  {{
    "agent_name": "{safe_name}",
    "agent_role": "{safe_role}",
    "agent_token": "{token}",
    "workspace": "{workspace_name}",
    "project": "{project_name}",
    "api_base_url": "{base}"
  }}

IMPORTANT: the token is a secret. Never put it in a comment, artifact, or any output.

───────────────────────────────────────────────────────────────────────────
STEP 2 · CONFIRM YOU ARE ONLINE
───────────────────────────────────────────────────────────────────────────

Verify the token works before doing anything else:

  GET {base}/agent/me
  Authorization: Bearer <your token>

  → 200 with your profile + the teammate directory = you are in.
  → 401 = the token is wrong; re-check STEP 1 (or re-run STEP 0 / claim).

───────────────────────────────────────────────────────────────────────────
STEP 3 · INSTALL YOUR SKILLS
───────────────────────────────────────────────────────────────────────────

{skill_block}
───────────────────────────────────────────────────────────────────────────
STEP 4 · WORK THE LOOP  (reference)
───────────────────────────────────────────────────────────────────────────

Your installed skill(s) explain these in full; the endpoints, for reference:

  GET  {base}/agent/me                          who you are + the directory
  GET  {base}/agent/tasks/{{task_id}}             brief + thread + artifacts
  POST {base}/agent/tasks/{{task_id}}/claim       take the task, start working
  POST {base}/agent/tasks/{{task_id}}/comment     {{"body": "... @Name ..."}}
  POST {base}/agent/tasks/{{task_id}}/status      {{"status": "in_progress|in_review|...", "reason": "..."}}
  POST {base}/agent/tasks/{{task_id}}/next-action {{"next_action": "what you'll do next"}}
  POST {base}/agent/tasks/{{task_id}}/artifact    {{"name": "...", "kind": "file|patch|note|link", "content": "..."}}

RULES OF THE WORKSHOP
  1. A task only moves to review/done AFTER you publish an artifact.
  2. @mention a teammate in a comment to wake them.
  3. Always record a next_action before you stop, so work can resume.
  4. Re-read your credential file for the current api_base_url before a session.

You task. They collaborate. You trace.
"""
