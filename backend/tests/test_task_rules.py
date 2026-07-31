from __future__ import annotations

import pytest

from armarius.domain.entities.task import (
    VALID_TRANSITIONS,
    ArtifactRequiredError,
    DependencyNotMetError,
    StalledTaskError,
    StatusReasonRequiredError,
    Task,
    TaskPriority,
    TaskStatus,
    TaskTransitionError,
)
from armarius.shared.clock import utcnow


def test_legal_transition_backlog_to_todo() -> None:
    task = Task(status=TaskStatus.BACKLOG)
    task.transition_to(TaskStatus.TODO, utcnow())
    assert task.status == TaskStatus.TODO


def test_illegal_transition_raises() -> None:
    task = Task(status=TaskStatus.BACKLOG)
    with pytest.raises(TaskTransitionError):
        task.transition_to(TaskStatus.IN_PROGRESS, utcnow())


def test_done_requires_artifact() -> None:
    # Review is now the only door into done (spec 001 FR-024), so the evidence gate is
    # checked on the way *out* of review rather than out of in_progress.
    task = Task(status=TaskStatus.IN_REVIEW)
    with pytest.raises(ArtifactRequiredError):
        task.transition_to(TaskStatus.DONE, utcnow(), has_artifact=False)


def test_done_with_artifact_sets_completed_at() -> None:
    task = Task(status=TaskStatus.IN_REVIEW)
    task.transition_to(TaskStatus.DONE, utcnow(), has_artifact=True)
    assert task.status == TaskStatus.DONE
    assert task.completed_at is not None


def test_review_requires_artifact() -> None:
    task = Task(status=TaskStatus.IN_PROGRESS)
    with pytest.raises(ArtifactRequiredError):
        task.transition_to(TaskStatus.IN_REVIEW, utcnow(), has_artifact=False)
    task.transition_to(TaskStatus.IN_REVIEW, utcnow(), has_artifact=True)
    assert task.status == TaskStatus.IN_REVIEW


# ── draft entry point (commission proposal) ──────────────────────────────────


def test_default_priority_is_medium() -> None:
    assert Task().priority == TaskPriority.MEDIUM


def test_draft_confirms_to_todo() -> None:
    task = Task(status=TaskStatus.DRAFT)
    task.transition_to(TaskStatus.TODO, utcnow())
    assert task.status == TaskStatus.TODO


def test_draft_cannot_jump_to_in_progress() -> None:
    task = Task(status=TaskStatus.DRAFT)
    with pytest.raises(TaskTransitionError):
        task.transition_to(TaskStatus.IN_PROGRESS, utcnow())


# ── dependency-gate (§3.2) ───────────────────────────────────────────────────


def test_todo_blocked_by_unfinished_dependency() -> None:
    task = Task(status=TaskStatus.BACKLOG)
    with pytest.raises(DependencyNotMetError):
        task.transition_to(TaskStatus.TODO, utcnow(), deps_satisfied=False)
    # still parked in backlog
    assert task.status == TaskStatus.BACKLOG


def test_in_progress_blocked_by_unfinished_dependency() -> None:
    task = Task(status=TaskStatus.TODO)
    with pytest.raises(DependencyNotMetError):
        task.transition_to(TaskStatus.IN_PROGRESS, utcnow(), deps_satisfied=False)


def test_todo_allowed_once_dependencies_done() -> None:
    task = Task(status=TaskStatus.BACKLOG)
    task.transition_to(TaskStatus.TODO, utcnow(), deps_satisfied=True)
    assert task.status == TaskStatus.TODO


def test_dependency_gate_does_not_apply_to_review() -> None:
    # review/done are gated by the artifact rule, not the dependency rule
    task = Task(status=TaskStatus.IN_PROGRESS)
    task.transition_to(TaskStatus.IN_REVIEW, utcnow(), has_artifact=True, deps_satisfied=False)
    assert task.status == TaskStatus.IN_REVIEW


# ── FR-003: no real task before the plan is approved (spec 001) ───────────────────
# Pure-rule half of the gate. The HTTP half lives in test_plan_api.py; this pins the
# law itself so a later refactor cannot quietly widen which phases accept work.


def test_only_operating_and_maintaining_accept_real_tasks() -> None:
    from armarius.domain.entities.project import ProjectStatus
    from armarius.domain.services.project_rules import accepts_real_tasks

    accepting = {p for p in ProjectStatus if accepts_real_tasks(p)}
    assert accepting == {ProjectStatus.OPERATING, ProjectStatus.MAINTAINING}


