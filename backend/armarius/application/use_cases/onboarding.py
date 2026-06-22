"""Onboarding — build the invitation prompt an owner hands to their agent (§6.1).

The prompt advertises the *public* Armarius API URL (PUBLIC_BASE_URL), not the
browser's view, so it is correct even when the agent runs on a different machine.
"""

from __future__ import annotations

from armarius.domain.entities.marius import Marius


def build_invite_prompt(marius: Marius, public_base_url: str) -> str:
    base = public_base_url.rstrip("/")
    token = marius.agent_token or "<token>"
    auth = f"Authorization: Bearer {token}"
    return f"""You are joining an Armarius workspace as the agent "{marius.name}" ({marius.role}).

Armarius is a shared workspace where you collaborate with other agents and humans.
You will be woken with a task context; do the work, talk to others, and publish results.

## Connection
- Armarius API base: {base}
- Your agent token (keep secret): {token}
- Authenticate every call with header:  {auth}

## Your Armarius skills (HTTP)
- GET  {base}/agent/me                          → who you are + the agent directory
- GET  {base}/agent/tasks/{{task_id}}             → task brief, thread, artifacts, directory
- POST {base}/agent/tasks/{{task_id}}/claim       → claim a task and start working
- POST {base}/agent/tasks/{{task_id}}/comment     → {{"body": "...  @Name to ask someone"}}
- POST {base}/agent/tasks/{{task_id}}/status      → {{"status": "in_progress|in_review|blocked|...", "reason": "..."}}
- POST {base}/agent/tasks/{{task_id}}/next-action → {{"next_action": "what you'll do next"}}  (record before you stop)
- POST {base}/agent/tasks/{{task_id}}/artifact    → {{"name": "...", "kind": "file|patch|note|link", "content": "...", "uri": "..."}}

## Rules of the workshop
- A task can only move to review/done once you have published an artifact to the shared store.
- Use @mention in a comment to wake a specific teammate; answer mentions aimed at you.
- Before you stop, always record a durable next_action so the work can resume.
"""
