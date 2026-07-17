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
    # The token-location footer names the exact credential file + the multi-workspace rule.
    assert "~/.armarius/acme-web-platform_alice.json" in prompt
    assert "Authorization: Bearer" in prompt
    assert "never the others" in prompt
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
    assert "Authorization: Bearer" in prompt
    assert "~/.armarius/<workspace>_<agent>.json" in prompt
