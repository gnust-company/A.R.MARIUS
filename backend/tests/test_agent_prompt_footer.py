"""Shared token-location footer — every system→agent prompt names the credential file (#80).

The footer (modeled on openclaw-mission-control) is token-free and appended to the prompts
the system sends, so the agent always knows where its token lives.

The invite and skill-install prompts this file used to cover are gone with the gateway that
carried them (FR-007g, FR-011c). The onboarding prompt still goes out, and the footer rule is
about every such prompt rather than any one of them, so it is tested on its own here.
"""

from __future__ import annotations

from armarius.application.use_cases.onboarding import credential_file_for
from armarius.domain.entities.marius import Marius
from armarius.domain.services.agent_prompt import agent_prompt_footer

_SECRET = "arm_secret_should_never_appear_in_a_footer"


def _marius() -> Marius:
    return Marius(name="Marin", role="Backend", adapter_type="echo", agent_token=_SECRET)


def test_footer_is_a_soft_token_free_hint():
    footer = agent_prompt_footer("$HOME/.armarius/acme_marin.json")
    assert "$HOME/.armarius/acme_marin.json" in footer
    # Leads with a separator so it reads as an appended footer, not inline body.
    assert footer.startswith("\n\n---\n")
    # Token-free by design: it points at the file, never re-embeds the secret.
    assert _SECRET not in footer
    # A soft HINT, not an order: nudges reading once + reusing, mentions `cat`, and is
    # runtime-neutral (no Bearer tutorial, no runtime-specific dedup line) (#108).
    assert "ARMARIUS HINT" in footer
    assert "cat" in footer
    assert "Authorization: Bearer" not in footer
    assert "File unchanged" not in footer
    # The anti-leak guardrail stays (task-wake/leader-chat get the warning only via this
    # footer), as a short token-free line — not the old numbered list (#109 review).
    assert "never echo the token" in footer.lower()


def test_footer_falls_back_to_a_default_location():
    assert "$HOME/.armarius/<workspace>_<agent>.json" in agent_prompt_footer()


def test_the_credential_file_is_named_the_same_way_everywhere():
    # One function answers "where does this agent keep its token", because two places naming
    # that file separately is two places that can name it differently. The wake prompt and
    # the leader-chat prompt both ask this one.
    marius = _marius()
    assert credential_file_for(marius, "Acme") == "$HOME/.armarius/acme_marin.json"
    # Spelled $HOME rather than ~, so a runtime that fumbles tilde expansion still finds it.
    assert credential_file_for(marius, "Acme").startswith("$HOME/")
