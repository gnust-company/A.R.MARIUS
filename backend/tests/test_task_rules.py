from __future__ import annotations

import pytest

from armarius.domain.entities.task import (
    ArtifactRequiredError,
    DependencyNotMetError,
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
    task = Task(status=TaskStatus.IN_PROGRESS)
    with pytest.raises(ArtifactRequiredError):
        task.transition_to(TaskStatus.DONE, utcnow(), has_artifact=False)


def test_done_with_artifact_sets_completed_at() -> None:
    task = Task(status=TaskStatus.IN_PROGRESS)
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
