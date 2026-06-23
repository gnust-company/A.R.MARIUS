"""Onboarding — build the invitation prompt an owner hands to their agent (§6.1).

The prompt advertises the *public* Armarius API URL (PUBLIC_BASE_URL), not the
browser's view, so it is correct even when the agent runs on a different machine.

Enhanced with:
- Credential file storage instruction
- Online confirmation step
- Skill installation guidance
"""

from __future__ import annotations

from armarius.domain.entities.marius import Marius


def _credential_file_path(marius: Marius) -> str:
    """Return the credential file path where the agent should store its token."""
    # Format: ~/.armarius/credentials/<workspace_slug>_<agent_name>.json
    # Use a simple format that works across agents
    workspace_slug = marius.workspace.slug if marius.workspace else "workspace"
    return f"~/.armarius/credentials/{workspace_slug}_{marius.name.lower()}.json"


def build_invite_prompt(marius: Marius, public_base_url: str) -> str:
    """Build an enhanced invitation prompt with credential storage and skill install steps."""
    base = public_base_url.rstrip("/")
    token = marius.agent_token or "<token>"
    cred_path = _credential_file_path(marius)
    workspace_name = marius.workspace.name if marius.workspace else "the workspace"
    project_name = marius.project.name if marius.project else "the project"

    # Escape any special characters in the name/role for safe shell usage
    safe_name = marius.name.replace('"', '\\"')
    safe_role = marius.role.replace('"', '\\"')

    return f"""You are joining an Armarius workspace as the agent "{safe_name}" ({safe_role}).

Armarius is a shared workspace where you collaborate with other agents and humans.
You will be woken with a task context; do the work, talk to others, and publish results.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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

  curl -sS "{{base}}/agent/me" \\
    -H "Authorization: Bearer {token}" \\
    -w '\\nHTTP %{{http_code}}\\n'

You should see your agent profile and HTTP 200. If you get 401, your token is invalid.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — INSTALL THE ARMARIUS SKILL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The Armarius skill gives you direct access to all workspace APIs.

Install via your agent's skill system:

  # For Hermes agents
  hermes skill install https://github.com/gnust-company/A.R.MARIUS/skills/armarius-http

  # For Claude Code / other agents
  # Download the skill from: {base}/static/skills/armarius-http/SKILL.md

The skill will read your credential file at: {cred_path}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YOUR ARMARIUS API ENDPOINTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Once the skill is installed, you can call these endpoints:

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

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
QUICK START — KNOWN-GOOD CALL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

After installing the skill, verify with:

  curl -sS "{base}/agent/me" \\
    -H "Authorization: Bearer {token}" \\
    -w '\\nHTTP %{{http_code}}\\n'

You task. They collaborate. You trace.
"""
