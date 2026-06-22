from __future__ import annotations

import pytest

from armarius.domain.entities.task import (
    ArtifactRequiredError,
    Task,
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
