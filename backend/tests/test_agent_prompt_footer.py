"""Shared token-location footer — every system→agent prompt names the credential file (#80).

The footer (modeled on openclaw-mission-control) is token-free and appended to the invite,
skill-install and onboarding prompts so the agent always knows where its token lives.
"""

from __future__ import annotations

from armarius.application.use_cases.onboarding import (
    build_invite_prompt,
    build_skill_install_prompt,
    credential_file_for,
)
from armarius.domain.entities.marius import Marius
from armarius.domain.entities.skill import Skill
from armarius.domain.services.agent_prompt import agent_prompt_footer

_SECRET = "arm_secret_should_never_appear_in_a_footer"


def _marius() -> Marius:
    return Marius(name="Marin", role="Backend", adapter_type="hermes_gateway", agent_token=_SECRET)


def _skill() -> Skill:
    return Skill(slug="armarius-http", name="Armarius HTTP API", description="Drive the workspace.")


def test_footer_names_the_file_and_is_token_free():
    footer = agent_prompt_footer("~/.armarius/acme_marin.json")
    assert "~/.armarius/acme_marin.json" in footer
    assert "Authorization: Bearer" in footer
    # Leads with a separator so it reads as an appended footer, not inline body.
    assert footer.startswith("\n\n---\n")
    # Token-free by design: it points at the file, never re-embeds the secret.
    assert _SECRET not in footer


def test_footer_falls_back_to_a_default_location():
    assert "~/.armarius/<workspace>_<agent>.json" in agent_prompt_footer()


def test_skill_install_prompt_carries_token_location():
    """The gap #80 fixes: the post-invite skill-install prompt now names the token file."""
    m = _marius()
    cred = credential_file_for(m, "Acme")
    prompt = build_skill_install_prompt(
        m, "https://api.example.com", workspace_name="Acme", skills=[_skill()]
    )
    assert cred in prompt
    assert agent_prompt_footer(cred) in prompt
    # A prompt with no numbered steps must not point the agent at a non-existent "STEP 0".
    assert "STEP 0" not in prompt


def test_invite_prompt_carries_token_location_footer():
    m = _marius()
    cred = credential_file_for(m, "Acme")
    prompt = build_invite_prompt(
        m, "https://api.example.com", workspace_name="Acme", skills=[_skill()]
    )
    assert agent_prompt_footer(cred) in prompt
    # The enroll-and-wait STEP 0 block was removed (#97); the prompt must not reference it.
    assert "your token from STEP 0" not in prompt
    assert "STEP 0" not in prompt
    assert "/agent/enroll" not in prompt
