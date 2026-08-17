"""Thân lời gọi ở cửa dự án: lưu mã kèm tham số, không lưu câu (Hiến pháp VII, T194).

Bảy chỗ trong mã tự soạn lấy một đoạn văn xuôi tiếng Việt rồi đưa thẳng vào gói tin gửi
Trưởng dự án. Tưởng là chuyện dịch, nhưng không phải: đoạn ấy được ghi vào **chính luồng trò
chuyện** người chủ đang mở, nên nó có **hai người đọc** — agent đọc bản của agent, người chủ
đọc bản của mình. Một câu viết sẵn lúc phát chỉ phục vụ được một trong hai.

Nên cắt đôi:
  * **cớ gọi dậy** — cả hai bên cùng đọc ⇒ lưu mã kèm tham số, mỗi bên tự dựng câu;
  * **phần riêng của loại lời gọi** — chỉ agent đọc ⇒ tiếng Anh, viết thẳng.

Và trên đường đi ra màn hình, câu ấy từng bị gắn cho chính Trưởng dự án — luồng trò chuyện
chỉ biết hai vai, nên cái gì không phải người chủ đều thành lời của nó.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from armarius.domain.entities.marius import Liveness
from armarius.domain.entities.run import WakeSource
from armarius.domain.services.orchestration_cadence import Snag, SnagKind
from armarius.domain.services.wake_prompt import cadence_detail
from armarius.domain.services.wake_reason import reason as wake_reason

pytestmark = pytest.mark.asyncio

# Dấu thanh tiếng Việt. Một chữ nào trong này lọt vào bản của agent là hỏng luật.
_VIETNAMESE = "ăâđêôơưàáảãạèéẻẽẹìíỉĩịòóỏõọùúủũụỳýỷỹỵ"


def _has_vietnamese(text: str) -> bool:
    lowered = text.lower()
    return any(ch in lowered for ch in _VIETNAMESE)


async def _leader_seated(uow_factory, chat):  # noqa: ANN001, ANN202
    """Một dự án có Trưởng dự án đang trực tuyến, sẵn sàng nhận lời gọi."""
    from tests.test_wake_causes_are_enforced import _world  # cùng bộ dựng cảnh

    project, leader, _worker, _task = await _world(uow_factory)
    async with uow_factory() as uow:
        online = await uow.mariuses.get(leader.id)
        assert online is not None
        online.liveness = Liveness.ONLINE
        await uow.mariuses.update(online)
        await uow.commit()
    return project, leader


async def test_the_stored_turn_keeps_the_cause_as_a_code_and_its_parameters(
    uow_factory,  # noqa: ANN001
) -> None:
    """Người chủ mở buồng trò chuyện lên và phải đọc được bằng tiếng của mình. Câu đã dựng
    sẵn thì đóng băng luôn thứ tiếng; mã kèm tham số thì không."""
    from tests.test_wake_causes_are_enforced import _chat

    chat = _chat(uow_factory)
    project, _leader = await _leader_seated(uow_factory, chat)

    await chat.notify(
        project_id=project.id,
        source=WakeSource.TASK_IN_REVIEW,
        reason=wake_reason("task_in_review", task="P1-2"),
        detail="Judge it against the task's acceptance criteria.",
    )

    view = await chat.get_or_open(project.id)
    turn = view.conversation.transcript[-1]
    assert turn["role"] == "system", "lời của hệ không được đội lốt lời của Trưởng dự án"
    assert turn["code"] == "task_in_review"
    assert turn["params"] == {"task": "P1-2"}


async def test_nothing_the_agent_reads_is_written_in_vietnamese(
    uow_factory,  # noqa: ANN001
) -> None:
    """Bản của agent phải sạch tiếng Việt — cớ lẫn phần riêng."""
    from tests.test_wake_causes_are_enforced import _chat

    chat = _chat(uow_factory)
    project, _leader = await _leader_seated(uow_factory, chat)

    await chat.notify(
        project_id=project.id,
        source=WakeSource.PROJECT_READY,
        reason=wake_reason("roster_complete"),
        detail="Settle the project brief with the patron first.",
    )

    view = await chat.get_or_open(project.id)
    turn = view.conversation.transcript[-1]
    assert not _has_vietnamese(str(turn["text"])), turn["text"]
    assert not _has_vietnamese(str(turn["detail"])), turn["detail"]


async def test_a_call_with_nothing_extra_to_say_carries_no_extra(
    uow_factory,  # noqa: ANN001
) -> None:
    """FR-044a: phần riêng là của **loại** lời gọi, không phải ô bắt buộc. Loại nào không
    có gì thêm thì để trống, chứ không đi bịa một câu cho đủ khuôn."""
    from tests.test_wake_causes_are_enforced import _chat

    chat = _chat(uow_factory)
    project, _leader = await _leader_seated(uow_factory, chat)

    await chat.notify(
        project_id=project.id,
        source=WakeSource.PATRON_DECISION,
        reason=wake_reason("patron_rejected_output", task="P1-2", note="chưa đúng ý"),
    )

    view = await chat.get_or_open(project.id)
    turn = view.conversation.transcript[-1]
    assert turn["detail"] == ""
    # Chữ người chủ tự gõ thì giữ nguyên, kể cả trong bản của agent: người viết ra nó, nên
    # nó không phải chữ của hệ để mà dịch.
    assert turn["params"]["note"] == "chưa đúng ý"


# ── điểm treo: cùng một sự việc, hai người đọc (FR-052) ──────────────────────────


async def test_a_snag_hands_over_its_parts_so_each_reader_can_word_it_itself() -> None:
    """Điểm treo hiện trên bảng dự án cho người chủ **và** đi trong gói tin cho Trưởng dự
    án. Bản của agent là tiếng Anh; màn hình dựng câu của mình từ mã và các mảnh dữ liệu."""
    snags = [
        Snag(
            kind=SnagKind.BLOCKED,
            task_id=uuid4(),
            identifier="P1-2",
            title="Nút lưu",
            detail="P1-2 — Nút lưu: blocked.",
        )
    ]
    extra = cadence_detail(snags)

    assert "P1-2" in extra, "nêu đích danh đầu việc, không nói chung chung (FR-054)"
    # Tiêu đề do người viết ra thì giữ nguyên; phần còn lại là chữ của hệ nên phải tiếng Anh.
    assert "blocked" in extra
    assert "đang bị chặn" not in extra
    # Và các mảnh vẫn còn nguyên để màn hình tự dựng câu tiếng Việt.
    assert snags[0].title == "Nút lưu"
    assert snags[0].identifier == "P1-2"
