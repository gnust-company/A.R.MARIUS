"""Leader-chat prompt content — teammates carry their PROJECT role, not an empty one.

This is the exact complaint that opened issue #87: the Leader saw its team as
``con2 ()`` / ``con3 ()`` — name only, role blank — because the prompt read the empty
workspace-level ``Marius.role`` instead of the project role (SeatGrant.role_key → Role).

It also guards FR-009 (T182): the brief the Leader reads is the **approved** one, the same
version its workers get.
"""

from __future__ import annotations

from uuid import uuid4

from armarius.domain.services.leader_chat_prompt import (
    ChatDirectoryEntry,
    ChatTurn,
    LeaderChatContext,
    build_leader_chat_prompt,
)
from armarius.domain.services.wake_prompt import ProjectBrief


def _ctx(**overrides) -> LeaderChatContext:
    base = dict(
        leader_name="Leo",
        project_id=uuid4(),
        project_name="Calculator",
        workspace_name="Acme",
        project_brief=ProjectBrief(objective="Build a calculator."),
        commission="",
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
        plan_items=[],
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


# ── FR-009: the Leader reads the same approved brief its workers read ──────────────


def test_the_leader_gets_all_five_parts_of_the_approved_brief():
    """The whole brief, not just the objective.

    The worker packet has carried five parts for a while; the Leader — the one who has to
    judge whether a proposal fits the constraints and the scope — was handed a single
    line. Whatever the patron approved is what both sides argue from.
    """
    prompt = build_leader_chat_prompt(
        _ctx(
            project_brief=ProjectBrief(
                objective="Ship a calculator.",
                background="The old one was retired.",
                constraints="No third-party maths libraries.",
                scope="Four operations, nothing else.",
                principles="Correctness before speed.",
            )
        )
    )
    assert "- Objective: Ship a calculator." in prompt
    assert "- Background: The old one was retired." in prompt
    assert "- Constraints: No third-party maths libraries." in prompt
    assert "- Scope: Four operations, nothing else." in prompt
    assert "- Principles: Correctness before speed." in prompt


def test_an_empty_part_of_the_brief_reads_as_absent_not_as_a_gap():
    prompt = build_leader_chat_prompt(
        _ctx(project_brief=ProjectBrief(objective="Ship a calculator."))
    )
    assert "- Background: (none)" in prompt


def test_with_no_approved_brief_the_leader_is_told_so_and_gets_the_commission():
    """Before approval there is no brief in force — and saying so is the point.

    Drafting the brief with the patron is the Leader's job in *planning*, so it must not
    be handed an approved-looking block that nobody approved. What it does get is the
    patron's own commission, labelled as raw material: that text is the patron's writing,
    not the system's, so it rides the packet in whatever language they wrote it.
    """
    prompt = build_leader_chat_prompt(
        _ctx(project_brief=None, commission="Làm hộ tôi cái máy tính bỏ túi.")
    )
    assert "no approved brief" in prompt.lower()
    assert "Làm hộ tôi cái máy tính bỏ túi." in prompt
    # Never dressed up as the approved one.
    assert "- Objective:" not in prompt


def test_with_neither_a_brief_nor_a_commission_nothing_is_invented():
    prompt = build_leader_chat_prompt(_ctx(project_brief=None, commission=""))
    assert "no approved brief" in prompt.lower()
    assert "- Objective:" not in prompt


# ── lõi bốn phần ở cửa dự án (FR-044, FR-044a) ───────────────────────────────────


def test_a_wake_says_why_the_leader_is_awake_instead_of_leaving_it_to_guess():
    """Phần thứ ba của lõi. Trước đây cửa dự án nhét câu đánh thức vào *lịch sử trò
    chuyện*, nên gói tin không có mục nào trả lời "vì sao lúc này"."""
    prompt = build_leader_chat_prompt(
        _ctx(wake_reason="The orchestration sweep found 3 snag(s) on the board.")
    )
    assert "## Why you were woken" in prompt
    assert "found 3 snag(s)" in prompt


def test_the_extra_of_this_call_type_rides_under_the_reason():
    prompt = build_leader_chat_prompt(
        _ctx(
            wake_reason="The orchestration sweep found 1 snag(s) on the board.",
            wake_detail="## The snags this sweep found\n\n- P1-2 — Nút lưu: blocked.",
        )
    )
    why = prompt[prompt.index("## Why you were woken") :]
    assert "P1-2 — Nút lưu: blocked." in why


def test_a_patron_message_carries_no_wake_section_at_all():
    """FR-044a cấm ép mọi loại lời gọi dùng chung một khuôn. Người chủ vừa gõ một câu thì
    lý do nằm ngay đó — dựng thêm một mục "vì sao bị gọi" rỗng là thêm nhiễu."""
    prompt = build_leader_chat_prompt(_ctx())
    assert "## Why you were woken" not in prompt


def test_a_system_line_is_not_put_in_the_leaders_mouth():
    """Câu do hệ phát không phải người chủ nói, cũng không phải Trưởng dự án nói. Gán cho
    "You" là đưa lời hệ thống vào miệng nó, và nó đọc lại chính thông báo đánh thức của
    mình như một thứ mình đã phát biểu."""
    prompt = build_leader_chat_prompt(
        _ctx(
            recent_turns=[
                ChatTurn(role="patron", text="Tình hình sao rồi?"),
                ChatTurn(role="leader", text="Đang chạy tốt."),
                ChatTurn(role="system", text="A worker handed P1-3 back."),
            ]
        )
    )
    assert "- Patron: Tình hình sao rồi?" in prompt
    assert "- You: Đang chạy tốt." in prompt
    assert "- System: A worker handed P1-3 back." in prompt


def test_an_empty_team_says_so_rather_than_vanishing():
    """FR-045 ở phần thứ tư của lõi: mục biến mất thì Trưởng dự án không phân biệt được
    "chưa ai được cấp ghế" với "danh sách đội hỏng", và nó sẽ tự nghĩ ra một đội."""
    prompt = build_leader_chat_prompt(_ctx(directory=[]))
    assert "## Your team (workers you can assign)" in prompt
    assert "nobody else holds a seat" in prompt
