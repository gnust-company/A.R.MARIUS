"""Shared token-location footer — every system→agent prompt names the credential file (#80).

The footer (modeled on openclaw-mission-control) is token-free and appended to the invite,
skill-install and onboarding prompts so the agent always knows where its token lives.
"""

from __future__ import annotations

from armarius.application.ports.adapter import (
    AdapterCapabilities,
    Diagnostics,
    ExecContext,
    ExecResult,
    MariusAdapter,
)
from armarius.application.use_cases.onboarding import (
    build_invite_prompt,
    build_skill_install_prompt,
    credential_file_for,
)
from armarius.domain.entities.marius import Marius
from armarius.domain.entities.run import RunStatus
from armarius.domain.entities.skill import Skill
from armarius.domain.services.agent_prompt import agent_prompt_footer
from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry

_SECRET = "arm_secret_should_never_appear_in_a_footer"


def _marius() -> Marius:
    return Marius(name="Marin", role="Backend", adapter_type="echo", agent_token=_SECRET)


def _skill() -> Skill:
    return Skill(slug="armarius-http", name="Armarius HTTP API", description="Drive the workspace.")


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


class _ToolCallingAdapter(MariusAdapter):
    """A second runtime that installs skills by calling a tool rather than writing files.

    Defined here rather than imported: the point of the test below is that *two* runtimes
    give *two* answers, and it must keep making that point no matter which real adapters
    happen to be registered this month.
    """

    type = "tool_calling"
    capabilities = AdapterCapabilities(resumable=True, streaming=False, transport="http")
    skill_install_steps = (
        "Install skills using the skill_manage tool:",
        "  • Call skill_manage with the slug and the file tree fetched below",
    )

    async def execute(self, ctx: ExecContext) -> ExecResult:  # pragma: no cover - unused
        return ExecResult(status=RunStatus.COMPLETED)

    async def test_environment(self, config: dict) -> Diagnostics:  # pragma: no cover - unused
        return Diagnostics(ok=True)


# ── the install steps come from the adapter, not from a branch (T157, FR-083) ────


def test_the_install_steps_come_from_the_adapter_that_will_run_the_agent():
    """Two runtimes, two sets of instructions, and the use case knows about neither.

    ``_skill_block`` used to answer *how do I install a skill here* with a chain of
    ``if adapter_type == ...``. The text is the same; where it comes from is the point —
    a new runtime now ships its own steps and the business layer is untouched
    (Hiến pháp III).
    """
    registry = InMemoryAdapterRegistry()
    registry.register(_ToolCallingAdapter())
    registry.register(EchoAdapter())
    skills = [_skill()]

    on_tool_calling = build_invite_prompt(
        Marius(name="Marin", role="Backend", adapter_type="tool_calling"),
        "https://api.test",
        skills=skills,
        adapters=registry,
    )
    assert "skill_manage" in on_tool_calling

    on_echo = build_invite_prompt(
        Marius(name="Echo-2", role="Backend", adapter_type="echo"),
        "https://api.test",
        skills=skills,
        adapters=registry,
    )
    assert "~/.echo/skills/" in on_echo
    assert "skill_manage" not in on_echo


def test_a_runtime_nothing_is_registered_for_gets_the_neutral_wording():
    """An agent can only be invited on a registered adapter (``InviteService.invite``
    raises otherwise), so this is the safety net rather than a path anyone walks. It
    still has to say something usable instead of naming a runtime at random."""
    prompt = build_skill_install_prompt(
        Marius(name="Nobody", role="Backend", adapter_type="a_runtime_we_never_heard_of"),
        "https://api.test",
        skills=[_skill()],
        adapters=InMemoryAdapterRegistry(),
    )
    assert "your runtime's mechanism" in prompt
    assert "skill_manage" not in prompt
