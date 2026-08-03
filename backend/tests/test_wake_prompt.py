"""Wake prompt content — every wake names its workspace/project + credential file (#15).

Spec 001 Story 4 adds the shape of the packet itself: eight mandatory parts (FR-044) and
the rule that an empty part is *stated* as empty rather than dropped (FR-045). Dropping a
part is what makes a packet ambiguous — the agent cannot tell "nobody has said anything
yet" apart from "the section broke", so it guesses. Every part is therefore always
rendered.
"""

from __future__ import annotations

from armarius.domain.entities.run import WakeSource
from armarius.domain.services.wake_prompt import (
    NONE_MARKER,
    DirectoryEntry,
    ProjectBrief,
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
            credential_file="$HOME/.armarius/acme-web-platform_alice.json",
        )
    )
    assert "## Where you are" in prompt
    assert "Acme Web Platform" in prompt
    assert "Settings Redesign" in prompt
    # The soft credential HINT names the exact file and nudges reading once + reusing (#108).
    assert "$HOME/.armarius/acme-web-platform_alice.json" in prompt
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
    assert "$HOME/.armarius/<workspace>_<agent>.json" in prompt


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


# ── spec 001 Story 4: the eight-part packet (FR-044, FR-045, FR-046) ────────────


# The eight parts, in the order FR-044 lists them. Kept as data so a part that quietly
# stops being rendered fails here by name instead of hiding behind a passing suite.
EIGHT_PARTS = (
    "You are Alice",  # 1. the agent's role on this project
    "## Project context",  # 2. the approved brief
    "## Task:",  # 3. the task, its description and status
    "## Why you were woken",  # 4. the reason, in a sentence
    "## Your teammates on this project",  # 5. the directory with liveness
    "## New messages since you last worked",  # 6. what happened while it slept
    "## Your recorded next action",  # 7. the work waiting to be picked up
    "## Where to put your work and how to report status",  # 8. how to hand work back
)


def test_the_packet_carries_all_eight_parts():
    prompt = build_wake_prompt(
        _ctx(
            self_role="Backend",
            project_brief=ProjectBrief(
                objective="Ra mắt nền tảng trong quý này.",
                background="Nền cũ hết tải.",
                constraints="Không đổi cơ sở dữ liệu.",
                scope="Chỉ phần máy chủ.",
                principles="Đặc tả đi trước.",
            ),
        )
    )
    for part in EIGHT_PARTS:
        assert part in prompt, f"thiếu phần: {part}"

    # And in the order the requirement lists them — an agent reads top-down, so the brief
    # has to arrive before the task it is supposed to judge.
    positions = [prompt.index(part) for part in EIGHT_PARTS]
    assert positions == sorted(positions), positions


def test_every_empty_part_says_so_instead_of_disappearing():
    """FR-045. A dropped section reads as 'this packet is broken'; an empty one that says
    so reads as 'there is genuinely nothing here'. Only the second is actionable."""
    prompt = build_wake_prompt(
        _ctx(
            task_description=None,
            next_action=None,
            directory=[],
            new_messages=[],
            project_brief=None,
        )
    )
    for part in EIGHT_PARTS:
        assert part in prompt, f"phần rỗng bị bỏ rơi thay vì ghi rõ: {part}"
    # Five of them are empty in this packet: brief, description, teammates, messages,
    # next action. Each must carry the explicit marker.
    assert prompt.count(NONE_MARKER) >= 5, prompt


def test_the_approved_brief_reaches_the_worker_not_just_the_leader():
    """The gap Story 4 exists to close: the Leader saw the objective in its chat prompt
    while the worker doing the job never did."""
    prompt = build_wake_prompt(
        _ctx(
            project_brief=ProjectBrief(
                objective="Ra mắt nền tảng trong quý này.",
                background="Nền cũ hết tải.",
                constraints="Không đổi cơ sở dữ liệu.",
                scope="Chỉ phần máy chủ.",
                principles="Đặc tả đi trước.",
            )
        )
    )
    assert "Ra mắt nền tảng trong quý này." in prompt
    assert "Không đổi cơ sở dữ liệu." in prompt
    assert "Đặc tả đi trước." in prompt


def test_a_brief_with_holes_names_the_holes():
    prompt = build_wake_prompt(
        _ctx(project_brief=ProjectBrief(objective="Ra mắt nền tảng.", background=""))
    )
    assert "Ra mắt nền tảng." in prompt
    brief = prompt[prompt.index("## Project context") : prompt.index("## Task:")]
    # Four of the five parts are empty here and each says so.
    assert brief.count(NONE_MARKER) == 4, brief


def test_where_to_submit_is_its_own_part_not_a_line_of_advice():
    """FR-044 part 8. Buried in a bullet list of general advice it competes with six other
    'don't forget' lines; as its own heading it is the thing the agent looks up."""
    prompt = build_wake_prompt(_ctx())
    submit = prompt.index("## Where to put your work and how to report status")
    how = prompt.index("## How to act")
    assert submit < how
    section = prompt[submit:how]
    assert "artifact" in section.lower()
    assert "next_action" in section


def test_the_reason_is_a_sentence_a_person_can_read():
    """FR-046. `source: comment` names a code path; it does not say why this agent is being
    pulled out of sleep right now."""
    prompt = build_wake_prompt(_ctx(source=WakeSource.COMMENT, reason="Bob asked you a question"))
    why = prompt[prompt.index("## Why you were woken") :]
    assert "Bob asked you a question" in why


def test_a_wake_with_no_stated_reason_still_says_something_readable():
    prompt = build_wake_prompt(_ctx(reason=None))
    why = prompt[
        prompt.index("## Why you were woken") : prompt.index("## Your teammates")
    ]
    assert str(WakeSource.ASSIGNMENT) in why
