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

from armarius.application.ports.adapter import AdapterRegistry, MariusAdapter
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

    **Path note**: The file sits directly under ``$HOME/.armarius/`` (no ``tokens``/
    ``credentials`` subfolder) — a flat per-workspace JSON named ``<slug>.json``. We spell
    it ``$HOME`` (not ``~``) so weak runtimes don't fumble tilde expansion (#114).
    """
    return f"$HOME/.armarius/{_slugify(workspace_name)}_{marius.name.lower()}.json"


def install_steps_for(adapters: AdapterRegistry | None, adapter_type: str) -> tuple[str, ...]:
    """Ask the runtime itself how a skill gets installed on it (FR-083, Constitution III).

    This module used to answer that question with a chain of ``if adapter_type == ...``,
    which put a list of known runtimes inside the business layer — exactly what the
    adapter contract exists to prevent. Now the steps travel with the adapter, and a type
    nothing is registered for falls back to the contract's neutral wording. An agent can
    only be invited on a registered type in the first place (``InviteService.invite``
    raises ``UnknownAdapter`` otherwise), so the fallback is a safety net, not a path.
    """
    if adapters is not None:
        try:
            return adapters.get(adapter_type).skill_install_steps
        except LookupError:
            pass
    return MariusAdapter.skill_install_steps


def _skill_block(skills: list[Skill], base: str, install_steps: tuple[str, ...]) -> str:
    """Render the per-skill installation section.

    Each skill is a small file tree (SKILL.md plus any sibling files/folders). The agent
    fetches the whole tree in ONE authenticated JSON call; ``install_steps`` is the only
    runtime-specific part and comes from the adapter (see ``install_steps_for``).
    """
    if not skills:
        return (
            'No skills were linked to you yet. Ask your patron to link the "Armarius HTTP '
            'API" skill (at least) so you can drive the workspace.'
        )

    lines = [
        "You have been granted the skills below. Install EVERY one before you start work.",
        "",
        *install_steps,
        "",
    ]
    for i, sk in enumerate(skills, start=1):
        lines.append(f"  {i}. {sk.name}  (slug: {sk.slug})")
        if sk.description:
            lines.append(f"     {sk.description}")
        lines.append(f"     Fetch:   GET {base}/agent/skills/{sk.slug}")
        lines.append("              Authorization: Bearer <your agent token — see the note below>")
        lines.append(
            '     Returns: {"slug": "' + sk.slug + '", "files": {"SKILL.md": "...", ...}}'
        )
        lines.append(
            f"     Confirm: POST {base}/agent/skills/{sk.slug}/installed  (empty body, once you"
            " have written the files — so your patron sees it is installed)"
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
    adapters: AdapterRegistry | None = None,
) -> str:
    """Build the invitation prompt: connect to the workspace, then install skills.

    Inviting an agent to a workspace is *only* a connection step — prove the agent can
    reach the API with its own token and install the skills it has been granted. There is
    deliberately no project and no task loop here: real work happens later, in a separate
    wake session that carries its own full context, so nothing from this prompt needs to
    be remembered (issue #43).

    Under operator-invite (#63) the agent already holds its minted ``agent_token`` at invite
    time, so the prompt embeds it directly and points at ``/agent/me`` — there is no
    enroll-and-wait step anymore (the old ``enrollment_code`` / STEP-0 path was removed in
    #97).
    """
    base = public_base_url.rstrip("/")
    cred_path = credential_file_for(marius, workspace_name)
    skills = skills or []

    safe_name = marius.name.replace('"', '\\"')
    safe_role = marius.role.replace('"', '\\"')
    skill_block = _skill_block(skills, base, install_steps_for(adapters, marius.adapter_type))

    # Build the banner programmatically so the box stays aligned regardless of title.
    _w = 76
    _title = "ARMARIUS · WORKSPACE CONNECTION"
    banner = (
        "╔" + "═" * _w + "╗\n"
        "║  " + _title.ljust(_w - 2) + "║\n"
        "╚" + "═" * _w + "╝"
    )

    # Operator-invite: the agent already holds its minted token, so the prompt embeds it
    # directly. No STEP-0 enroll block.
    token = marius.agent_token or "<token>"

    return f"""{banner}

You are "{safe_name}", connecting to the "{workspace_name}" workspace as {safe_role}.

Armarius is a shared workshop where agents and humans collaborate. This message is a
ONE-TIME setup: it connects you to the workspace and installs the skills you have been
granted — nothing more. You are joining as an available worker in the pool.

There is no task here and nothing to remember afterwards. When there is work for you,
you will be woken in a SEPARATE session that carries the task, its thread, your
teammates, and everything else you need. For now, just get connected.

Work through the steps IN ORDER. Each one has a single clear check before the next.

───────────────────────────────────────────────────────────────────────────
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
  → 401 = the token is wrong; re-check STEP 1.

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
    adapters: AdapterRegistry | None = None,
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
    skill_block = _skill_block(skills, base, install_steps_for(adapters, marius.adapter_type))
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
