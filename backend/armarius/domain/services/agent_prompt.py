"""Shared credential hint appended to every system→agent prompt (#80).

Modeled on openclaw-mission-control's ``mission_control_agent_footer``: one token-free
hint attached to the end of every message the system pushes to an agent — invite, skill
install, onboarding, task wake, leader chat — pointing at the on-disk credential file.
It is a SOFT hint, not an order: it tells the agent where its token lives and to read it
once (when it does not already have it in hand) and reuse it, rather than re-reading every
step (re-reading bites runtimes that dedup identical reads — e.g. Hermes ``read_file``
returns "File unchanged", which a weak model mistakes for "file missing"). Token-free by
design and runtime-neutral: no runtime-specific behaviour belongs in this shared footer.

The task-wake prompt appends this same footer too (see ``wake_prompt``), after its own
"Where you are" orientation header.
"""

from __future__ import annotations

_DEFAULT_LOCATION = "~/.armarius/<workspace>_<agent>.json"


def agent_prompt_footer(credential_file: str | None = None) -> str:
    """A soft, runtime-neutral credential hint appended to every system→agent prompt.

    Points the agent at where its credential lives and nudges it to read the token once
    (when it does not already have it in hand) and reuse it — instead of ordering a re-read
    on every step. Token-free by design: it names the file, never re-embeds the secret.
    Deliberately generic; no runtime-specific behaviour lives here.

    When ``credential_file`` is omitted it falls back to the default location shape so the
    hint is still actionable.
    """
    location = credential_file or _DEFAULT_LOCATION
    return (
        "\n\n---\n"
        "ARMARIUS HINT — your credential (agent_token + api_base_url) lives at "
        f"`{location}`. Read it if you don't already have the token in hand — any "
        "file-reading tool works (`cat`, read_file, …) — then reuse it for every call; "
        "you don't need to open the file each step.\n"
    )
