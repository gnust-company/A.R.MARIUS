"""Tiêu chí công nhận thay chuỗi định nghĩa hoàn thành tự do (spec 001 FR-019).

*Định nghĩa hoàn thành* cũ là một ô chữ tự do — không ai chấm được nó, nên trên thực tế nó
không chặn gì cả. Nay nó là một **danh sách khẳng định đúng/sai**, mỗi dòng có kết quả chấm
và chỗ trỏ tới thành phẩm nào chứng minh.

Hai luật đi kèm: bộ tiêu chí phải đặt **trước khi** thợ bắt tay, và sửa nó sau đó là một
thay đổi lớn (FR-075) nên phải treo chờ người chủ chứ không sửa thẳng.
"""

from __future__ import annotations

import pytest

from armarius.domain.entities.checklist_item import (
    AcceptanceResult,
    ChecklistItem,
    CriteriaLockedError,
    assert_criteria_editable,
)
from armarius.domain.entities.task import Task, TaskStatus
from tests.support.planning import client, operating_project

# ── thực thể: một tiêu chí là một khẳng định chấm được ────────────────────────────


def test_a_fresh_criterion_is_unrated() -> None:
    item = ChecklistItem(text="Tệp kết xuất mở được bằng phần mềm bảng tính")
    assert item.result is AcceptanceResult.UNRATED
    assert item.evidence_artifact_id is None


def test_a_criterion_can_be_marked_passed_with_evidence() -> None:
    from uuid import uuid4

    artifact_id = uuid4()
    item = ChecklistItem(text="Có tệp kết xuất")
    item.rate(AcceptanceResult.PASSED, evidence_artifact_id=artifact_id)
    assert item.result is AcceptanceResult.PASSED
    assert item.evidence_artifact_id == artifact_id


def test_the_legacy_done_flag_follows_the_rating() -> None:
    """Ô tích cũ vẫn còn để giao diện cũ không vỡ, nhưng nó chỉ là bóng của kết quả chấm."""
    item = ChecklistItem(text="Có tệp kết xuất")
    item.rate(AcceptanceResult.PASSED)
    assert item.done is True
    item.rate(AcceptanceResult.FAILED)
    assert item.done is False


# ── luật: đặt trước khi thợ bắt tay ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "status", [TaskStatus.DRAFT, TaskStatus.BACKLOG, TaskStatus.TODO]
)
def test_criteria_may_be_written_before_work_starts(status: TaskStatus) -> None:
    assert_criteria_editable(Task(status=status))  # không ném là đạt


@pytest.mark.parametrize(
    "status",
    [TaskStatus.IN_PROGRESS, TaskStatus.IN_REVIEW, TaskStatus.BLOCKED, TaskStatus.DONE],
)
def test_criteria_freeze_once_the_worker_has_started(status: TaskStatus) -> None:
    with pytest.raises(CriteriaLockedError):
        assert_criteria_editable(Task(status=status))


# ── mặt giao tiếp ─────────────────────────────────────────────────────────────────


async def test_criteria_round_trip_over_http() -> None:
    async with client() as c:
        p = await operating_project(c, "crit-a@armarius.dev")
        created = await c.post(
            f"/v1/projects/{p.project_id}/tasks",
            headers=p.headers,
            json={
                "title": "Xuất báo cáo tháng",
                "description": "Kết xuất số liệu tháng 7 ra tệp bảng tính.",
            },
        )
        task_id = created.json()["id"]

        put = await c.put(
            f"/v1/tasks/{task_id}/criteria",
            headers=p.headers,
            json={
                "items": [
                    {"text": "Tệp mở được bằng phần mềm bảng tính"},
                    {"text": "Tổng doanh thu khớp với sổ cái"},
                ]
            },
        )
        assert put.status_code == 200, put.text
        assert [i["text"] for i in put.json()] == [
            "Tệp mở được bằng phần mềm bảng tính",
            "Tổng doanh thu khớp với sổ cái",
        ]
        assert {i["result"] for i in put.json()} == {"unrated"}

        got = await c.get(f"/v1/tasks/{task_id}/criteria", headers=p.headers)
    assert got.status_code == 200
    assert len(got.json()) == 2


async def test_criteria_cannot_be_rewritten_once_the_work_is_under_way() -> None:
    async with client() as c:
        p = await operating_project(c, "crit-b@armarius.dev")
        created = await c.post(
            f"/v1/projects/{p.project_id}/tasks",
            headers=p.headers,
            json={
                "title": "Xuất báo cáo tháng",
                "description": "Kết xuất số liệu tháng 7 ra tệp bảng tính.",
            },
        )
        task_id = created.json()["id"]
        await c.put(
            f"/v1/tasks/{task_id}/criteria",
            headers=p.headers,
            json={"items": [{"text": "Tệp mở được"}]},
        )
        await c.post(
            f"/v1/tasks/{task_id}/assign",
            headers=p.headers,
            json={"marius_id": p.worker_id},
        )
        started = await c.post(
            f"/v1/tasks/{task_id}/status", headers=p.headers, json={"status": "in_progress"}
        )
        assert started.status_code == 200, started.text

        r = await c.put(
            f"/v1/tasks/{task_id}/criteria",
            headers=p.headers,
            json={"items": [{"text": "Đổi luật giữa chừng"}]},
        )
    assert r.status_code == 409, r.text


async def test_the_task_read_route_carries_the_four_fields_the_board_draws() -> None:
    """Hạng mục kế hoạch, động cơ đẩy, cờ đình trệ, chữ ký — thiếu là bảng dự án trống."""
    async with client() as c:
        p = await operating_project(c, "crit-c@armarius.dev")
        created = await c.post(
            f"/v1/projects/{p.project_id}/tasks",
            headers=p.headers,
            json={"title": "Việc mẫu", "description": "Có mô tả đàng hoàng."},
        )
        task_id = created.json()["id"]
        got = await c.get(f"/v1/tasks/{task_id}", headers=p.headers)
    assert got.status_code == 200, got.text
    body = got.json()
    for field in ("plan_item_id", "drive", "stalled", "stalled_reason", "signatures"):
        assert field in body, f"thiếu trường '{field}' ở lối đọc đầu việc"