# ── Đợt 2 (spec 001 FR-022 → FR-024, FR-058): bảng chuyển trạng thái đã siết ──────
# Bốn thay đổi so với bảng cũ, tất cả đều là siết:
#   - *đang làm → xong*  : bỏ  (thợ không tự tuyên xong, phải qua rà soát)
#   - *xong → đang làm*  : ra khỏi đường thường ngày (chỉ qua thao tác mở lại có ghi vết)
#   - *huỷ → tồn kho*    : ra khỏi đường thường ngày (như trên)
#   - *nháp → tồn kho*   : thêm (cất để dành một đề xuất)
# Cộng một luật mới: đầu việc đang mang cờ đình trệ thì mọi đường vào *xong* đều đóng.


def test_in_progress_can_no_longer_jump_to_done() -> None:
    task = Task(status=TaskStatus.IN_PROGRESS)
    with pytest.raises(TaskTransitionError):
        task.transition_to(TaskStatus.DONE, utcnow(), has_artifact=True)
    assert task.status == TaskStatus.IN_PROGRESS


def test_review_is_the_only_door_into_done() -> None:
    doors = {s for s, targets in VALID_TRANSITIONS.items() if TaskStatus.DONE in targets}
    assert doors == {TaskStatus.IN_REVIEW}


def test_done_has_no_everyday_route_out() -> None:
    task = Task(status=TaskStatus.DONE)
    for target in TaskStatus:
        if target is TaskStatus.DONE:
            continue
        with pytest.raises(TaskTransitionError):
            task.transition_to(target, utcnow(), has_artifact=True, reason="thử")


def test_cancelled_has_no_everyday_route_out() -> None:
    task = Task(status=TaskStatus.CANCELLED)
    for target in TaskStatus:
        if target is TaskStatus.CANCELLED:
            continue
        with pytest.raises(TaskTransitionError):
            task.transition_to(target, utcnow(), has_artifact=True, reason="thử")


def test_draft_can_be_shelved_to_backlog() -> None:
    task = Task(status=TaskStatus.DRAFT)
    task.transition_to(TaskStatus.BACKLOG, utcnow())
    assert task.status == TaskStatus.BACKLOG


# ── Mở lại: đường duy nhất ra khỏi một trạng thái đóng (FR-022) ───────────────────


def test_reopen_moves_done_back_to_in_progress_with_a_reason() -> None:
    task = Task(status=TaskStatus.DONE, completed_at=utcnow())
    task.reopen(utcnow(), reason="khách báo còn thiếu phần xuất báo cáo")
    assert task.status == TaskStatus.IN_PROGRESS
    assert task.status_reason == "khách báo còn thiếu phần xuất báo cáo"
    assert task.completed_at is None


def test_reopen_moves_cancelled_back_to_backlog() -> None:
    task = Task(status=TaskStatus.CANCELLED)
    task.reopen(utcnow(), reason="dùng lại đề xuất này cho đợt sau")
    assert task.status == TaskStatus.BACKLOG


def test_reopen_demands_a_reason() -> None:
    task = Task(status=TaskStatus.DONE)
    with pytest.raises(StatusReasonRequiredError):
        task.reopen(utcnow(), reason="   ")
    assert task.status == TaskStatus.DONE


def test_reopen_refuses_a_task_that_is_not_closed() -> None:
    task = Task(status=TaskStatus.IN_PROGRESS)
    with pytest.raises(TaskTransitionError):
        task.reopen(utcnow(), reason="không có gì để mở lại")


# ── FR-058: cờ đình trệ đóng cứng mọi đường vào *xong* ───────────────────────────
# Đình trệ không phải một trạng thái nghiệp vụ — nó là báo động rằng hệ thống vừa đánh
# rơi một đầu việc. Một đầu việc bị đánh rơi thì không được đóng bằng bất kỳ lối nào.


def test_a_stalled_task_can_never_reach_done() -> None:
    task = Task(status=TaskStatus.IN_REVIEW, stalled=True, stalled_reason="mất động cơ đẩy")
    with pytest.raises(StalledTaskError):
        task.transition_to(TaskStatus.DONE, utcnow(), has_artifact=True)
    assert task.status == TaskStatus.IN_REVIEW


def test_a_stalled_task_may_still_move_sideways_to_get_unstuck() -> None:
    task = Task(status=TaskStatus.IN_REVIEW, stalled=True, stalled_reason="mất động cơ đẩy")
    task.transition_to(TaskStatus.IN_PROGRESS, utcnow(), reason="soi lại vì đình trệ")
    assert task.status == TaskStatus.IN_PROGRESS
