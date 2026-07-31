"""Cổng mô tả, cổng lý do bắt buộc, và khoá mô tả gốc (spec 001 FR-018, FR-029, FR-030).

Ba luật thuần ở tầng miền, không cần cơ sở dữ liệu:

  - **Cổng mô tả** (FR-029): không giao được một đầu việc khi *mô tả chi tiết* còn trống.
    Chặn ở đúng lúc giao, không phải lúc tạo — người chủ được phép phác một ý rồi mới viết
    kỹ, nhưng không được ném một dòng tiêu đề cho thợ rồi bảo nó tự đoán.
  - **Cổng lý do** (FR-030): vào *bị chặn*, vào *huỷ*, hoặc trả lại sửa mà không nói vì sao
    thì bị từ chối. Ba chuyển này đều là tin xấu cho ai đó — tin xấu phải có lý do.
  - **Khoá mô tả gốc** (FR-018): thợ bổ sung ghi chú tiến trình được, sửa yêu cầu gốc thì
    không. Đây là cách một đầu việc không tự trôi khỏi thứ người ta đặt hàng.
"""

from __future__ import annotations

import pytest

from armarius.domain.entities.task import (
    DescriptionLockedError,
    DescriptionRequiredError,
    StatusReasonRequiredError,
    Task,
    TaskStatus,
    assert_assignable,
)
from armarius.shared.clock import utcnow

# ── Cổng mô tả (FR-029) ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("blank", [None, "", "   ", "\n\t "])
def test_a_task_without_a_description_cannot_be_assigned(blank: str | None) -> None:
    task = Task(title="Xuất báo cáo tháng", description=blank, status=TaskStatus.DRAFT)
    with pytest.raises(DescriptionRequiredError):
        assert_assignable(task)


def test_a_task_with_a_description_can_be_assigned() -> None:
    task = Task(
        title="Xuất báo cáo tháng",
        description="Gom số liệu bán hàng tháng 7 rồi kết xuất ra tệp bảng tính.",
        status=TaskStatus.DRAFT,
    )
    assert_assignable(task)  # không ném là đạt


# ── Cổng lý do bắt buộc (FR-030) ─────────────────────────────────────────────────


def test_blocked_demands_a_reason() -> None:
    task = Task(status=TaskStatus.IN_PROGRESS)
    with pytest.raises(StatusReasonRequiredError):
        task.transition_to(TaskStatus.BLOCKED, utcnow())
    assert task.status == TaskStatus.IN_PROGRESS


def test_cancelled_demands_a_reason() -> None:
    task = Task(status=TaskStatus.TODO)
    with pytest.raises(StatusReasonRequiredError):
        task.transition_to(TaskStatus.CANCELLED, utcnow(), reason="  ")
    assert task.status == TaskStatus.TODO


def test_sending_a_task_back_for_rework_demands_a_reason() -> None:
    """*Chờ rà soát → đang làm* là lần trả lại sửa — thợ phải biết sửa cái gì."""
    task = Task(status=TaskStatus.IN_REVIEW)
    with pytest.raises(StatusReasonRequiredError):
        task.transition_to(TaskStatus.IN_PROGRESS, utcnow())
    task.transition_to(TaskStatus.IN_PROGRESS, utcnow(), reason="thiếu phần đối chiếu số")
    assert task.status == TaskStatus.IN_PROGRESS
    assert task.status_reason == "thiếu phần đối chiếu số"


def test_ordinary_forward_moves_need_no_reason() -> None:
    task = Task(status=TaskStatus.TODO)
    task.transition_to(TaskStatus.IN_PROGRESS, utcnow())
    assert task.status == TaskStatus.IN_PROGRESS


def test_a_reason_is_kept_on_the_task_after_a_blocked_move() -> None:
    task = Task(status=TaskStatus.IN_PROGRESS)
    task.transition_to(TaskStatus.BLOCKED, utcnow(), reason="chờ khoá truy cập từ bên thứ ba")
    assert task.status_reason == "chờ khoá truy cập từ bên thứ ba"


# ── Khoá mô tả gốc (FR-018) ──────────────────────────────────────────────────────


def test_a_worker_cannot_rewrite_the_original_requirement() -> None:
    task = Task(description="Gom số liệu bán hàng tháng 7.")
    with pytest.raises(DescriptionLockedError):
        task.set_description("Thôi làm tháng 6 cho dễ.", by_worker=True)
    assert task.description == "Gom số liệu bán hàng tháng 7."


def test_the_side_that_ordered_the_work_may_rewrite_it() -> None:
    task = Task(description="Gom số liệu bán hàng tháng 7.")
    task.set_description("Gom số liệu bán hàng quý 3.", by_worker=False)
    assert task.description == "Gom số liệu bán hàng quý 3."
