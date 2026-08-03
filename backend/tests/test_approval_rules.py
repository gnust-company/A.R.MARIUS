"""Luật hai chữ ký, dạng hàm thuần (spec 001 FR-033, FR-037, FR-041, FR-042).

Không đụng cơ sở dữ liệu: người gọi đưa vào những chữ ký đã có, luật trả lời đầu việc đã
đủ điều kiện đóng chưa và ai còn thiếu. Đây là chỗ "không có xong giả" thành một câu kiểm
được, chứ không phải một lời hứa nằm trong tài liệu.

Ba điều luật phải giữ:

  1. Một chữ ký không đóng được việc, dù là chữ ký của ai.
  2. Một lần **từ chối** không bị một lần tán thành sau đó xoá đi im lặng — vòng từ chối
     phải kết thúc bằng việc đầu việc quay lại *đang làm*, rồi ký lại từ đầu.
  3. Công tắc tự động công nhận không được đụng tới ba quyết định cấp dự án (FR-037).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from armarius.domain.entities.approval import (
    Approval,
    ApprovalResult,
    SignerKind,
)
from armarius.domain.services.approval_rules import (
    PROJECT_DECISIONS_OUTSIDE_AUTO_APPROVAL,
    ProjectDecision,
    is_closable,
    missing_signatures,
    rejection_rounds,
)
from armarius.shared.clock import utcnow


def _sign(
    kind: SignerKind,
    result: ApprovalResult = ApprovalResult.APPROVE,
    *,
    auto: bool = False,
) -> Approval:
    return Approval(
        task_id=uuid4(),
        signer_kind=kind,
        result=result,
        # Từ chối bắt buộc có lý do — luật này nằm ngay trong thực thể, nên bài kiểm phải
        # tuân theo chứ không được nới ra cho tiện.
        reason="Chưa đạt tiêu chí." if result is ApprovalResult.REJECT else None,
        is_auto=auto,
        signed_at=utcnow(),
    )


# ── 1. đủ hai chữ ký mới đóng ────────────────────────────────────────────────


def test_no_signature_closes_nothing() -> None:
    assert is_closable([]) is False
    assert missing_signatures([]) == (SignerKind.LEADER, SignerKind.PATRON)


def test_the_leader_alone_cannot_close() -> None:
    """Đây chính là lối tắt mà Câu chuyện 3 dựng lên để chặn."""
    signed = [_sign(SignerKind.LEADER)]
    assert is_closable(signed) is False
    assert missing_signatures(signed) == (SignerKind.PATRON,)


def test_the_patron_alone_cannot_close() -> None:
    """Mặt còn lại: người chủ gật trước cũng không đủ — Trưởng dự án vẫn phải chấm."""
    signed = [_sign(SignerKind.PATRON)]
    assert is_closable(signed) is False
    assert missing_signatures(signed) == (SignerKind.LEADER,)


def test_two_signatures_close_the_task() -> None:
    signed = [_sign(SignerKind.LEADER), _sign(SignerKind.PATRON)]
    assert is_closable(signed) is True
    assert missing_signatures(signed) == ()


def test_the_same_side_signing_twice_is_still_one_side() -> None:
    """Hai chữ ký cùng phía không thành hai chữ ký."""
    signed = [_sign(SignerKind.LEADER), _sign(SignerKind.LEADER)]
    assert is_closable(signed) is False
    assert missing_signatures(signed) == (SignerKind.PATRON,)


def test_an_auto_signature_counts_as_the_patron_signature() -> None:
    """Công tắc bật thì chữ ký người chủ coi như có sẵn — nhưng vẫn là một chữ ký thật,
    có dòng của nó, chứ không phải một phép bỏ qua (FR-039)."""
    signed = [_sign(SignerKind.LEADER), _sign(SignerKind.PATRON, auto=True)]
    assert is_closable(signed) is True


# ── 2. một lần từ chối không bị xoá im lặng ──────────────────────────────────


def test_a_rejection_blocks_closing_even_with_the_other_signature() -> None:
    signed = [_sign(SignerKind.LEADER), _sign(SignerKind.PATRON, ApprovalResult.REJECT)]
    assert is_closable(signed) is False


def test_a_later_approval_does_not_erase_an_earlier_rejection_in_the_same_round() -> None:
    """Từ chối rồi tán thành ngay trong cùng một vòng thì vẫn không đóng.

    Vòng từ chối phải đi trọn: đầu việc về *đang làm*, thợ sửa, nộp lại, rồi ký lại từ
    đầu. Cho phép "ký đè" ở đây là mở đúng lối tắt mà cả câu chuyện này dựng lên để chặn.
    """
    signed = [
        _sign(SignerKind.LEADER),
        _sign(SignerKind.PATRON, ApprovalResult.REJECT),
        _sign(SignerKind.PATRON, ApprovalResult.APPROVE),
    ]
    assert is_closable(signed) is False


def test_rejection_rounds_counts_only_rejections() -> None:
    signed = [
        _sign(SignerKind.LEADER, ApprovalResult.REJECT),
        _sign(SignerKind.LEADER),
        _sign(SignerKind.PATRON, ApprovalResult.REJECT),
    ]
    assert rejection_rounds(signed) == 2


def test_three_rounds_is_the_ceiling_that_pulls_the_leader_in() -> None:
    """FR-041: sau vòng thứ ba, lỗi có thể nằm ở **đề bài**, không ở thợ."""
    signed = [_sign(SignerKind.PATRON, ApprovalResult.REJECT) for _ in range(3)]
    assert rejection_rounds(signed) == 3


# ── 3. công tắc không với tới ba quyết định cấp dự án (FR-037) ───────────────


@pytest.mark.parametrize(
    "decision",
    [
        ProjectDecision.PLAN_APPROVAL,
        ProjectDecision.MAJOR_CHANGE,
        ProjectDecision.PHASE_CHANGE,
    ],
)
def test_auto_approval_never_covers_a_project_level_decision(
    decision: ProjectDecision,
) -> None:
    assert decision in PROJECT_DECISIONS_OUTSIDE_AUTO_APPROVAL


def test_the_three_project_decisions_are_exactly_three() -> None:
    """Đóng cứng con số: thêm một quyết định cấp dự án vào diện tự động sẽ làm đỏ ở đây
    chứ không lặng lẽ trôi qua."""
    assert len(PROJECT_DECISIONS_OUTSIDE_AUTO_APPROVAL) == 3
