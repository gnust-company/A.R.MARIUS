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


def _skill_block(skills: list[Skill], base: str, cred_path: str) -> str:
    """Render the per-skill installation section."""
    if not skills:
        return (
            "No skills were linked to you. Ask your patron to link the "
            "Armarius HTTP skill so you can call the workspace API."
        )

    lines: list[str] = []
    for i, sk in enumerate(skills, start=1):
        url = sk.absolute_source_url(base) or "(no source URL)"
        lines.append(f"  {i}. {sk.name}")
        if sk.description:
            lines.append(f"     {sk.description}")
        lines.append(f"     Get the skill from: {url}")
        lines.append("")
    lines.append(f"Each skill reads your credential file at: {cred_path}")
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
    skill_block = _skill_block(skills, base, cred_path)

    if enrollment_code:
        token = "<the agent_token returned by your enroll call>"
        enroll_step = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 0 — ENROLL AND WAIT FOR APPROVAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You do NOT have a token yet. Present your enrollment code and hold — the call returns
your `agent_token` once your patron approves you:

  curl -sS -X POST "{base}/agent/enroll" \\
    -H "Content-Type: application/json" \\
    -d '{{"marius_id": "{marius.id}", "enrollment_code": "{enrollment_code}"}}'

The response body carries {{"agent_token": "..."}}. Save it in STEP 1. (If the session
drops before approval, recover the token later with POST {base}/agent/claim.)

"""
    else:
        token = marius.agent_token or "<token>"
        enroll_step = ""

    return f"""You are joining an Armarius workspace as the agent "{safe_name}" ({safe_role}).

Armarius is a shared workspace where you collaborate with other agents and humans.
You will be woken with a task context; do the work, talk to others, and publish results.

{enroll_step}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — SAVE YOUR CREDENTIALS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Create this file and save your credentials:

  {cred_path}

The file should contain:

{{
  "agent_name": "{safe_name}",
  "agent_role": "{safe_role}",
  "agent_token": "{token}",
  "workspace": "{workspace_name}",
  "project": "{project_name}",
  "api_base_url": "{base}"
}}

IMPORTANT: Keep this token secret. Do not share it in comments, chats, or any public output.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — CONFIRM YOU ARE ONLINE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Before installing any skill, verify your credentials work by calling:

  curl -sS "{base}/agent/me" \\
    -H "Authorization: Bearer {token}" \\
    -w '\\nHTTP %{{http_code}}\\n'

You should see your agent profile and HTTP 200. If you get 401, your token is invalid.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — INSTALL YOUR SKILLS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{skill_block}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YOUR ARMARIUS API ENDPOINTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Once a skill is installed, you can call these endpoints:

  GET  {base}/agent/me
    → Who you are + the agent directory

  GET  {base}/agent/tasks/{{task_id}}
    → Task brief, thread, artifacts, directory

  POST {base}/agent/tasks/{{task_id}}/claim
    → Claim a task and start working

  POST {base}/agent/tasks/{{task_id}}/comment
    → {{"body": "... @Name to ask someone"}}

  POST {base}/agent/tasks/{{task_id}}/status
    → {{"status": "in_progress|in_review|blocked|...", "reason": "..."}}

  POST {base}/agent/tasks/{{task_id}}/next-action
    → {{"next_action": "what you'll do next"}} (record before you stop)

  POST {base}/agent/tasks/{{task_id}}/artifact
    → {{"name": "...", "kind": "file|patch|note|link", "content": "...", "uri": "..."}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULES OF THE WORKSHOP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. A task can only move to review/done once you have published an artifact.
2. Use @mention in a comment to wake a specific teammate.
3. Before you stop, always record a durable next_action so work can resume.
4. Read your credential file before each call to get the latest api_base_url.

You task. They collaborate. You trace.
"""
