"""Khuôn gói tin đánh thức — lõi bốn phần, phần riêng theo loại lời gọi (FR-044, FR-044a).

Luật cũ là **tám phần cho mọi lời gọi**. Nó sai ở chỗ không nhìn ai đang nhận: năm trong tám
phần chỉ có nghĩa với người đang *làm* đầu việc. Trưởng dự án bị kéo vào một đầu việc để chấm
hoặc để quyết, thế mà vẫn nhận ô "việc kế tiếp của bạn" và cả đoạn dặn nộp thành phẩm ở đâu —
những ô mà muốn điền cho hết thì phải bịa.

Nên giờ: **lõi bốn phần** không lời gọi nào được miễn (vai của mình ở dự án này, Bối cảnh đã
duyệt, vì sao bị gọi, đồng đội và ai đang trực), rồi phần riêng của từng loại. FR-045 vẫn giữ
nguyên và chỉ nói chuyện *bên trong* những phần một gói tin có mang: phần nào có mà rỗng thì
phải ghi rõ là rỗng, chứ không được biến mất — mất hẳn một mục thì agent không phân biệt được
"không có gì" với "chỗ này hỏng", và nó sẽ đoán.

Chữ trong gói tin là tiếng Anh: đây là bản của agent, mà agent không có ngôn ngữ để chọn
(Hiến pháp VII).
"""

from __future__ import annotations

from armarius.domain.entities.run import WakeSource
from armarius.domain.services.wake_prompt import (
    NONE_MARKER,
    DirectoryEntry,
    ProjectBrief,
    ThreadMessage,
    WakeAudience,
    WakeContext,
    build_wake_prompt,
)


def _ctx(**overrides) -> WakeContext:  # noqa: ANN003
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


# ── lõi bốn phần (FR-044) ────────────────────────────────────────────────────────

# Bốn phần, theo đúng thứ tự yêu cầu liệt kê. Giữ ở dạng dữ liệu để một phần lặng lẽ thôi
# được dựng thì hỏng ngay tại đây kèm tên nó, chứ không nấp sau một bộ kiểm toàn xanh.
CORE_PARTS = (
    "You are Alice",  # 1. vai của agent ở dự án này
    "## Project context",  # 2. Bối cảnh đã duyệt
    "## Why you were woken",  # 3. vì sao bị gọi, thành câu
    "## Your teammates on this project",  # 4. đồng đội kèm trạng thái trực tuyến
)

# Phần riêng của loại "gọi thợ vào một đầu việc" (FR-044a).
WORKER_EXTRAS = (
    "## Task:",
    "## New messages since you last worked",
    "## Your recorded next action",
    "## Where to put your work and how to report status",
)


def test_every_packet_carries_the_four_part_core():
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
    for part in CORE_PARTS:
        assert part in prompt, f"thiếu phần lõi: {part}"

    # Và theo đúng thứ tự ấy — agent đọc từ trên xuống, nên Bối cảnh phải tới trước cái nó
    # được giao để đối chiếu.
    positions = [prompt.index(part) for part in CORE_PARTS]
    assert positions == sorted(positions), positions

    # Lõi đứng trước phần riêng: biết mình là ai rồi mới tới việc phải làm.
    assert prompt.index(CORE_PARTS[-1]) < prompt.index("## Task:")


def test_a_worker_called_into_a_task_gets_the_task_parts():
    prompt = build_wake_prompt(_ctx(audience=WakeAudience.WORKER))
    for part in WORKER_EXTRAS:
        assert part in prompt, f"thiếu phần riêng của thợ: {part}"


def test_the_leader_pulled_onto_a_task_is_not_asked_to_fill_a_workers_boxes():
    """FR-044a. Trưởng dự án bị kéo vào một đầu việc để chấm hoặc để quyết — nó không nộp
    thành phẩm nào cả. Ô "việc kế tiếp của bạn" và đoạn dặn nộp ở đâu là ô của vai khác, và
    một ô điền bừa còn tệ hơn một ô không có."""
    prompt = build_wake_prompt(_ctx(audience=WakeAudience.LEADER))

    for part in CORE_PARTS:
        assert part in prompt, f"lõi phải có ở mọi loại lời gọi: {part}"
    # Đầu việc và trao đổi trên nó thì vẫn phải có: không cho xem thì lấy gì mà chấm.
    assert "## Task: Add dark mode" in prompt
    assert "## New messages since you last worked" in prompt

    assert "## Your recorded next action" not in prompt
    assert "## Where to put your work and how to report status" not in prompt
    assert "publish-artifact" not in prompt
    # Và được dặn đúng việc của mình.
    assert "not the one doing this task" in prompt


def test_every_empty_part_says_so_instead_of_disappearing():
    """FR-045. Một mục bị bỏ rơi đọc thành "gói tin này hỏng"; một mục rỗng mà nói rõ là
    rỗng thì đọc thành "chỗ này thật sự không có gì". Chỉ cái thứ hai hành động được."""
    prompt = build_wake_prompt(
        _ctx(
            task_description=None,
            next_action=None,
            directory=[],
            new_messages=[],
            project_brief=None,
        )
    )
    for part in CORE_PARTS + WORKER_EXTRAS:
        assert part in prompt, f"phần rỗng bị bỏ rơi thay vì ghi rõ: {part}"
    # Năm chỗ rỗng trong gói tin này: Bối cảnh, mô tả, đồng đội, tin nhắn, việc kế tiếp.
    assert prompt.count(NONE_MARKER) >= 5, prompt


def test_an_empty_part_that_belongs_to_the_other_role_is_not_conjured_up():
    """FR-045 cấm im lặng ở phần một loại lời gọi **có mang**; nó không bắt loại này phải
    mang phần của loại kia. Đọc ngược lại là quay về đúng cái khuôn tám phần vừa bỏ."""
    prompt = build_wake_prompt(
        _ctx(audience=WakeAudience.LEADER, next_action=None, new_messages=[])
    )
    assert "## New messages since you last worked" in prompt  # phần của nó, rỗng thì nói
    assert "## Your recorded next action" not in prompt  # không phải phần của nó


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
    brief = prompt[prompt.index("## Project context") : prompt.index("## Why you were woken")]
    # Four of the five parts are empty here and each says so.
    assert brief.count(NONE_MARKER) == 4, brief


def test_where_to_submit_is_its_own_part_not_a_line_of_advice():
    """Buried in a bullet list of general advice it competes with six other 'don't forget'
    lines; as its own heading it is the thing the agent looks up."""
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
