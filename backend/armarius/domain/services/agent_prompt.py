"""Shared token-location footer for every system→agent prompt (#80).

Modeled on openclaw-mission-control's ``mission_control_agent_footer``: one token-free
reminder appended to the end of every message the system pushes to an agent — invite,
skill install, onboarding — so each one names the exact on-disk credential file and how
to authenticate. Token-free by design: it points at the file the agent already saved and
never re-embeds the secret, so the same footer is safe to attach to any message.

The task-wake prompt front-loads the same facts in its own "Where you are" header (see
``wake_prompt``), so it deliberately does not repeat this footer.
"""

from __future__ import annotations

_DEFAULT_LOCATION = "~/.armarius/<workspace>_<agent>.json"


def agent_prompt_footer(credential_file: str | None = None) -> str:
    """The token-location reminder appended to the end of a system→agent prompt.

    Names the workspace credential file the agent saved at connection time and tells it to
    authenticate every Armarius API call with the token stored there. Never contains the
    token itself. When ``credential_file`` is omitted it falls back to the default location
    shape so the reminder is still actionable.
    """
    location = credential_file or _DEFAULT_LOCATION
    return (
        "\n\n---\n"
        "IMPORTANT — this is an Armarius system message. Whatever it asks you to do, you "
        "authenticate every Armarius API call with YOUR agent token:\n"
        f"1) Read your credential file `{location}` — it holds `agent_token` and "
        "`api_base_url` for THIS workspace.\n"
        "2) Send header `Authorization: Bearer <agent_token>` on every request, using the "
        "`api_base_url` from that same file as the base URL.\n"
        "3) If you serve several workspaces you have one file per workspace under "
        "`~/.armarius/` — read only the file named above, never the others.\n"
        "4) If that file is missing you are not connected yet — run your workspace "
        "connection (the invite prompt) first.\n"
        "5) The token is a secret: never echo it into a comment, artifact, or any output.\n"
    )
