"""Onboarding prompt builders — the ordered FIELD PLAN + the answer-prompt history (#108).

The Workspace Agent is a real (possibly weak) model, so the prompts must keep it on the rails:
the guide lists the exact draft fields in order (no drifting into implementation detail), and
each continuation wake replays the FULL answered history (openclaw-style) so the agent always
knows what is collected.
"""

from __future__ import annotations

from armarius.application.use_cases.onboarding_brain import (
    FIELD_PLAN,
    build_onboarding_answer_prompt,
    build_onboarding_guide_prompt,
)
from tests.support.prompts import field_plan_of


def test_guide_prompt_lists_the_ordered_field_plan():
    guide = build_onboarding_guide_prompt(
        session_id="s1", workspace_name="Studio"
    )
    # The ordered FIELD PLAN tied to the draft body — every required field is named. Read off
    # `FIELD_PLAN` rather than typed out again: a list typed here would agree with the prompt on
    # the day it was written and then quietly stop, which is exactly the failure below.
    for field, _question in FIELD_PLAN:
        assert field in guide, field
    # Anti-drift: tell the agent not to spiral into implementation detail.
    assert "implementation detail" in guide.lower()
    # The two tools are named, and the chat they act on with them. Tools rather than an HTTP
    # address on purpose: the toolset a run is handed *is* its scope (FR-013d), and a prompt
    # that spells out a request teaches the agent to write around the tools it was given.
    assert "`onboarding ask`" in guide
    assert "`onboarding propose`" in guide
    assert "session_id=s1" in guide
    assert "/agent/onboarding/" not in guide


def test_answer_prompt_carries_the_full_answer_history():
    history = [
        ("What are you building?", "A web app"),
        ("A short project name?", "Task Tracker"),
    ]
    prompt = build_onboarding_answer_prompt(
        session_id="s1", history=history
    )
    # Every prior Q/A is replayed (openclaw-style) so the agent knows what is collected.
    assert "Answered so far:" in prompt
    assert "What are you building?" in prompt
    assert "A web app" in prompt
    assert "A short project name?" in prompt
    assert "Task Tracker" in prompt
    # The field plan + the two tools are still present on a continuation wake.
    assert "FIELD PLAN" in prompt
    assert "`onboarding ask`" in prompt
    assert "`onboarding propose`" in prompt
    assert "session_id=s1" in prompt


def test_answer_prompt_handles_empty_history():
    """A continuation turn with no answered pairs still shows the field plan and the tools."""
    prompt = build_onboarding_answer_prompt(
        session_id="s1", history=[]
    )
    assert "Answered so far:" not in prompt
    assert "FIELD PLAN" in prompt
    assert "`onboarding propose`" in prompt


def test_neither_prompt_asks_the_agent_to_design_the_team():
    """T039j — the interview is about the project, not about who works on it (FR-007l).

    It used to end with the agent drafting worker roles: a model inventing titles and
    descriptions of the work, which then stood in the project beside the instructions already
    written on each of the patron's own agents. Told on BOTH wakes, because a continuation wake
    is the only thing a weak model has in front of it by then.
    """
    guide = build_onboarding_guide_prompt(
        session_id="s1", workspace_name="Studio"
    )
    answer = build_onboarding_answer_prompt(
        session_id="s1", history=[]
    )
    for prompt in (guide, answer):
        assert "roster" not in prompt.lower()
        assert "worker role" not in prompt.lower()
        # And it is said outright, not merely left out: a field plan that simply stops has a
        # model guessing what the missing step was.
        assert "the owner picks that themselves" in prompt or "the owner fills themselves" in prompt


def test_both_prompts_name_every_field_in_the_plan():
    """Chốt cho đúng lỗi đã lọt: hai prompt phải nói ra **cùng một** danh sách field.

    Buổi phỏng vấn hỏi **một câu mỗi lượt**, và lượt mở đầu chỉ hỏi câu thứ nhất. Mọi câu sau đó
    đọc `build_onboarding_answer_prompt`. Nên một field chỉ có trong prompt mở đầu là một field
    **không bao giờ được hỏi** — mà nhìn từ mọi phía khác thì tính năng vẫn trông như đã xong:
    cửa nhận, parser đọc, bài kiểm xanh, đặc tả ghi. `worker_count` lọt đúng như thế: nó được
    thêm vào prompt mở đầu, còn prompt của mọi lượt sau vẫn liệt kê năm field và còn bảo *post
    draft sau `context`*. Mọi dự án dựng bằng hỏi–đáp ra đời với đúng một chỗ cho người làm —
    y hệt trước khi có tính năng. Người duyệt PR #272 tìm ra.

    Bài này không kiểm một field cụ thể mà kiểm **quan hệ**: cái gì trong kế hoạch thì phải nằm
    trong **danh sách field** của cả hai prompt. Nên thêm field thứ bảy mà quên một prompt là đỏ
    ngay, không cần ai nhớ.
    """
    plans = {
        "prompt mở đầu": field_plan_of(
            build_onboarding_guide_prompt(session_id="s1", workspace_name="Studio")
        ),
        "prompt của mọi lượt sau": field_plan_of(
            build_onboarding_answer_prompt(
                session_id="s1", history=[("What are you building?", "A shop")]
            )
        ),
    }
    for where, plan in plans.items():
        for field, _question in FIELD_PLAN:
            assert field in plan, f"{field} thiếu trong danh sách field của {where}"


def test_the_last_field_is_the_one_the_draft_is_posted_after():
    """Prompt lượt sau KHÔNG được bảo post draft sau một field ở giữa kế hoạch.

    Đây là nửa thứ hai của cùng một lỗi: kể cả khi field cuối có tên đâu đó trong prompt, một câu
    *"post the draft after `context`"* vẫn cắt buổi phỏng vấn trước field cuối.
    """
    answer = build_onboarding_answer_prompt(session_id="s1", history=[])
    plan = field_plan_of(answer)
    last_field = FIELD_PLAN[-1][0]
    assert last_field in plan, f"danh sách field của prompt lượt sau thiếu {last_field}"
    assert "post the draft" in plan.lower(), plan
    assert plan.index(last_field) < plan.lower().index("post the draft"), plan
    # Và không field nào ở giữa được nêu tên như thứ kết thúc buổi phỏng vấn.
    for field, _question in FIELD_PLAN[:-1]:
        assert f"after `{field}`" not in answer.lower(), field
        assert f"after {field}" not in answer.lower(), field


def test_the_draft_shape_carries_every_field_the_plan_collects():
    """Mẫu JSON và kế hoạch field phải khớp: một mẫu thiếu field là một draft thiếu field."""
    for prompt in (
        build_onboarding_guide_prompt(session_id="s1", workspace_name="Studio"),
        build_onboarding_answer_prompt(session_id="s1", history=[]),
    ):
        shape = next(line for line in prompt.split("\n") if "project={" in line)
        for field, _question in FIELD_PLAN:
            assert f'"{field}"' in shape, f"{field} thiếu trong mẫu draft"
