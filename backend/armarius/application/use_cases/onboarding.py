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


def credential_file_for(marius: Marius, workspace_name: str) -> str:
    """The file where the agent stores its token. Skills read the token from here.

    Shared by the invite (STEP 1) and every wake prompt so the two never name a
    different file — a multi-workspace agent has one file per workspace (#15).
    """
    return f"~/.armarius/credentials/{_slugify(workspace_name)}_{marius.name.lower()}.json"


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
    skills: list[Skill] | None = None,
    enrollment_code: str | None = None,
) -> str:
    """Build the invitation prompt: connect to the workspace, then install skills.

    Inviting an agent to a workspace is *only* a connection step — prove the agent can
    reach the API with its own token and install the skills it has been granted. There is
    deliberately no project and no task loop here: real work happens later, in a separate
    wake session that carries its own full context, so nothing from this prompt needs to
    be remembered (issue #43).

    Enroll-and-wait (API_CONTRACT §4.1): when `enrollment_code` is given, the prompt
    carries the **code** (never a token) and tells the agent to POST `/agent/enroll`
    and hold — the minted `agent_token` is returned on that call once the Patron approves.
    """
    base = public_base_url.rstrip("/")
    cred_path = credential_file_for(marius, workspace_name)
    skills = skills or []

    safe_name = marius.name.replace('"', '\\"')
    safe_role = marius.role.replace('"', '\\"')
    skill_block = _skill_block(skills, base)

    # Build the banner programmatically so the box stays aligned regardless of title.
    _w = 76
    _title = "ARMARIUS · WORKSPACE CONNECTION"
    banner = (
        "╔" + "═" * _w + "╗\n"
        "║  " + _title.ljust(_w - 2) + "║\n"
        "╚" + "═" * _w + "╝"
    )

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

    return f"""{banner}

You are "{safe_name}", connecting to the "{workspace_name}" workspace as {safe_role}.

Armarius is a shared workshop where agents and humans collaborate. This message is a
ONE-TIME setup: it connects you to the workspace and installs the skills you have been
granted — nothing more. You are joining as an available worker in the pool.

There is no task here and nothing to remember afterwards. When there is work for you,
you will be woken in a SEPARATE session that carries the task, its thread, your
teammates, and everything else you need. For now, just get connected.

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
    "api_base_url": "{base}"
  }}

IMPORTANT: the token is a secret. Never put it in a comment, artifact, or any output.

───────────────────────────────────────────────────────────────────────────
STEP 2 · CONFIRM YOU ARE ONLINE
───────────────────────────────────────────────────────────────────────────

Verify the token works before doing anything else:

  GET {base}/agent/me
  Authorization: Bearer <your token>

  → 200 with your profile + the teammate directory = you are connected.
  → 401 = the token is wrong; re-check STEP 1 (or re-run STEP 0 / claim).

───────────────────────────────────────────────────────────────────────────
STEP 3 · INSTALL YOUR SKILLS
───────────────────────────────────────────────────────────────────────────

{skill_block}
───────────────────────────────────────────────────────────────────────────

That is it — you are connected to "{workspace_name}" and your skills are installed.
Nothing else to do now: wait to be woken with a task in its own session, where your
installed skills take over.
"""
