"""Leader-chat prompt content — teammates carry their PROJECT role, not an empty one.

This is the exact complaint that opened issue #87: the Leader saw its team as
``con2 ()`` / ``con3 ()`` — name only, role blank — because the prompt read the empty
workspace-level ``Marius.role`` instead of the project role (SeatGrant.role_key → Role).
"""

from __future__ import annotations

from uuid import uuid4

from armarius.domain.services.leader_chat_prompt import (
    ChatDirectoryEntry,
    LeaderChatContext,
    build_leader_chat_prompt,
)


def _ctx(**overrides) -> LeaderChatContext:
    base = dict(
        leader_name="Leo",
        project_id=uuid4(),
        project_name="Calculator",
        workspace_name="Acme",
        project_context="Build a calculator.",
        directory=[
            ChatDirectoryEntry(
                marius_id=uuid4(),
                name="con2",
                role="Backend",
                liveness="online",
                role_description="Owns the API and database.",
            )
        ],
        recent_turns=[],
        yolo_mode=False,
    )
    base.update(overrides)
    return LeaderChatContext(**base)


def test_team_block_names_each_worker_project_role_and_description():
    prompt = build_leader_chat_prompt(_ctx())
    assert "## Your team (workers you can assign)" in prompt
    # Role title present (NOT an empty "con2 ()").
    assert "- con2 (Backend) [online]" in prompt
    assert "role: Owns the API and database." in prompt
    # The regression we are guarding against: an empty role paren must never appear.
    assert "con2 ()" not in prompt


def test_leader_header_states_its_own_role_description():
    prompt = build_leader_chat_prompt(
        _ctx(leader_role_description="Coordinates the whole project and shapes tasks.")
    )
    assert "You are Leo, the Leader of this project inside Armarius." in prompt
    assert "Coordinates the whole project and shapes tasks." in prompt


def test_worker_role_falls_back_to_key_but_never_blank():
    # If the Role row is missing, the service passes the raw role_key rather than "" so the
    # entry is never blank; a blank role is exactly the bug (#87).
    prompt = build_leader_chat_prompt(
        _ctx(
            directory=[
                ChatDirectoryEntry(
                    marius_id=uuid4(), name="con3", role="backend", liveness="offline"
                )
            ]
        )
    )
    assert "- con3 (backend) [offline]" in prompt
    assert "con3 ()" not in prompt
