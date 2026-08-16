"""Lý do gọi dậy là dữ liệu, không phải một câu viết sẵn (Hiến pháp VII, T193).

Một lệnh gọi dậy có hai người đọc không đọc cùng thứ tiếng: agent nhận gói tin tiếng Anh,
người chủ đọc đúng dòng đó trên màn hình bằng thứ tiếng họ chọn. Câu viết sẵn lúc gọi chỉ
phục vụ được một trong hai.
"""

from __future__ import annotations

import unicodedata

from armarius.domain.services.wake_reason import (
    ENGLISH,
    WakeReason,
    from_payload,
    merge,
    reason,
    render_en,
    to_payload,
)


def test_a_cause_fills_its_own_blanks() -> None:
    said = reason("dependency_cleared", blocker="TOT-1").render_en()
    assert "TOT-1" in said
    assert "ready to start" in said


def test_a_missing_parameter_still_wakes_somebody() -> None:
    """Một tham số thiếu không được phép nuốt cả lệnh gọi.

    Gọi dậy kèm một danh từ mơ hồ vẫn tới được người cần tới; ném lỗi ở đây thì lệnh gọi
    biến mất, và đầu việc đứng im tới khi lưới an toàn quét qua.
    """
    said = reason("dependency_cleared").render_en()
    assert said and "{" not in said


def test_a_code_nobody_worded_falls_back_to_itself() -> None:
    assert WakeReason(code="chua_ai_dat_ten").render_en() == "chua_ai_dat_ten"


def test_the_agents_copy_is_english_only() -> None:
    """Hiến pháp VII, đo được: bảng chữ gửi cho agent không được lẫn tiếng Việt.

    Đây đúng là lỗi T193 sinh ra — mấy đợt trước viết câu lý do bằng tiếng Việt rồi nhét
    vào giữa một gói tin tiếng Anh. Dấu tiếng Việt là thứ nhận ra được bằng máy, nên luật
    ấy có thước đo chứ không chỉ là lời dặn.
    """
    for code, template in ENGLISH.items():
        stripped = unicodedata.normalize("NFKD", template)
        marked = [c for c in stripped if unicodedata.combining(c)]
        assert not marked and "đ" not in template.lower(), code


def test_two_causes_of_the_same_kind_about_different_things_both_survive() -> None:
    """Hai vướng khác nhau được gỡ là hai chuyện người thợ cần biết."""
    causes = merge([], reason("dependency_cleared", blocker="A-1"))
    causes = merge(causes, reason("dependency_cleared", blocker="A-2"))
    assert [c.params["blocker"] for c in causes] == ["A-1", "A-2"]


def test_the_same_cause_twice_is_noise() -> None:
    causes = merge([], reason("mentioned"))
    causes = merge(causes, reason("mentioned"))
    assert len(causes) == 1


def test_a_merged_wake_names_every_cause() -> None:
    said = render_en([reason("mentioned"), reason("new_comment")])
    assert "mentioned" in said and "comment" in said
    assert said.count("•") == 2, "gộp hai cớ mà đọc như một câu thì mất một cớ"


def test_one_cause_reads_like_a_sentence_not_a_list() -> None:
    assert "•" not in render_en([reason("assigned")])


def test_a_row_written_before_the_codes_existed_reads_as_no_causes() -> None:
    """Dòng cũ chỉ có một câu và không có mã. Đọc ra rỗng là đúng — màn hình khi đó
    quay về hiện đúng câu mà dòng ấy có."""
    assert from_payload(None) == []
    assert from_payload("một câu cũ") == []
    assert from_payload([{"params": {}}]) == []


def test_a_cause_survives_the_round_trip_through_storage() -> None:
    original = [reason("output_rejected", note="thiếu phần đo đạc")]
    assert from_payload(to_payload(original)) == original
