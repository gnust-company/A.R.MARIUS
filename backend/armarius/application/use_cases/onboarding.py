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
from armarius.domain.services.agent_prompt import agent_prompt_footer


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "workspace"


def credential_file_for(marius: Marius, workspace_name: str) -> str:
    """The file where the agent stores its token. Skills read the token from here.

    Shared by the invite (STEP 1) and every wake prompt so the two never name a
    different file — a multi-workspace agent has one file per workspace (#15).

    **Path note**: The file sits directly under ``~/.armarius/`` (no ``tokens``/
    ``credentials`` subfolder) — a flat per-workspace JSON named ``<slug>.json``.
    """
    return f"~/.armarius/{_slugify(workspace_name)}_{marius.name.lower()}.json"


def _skill_block(skills: list[Skill], base: str, adapter_type: str = "hermes_gateway") -> str:
    """Render the per-skill installation section with runtime-specific instructions.

    Each skill is a small file tree (SKILL.md plus any sibling files/folders). The agent
    fetches the whole tree in ONE authenticated JSON call. Installation method varies by
    runtime (adapter_type): Hermes Agent uses skill_manage tool or /learn, Echo writes files,
    Claude Code uses MCP or ~/.claude/skills/, OpenClaw uses /skill-creator.
    """
    if not skills:
        return (
            'No skills were linked to you yet. Ask your patron to link the "Armarius HTTP '
            'API" skill (at least) so you can drive the workspace.'
        )

    # Runtime-specific installation instructions
    if adapter_type == "hermes_gateway":
        install_intro = [
            "You have been granted the skills below. Install EVERY one before you start work.",
            "",
            "You are running on HERMES AGENT. Install skills using the skill_manage tool:",
            "  • Use skill_manage with action='create' to install each skill",
            "  • Provide name, content (full SKILL.md), and optional category",
            "  • Alternative: use /learn slash command to create skills from sources",
            "  • Skills install to $HERMES_HOME/skills/<slug>/ and become slash commands",
            "",
        ]
    elif adapter_type == "echo":
        install_intro = [
            "You have been granted the skills below. Install EVERY one before you start work.",
            "",
            "You are running on ECHO (test adapter). Write skill files to ~/.echo/skills/:",
            "  • Fetch each skill's file tree via the authenticated GET call below",
            "  • Write each file verbatim to ~/.echo/skills/<slug>/<path>",
            "  • Create the skill directory structure before writing files",
            "",
        ]
    elif adapter_type in ("claude_mcp", "claude_local"):
        install_intro = [
            "You have been granted the skills below. Install EVERY one before you start work.",
            "",
            "You are running on CLAUDE CODE. Install skills via MCP or ~/.claude/skills/:",
            "  • If armarius-mcp MCP server is configured, skills are available as tools",
            "  • Otherwise: fetch skill files and write to ~/.claude/skills/<slug>/<path>",
            "  • Claude Code loads skills from ~/.claude/skills/ on startup",
            "",
        ]
    else:
        install_intro = [
            "You have been granted the skills below. Install EVERY one before you start work.",
            "",
            "Install each skill using your runtime's mechanism:",
            "  • Fetch the skill files via the authenticated GET call below",
            "  • Write each file verbatim to your runtime's skills directory",
            "  • Consult your runtime's documentation for the exact skills path",
            "",
        ]

    lines = install_intro.copy()
    for i, sk in enumerate(skills, start=1):
        lines.append(f"  {i}. {sk.name}  (slug: {sk.slug})")
        if sk.description:
            lines.append(f"     {sk.description}")
        lines.append(f"     Fetch:   GET {base}/agent/skills/{sk.slug}")
        lines.append("              Authorization: Bearer <your agent token — see the note below>")
        lines.append(
            '     Returns: {"slug": "' + sk.slug + '", "files": {"SKILL.md": "...", ...}}'
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
    skill_block = _skill_block(skills, base, marius.adapter_type)

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
installed skills take over.{agent_prompt_footer(cred_path)}"""


def build_skill_install_prompt(
    marius: Marius,
    public_base_url: str,
    *,
    workspace_name: str = "the workspace",
    skills: list[Skill],
) -> str:
    """Build a one-time skill-install prompt for an already-onboarded agent (issue #74).

    Unlike ``build_invite_prompt`` this carries no connection/setup steps — the agent is
    already approved and authenticated. It only tells the agent to fetch and install the
    newly linked skills. Reuses ``_skill_block`` so install instructions stay runtime-
    specific and identical to the invite path.
    """
    base = public_base_url.rstrip("/")
    cred_path = credential_file_for(marius, workspace_name)
    safe_name = marius.name.replace('"', '\\"')
    skill_block = _skill_block(skills, base, marius.adapter_type)
    return f"""╔══════════════════════════════════════════════════════════════════════════════╗
║  ARMARIUS · NEW SKILLS LINKED TO YOU                                          ║
╚══════════════════════════════════════════════════════════════════════════════╝

Hello {safe_name} — your patron in "{workspace_name}" has linked new skills to you.

You are already connected, so there is no setup here — just install the skills below so
you can use them on your next task. Authenticate with the agent_token you already saved
in `{cred_path}` (details in the note at the bottom).

───────────────────────────────────────────────────────────────────────────────────
INSTALL YOUR NEW SKILLS
───────────────────────────────────────────────────────────────────────────────────

{skill_block}
───────────────────────────────────────────────────────────────────────────────────

That is all. Once these are installed, carry on — you will be woken with a task when
there is work for you.{agent_prompt_footer(cred_path)}"""
