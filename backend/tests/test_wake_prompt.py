"""Wake prompt content — every wake names its workspace/project + credential file (#15)."""

from __future__ import annotations

from armarius.domain.entities.run import WakeSource
from armarius.domain.services.wake_prompt import (
    DirectoryEntry,
    ThreadMessage,
    WakeContext,
    build_wake_prompt,
)


def _ctx(**overrides) -> WakeContext:
    base = dict(
        marius_name="Alice",
        task_title="Add dark mode",
        task_status="in_progress",
        task_description="Dark theme for settings.",
        next_action="Wire the ThemeProvider.",
        directory=[DirectoryEntry(name="Bob", role="Design", skills=["ux"], liveness="idle")],
        new_messages=[ThreadMessage(author="human", body="ping")],
        source=WakeSource.ASSIGNMENT,
        reason="you were assigned",
    )
    base.update(overrides)
    return WakeContext(**base)


def test_prompt_names_workspace_project_and_credential_file():
    prompt = build_wake_prompt(
        _ctx(
            workspace_name="Acme Web Platform",
            project_name="Settings Redesign",
            credential_file="~/.armarius/acme-web-platform_alice.json",
        )
    )
    assert "## Where you are" in prompt
    assert "Acme Web Platform" in prompt
    assert "Settings Redesign" in prompt
    # The soft credential HINT names the exact file and nudges reading once + reusing (#108).
    assert "~/.armarius/acme-web-platform_alice.json" in prompt
    assert "ARMARIUS HINT" in prompt
    assert "cat" in prompt
    # Orientation still leads the prompt (workspace/project before the task brief).
    assert prompt.index("## Where you are") < prompt.index("## Task:")


def test_prompt_without_workspace_context_omits_the_orientation_but_never_the_footer():
    prompt = build_wake_prompt(_ctx())
    assert "## Where you are" not in prompt
    # The rest of the prompt is intact.
    assert "## Task: Add dark mode" in prompt
    assert "## Why you were woken" in prompt
    # The footer is UNCONDITIONAL: even with no workspace context, a task-wake must still
    # tell the agent where its token lives — falling back to the default location (#80).
    assert "ARMARIUS HINT" in prompt
    assert "~/.armarius/<workspace>_<agent>.json" in prompt


def test_header_states_the_agents_own_project_role_and_description():
    # The woken agent must know its OWN project role + what it entails (issue #87 / spec 03 §3.1).
    prompt = build_wake_prompt(
        _ctx(
            self_role="Backend",
            self_role_description="Owns the API and database work.",
        )
    )
    assert "You are Alice, the Backend on this project" in prompt
    assert "Owns the API and database work." in prompt
    # The generic fallback line must NOT appear when a project role is known.
    assert "an agent collaborating inside Armarius" not in prompt


def test_header_falls_back_when_agent_holds_no_project_role():
    prompt = build_wake_prompt(_ctx())  # self_role defaults to ""
    assert "an agent collaborating inside Armarius" in prompt


def test_directory_shows_teammate_project_role_and_description():
    # Teammates are listed with their PROJECT role title (not an empty workspace role),
    # so the agent knows who does what (issue #87 / spec 03 §3.1).
    prompt = build_wake_prompt(
        _ctx(
            directory=[
                DirectoryEntry(
                    name="Bob",
                    role="Design",
                    skills=["ux"],
                    liveness="idle",
                    role_description="Owns UX and visual design.",
                )
            ]
        )
    )
    assert "## Your teammates on this project" in prompt
    assert "- @Bob (Design) [idle] skills: ux" in prompt
    assert "role: Owns UX and visual design." in prompt


def test_directory_renders_dash_when_role_title_is_empty():
    prompt = build_wake_prompt(
        _ctx(directory=[DirectoryEntry(name="Bob", role="", skills=[], liveness="idle")])
    )
    assert "- @Bob (—) [idle] skills: —" in prompt
