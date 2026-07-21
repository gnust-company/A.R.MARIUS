"""Onboarding prompt builders — the ordered FIELD PLAN + the answer-prompt history (#108).

The Workspace Agent is a real (possibly weak) model, so the prompts must keep it on the rails:
the guide lists the exact draft fields in order (no drifting into implementation detail), and
each continuation wake replays the FULL answered history (openclaw-style) so the agent always
knows what is collected.
"""

from __future__ import annotations

from armarius.application.use_cases.onboarding_brain import (
    build_onboarding_answer_prompt,
    build_onboarding_guide_prompt,
)


def test_guide_prompt_lists_the_ordered_field_plan():
    guide = build_onboarding_guide_prompt(
        base_url="http://api.test", session_id="s1", workspace_name="Studio"
    )
    # The ordered FIELD PLAN tied to the draft body — every required field is named.
    for field in ("objective", "name", "roster", "success_metrics", "target_date", "context"):
        assert field in guide, field
    # Anti-drift: tell the agent not to spiral into implementation detail.
    assert "implementation detail" in guide.lower()
    # The two callback endpoints are present and self-sufficient.
    assert "/agent/onboarding/s1/question" in guide
    assert "/agent/onboarding/s1/complete" in guide


def test_answer_prompt_carries_the_full_answer_history():
    history = [
        ("What are you building?", "A web app"),
        ("A short project name?", "Task Tracker"),
    ]
    prompt = build_onboarding_answer_prompt(
        base_url="http://api.test", session_id="s1", history=history
    )
    # Every prior Q/A is replayed (openclaw-style) so the agent knows what is collected.
    assert "Answered so far:" in prompt
    assert "What are you building?" in prompt
    assert "A web app" in prompt
    assert "A short project name?" in prompt
    assert "Task Tracker" in prompt
    # The field plan + endpoints are still present on a continuation wake.
    assert "FIELD PLAN" in prompt
    assert "/agent/onboarding/s1/question" in prompt
    assert "/agent/onboarding/s1/complete" in prompt


def test_answer_prompt_handles_empty_history():
    """A continuation wake with no answered pairs still shows the field plan + endpoints."""
    prompt = build_onboarding_answer_prompt(
        base_url="http://api.test", session_id="s1", history=[]
    )
    assert "Answered so far:" not in prompt
    assert "FIELD PLAN" in prompt
    assert "/agent/onboarding/s1/complete" in prompt
