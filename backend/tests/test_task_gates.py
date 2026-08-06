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


# ── thành phẩm mất hoặc hỏng lúc chuẩn bị công nhận (FR-069) ────────────────────
#
# A signature is the one artefact in this system that is supposed to mean something. It is
# a claim about a thing that exists — and a row in the artifact table is not that claim: it
# says something *was* published. Buckets get pruned and volumes come back empty, and
# without this check a task closes against a file nobody can open.

import pytest  # noqa: E402

from armarius.application.use_cases.approvals import ApprovalService  # noqa: E402
from armarius.domain.entities.artifact import Artifact, ArtifactKind  # noqa: E402
from armarius.domain.entities.seat_grant import SeatGrant  # noqa: E402
from armarius.domain.entities.task_log import TaskLogKind  # noqa: E402


class VanishedStore:
    """A store where nothing is left. Only `exists` is ever called on this path."""

    async def save_bytes(self, project_id, name, data):  # noqa: ANN001, ARG002
        raise AssertionError("the acceptance path must not write to the store")

    async def exists(self, uri: str) -> bool:  # noqa: ARG002
        return False


class IntactStore:
    async def save_bytes(self, project_id, name, data):  # noqa: ANN001, ARG002
        raise AssertionError("the acceptance path must not write to the store")

    async def exists(self, uri: str) -> bool:  # noqa: ARG002
        return True


async def _task_in_review_with_a_stored_artifact(uow_factory):
    from armarius.application.use_cases.mariuses import MariusService
    from armarius.application.use_cases.tasks import TaskService
    from armarius.application.use_cases.wake_engine import WakeEngine
    from armarius.application.use_cases.workspaces import WorkspaceService
    from armarius.infrastructure.adapters.registry import InMemoryAdapterRegistry
    from armarius.infrastructure.events.in_memory_bus import InMemoryEventBus
    from tests.support.projects import force_phase

    workspaces = WorkspaceService(uow_factory)
    ws = await workspaces.create_workspace("WS")
    project = await workspaces.create_project(ws.id, "P")
    await force_phase(uow_factory, project.id)
    alice = await MariusService(uow_factory).register(
        workspace_id=ws.id, name="Alice", role="Backend", skills=[],
        adapter_type="echo", adapter_config={},
    )
    tasks = TaskService(
        uow_factory,
        WakeEngine(uow_factory, InMemoryAdapterRegistry(), InMemoryEventBus(),
                   run_timeout_seconds=30),
    )
    task = await tasks.create(
        project_id=project.id, title="Việc đã nộp",
        description="Gom số liệu tháng rồi kết xuất ra tệp bảng tính.",
    )
    async with uow_factory() as uow:
        # The seat grant is what says which patron must co-sign (FR-034); without it
        # the happy path cannot route the second signature at all.
        roles = list(await uow.roles.list_by_project(project.id))
        role_key = roles[0].key if roles else "backend"
        await uow.seat_grants.add(
            SeatGrant(
                project_id=project.id,
                role_key=role_key,
                marius_id=alice.id,
                granted_by_user_id="patron-1",
            )
        )
        await uow.artifacts.add(
            Artifact(
                project_id=project.id, task_id=task.id, marius_id=alice.id,
                name="bao-cao.xlsx", kind=ArtifactKind.FILE,
                uri=f"{project.id}/abc123-bao-cao.xlsx",
            )
        )
        stored = await uow.tasks.get(task.id)
        stored.status = TaskStatus.IN_REVIEW
        stored.assigned_marius_id = alice.id
        await uow.tasks.update(stored)
        await uow.commit()
    return project, alice, task


@pytest.mark.asyncio
async def test_a_lost_deliverable_sends_the_task_back_instead_of_closing_it(
    uow_factory,
) -> None:
    _, alice, task = await _task_in_review_with_a_stored_artifact(uow_factory)
    approvals = ApprovalService(uow_factory, artifact_store=VanishedStore())

    returned = await approvals.sign_as_leader(task.id, marius_id=alice.id, approve=True)

    assert returned.status is TaskStatus.IN_PROGRESS, (
        "ký được cho một thành phẩm không còn tồn tại"
    )
    assert "không còn trong kho" in (returned.status_reason or ""), (
        "kéo về mà không ghi lại là đã mất cái gì"
    )
    assert "bao-cao.xlsx" in (returned.next_action or ""), (
        "không nói rõ phải nộp lại cái nào, nên người phụ trách phải đoán"
    )
    async with uow_factory() as uow:
        assert list(await uow.approvals.list_for_task(task.id)) == [], (
            "một chữ ký vẫn được ghi cho thành phẩm đã mất"
        )


@pytest.mark.asyncio
async def test_the_loss_is_written_into_the_task_history(uow_factory) -> None:
    from armarius.application.use_cases.task_log import TaskLogService

    _, alice, task = await _task_in_review_with_a_stored_artifact(uow_factory)
    approvals = ApprovalService(
        uow_factory,
        task_logs=TaskLogService(uow_factory),
        artifact_store=VanishedStore(),
    )

    await approvals.sign_as_leader(task.id, marius_id=alice.id, approve=True)

    async with uow_factory() as uow:
        entries = list(await uow.task_logs.list_by_task(task.id))
    moved = [e for e in entries if e.kind is TaskLogKind.STATUS_CHANGED]
    assert moved and "không còn trong kho" in (moved[-1].reason or ""), (
        "mất thành phẩm mà nhật ký đầu việc không ghi lại vết nào"
    )


@pytest.mark.asyncio
async def test_an_intact_deliverable_signs_normally(uow_factory) -> None:
    """The guard must be invisible when nothing is wrong — a check that gets in the way of
    the happy path is a check somebody removes."""
    _, alice, task = await _task_in_review_with_a_stored_artifact(uow_factory)
    approvals = ApprovalService(uow_factory, artifact_store=IntactStore())

    await approvals.sign_as_leader(task.id, marius_id=alice.id, approve=True)

    async with uow_factory() as uow:
        signatures = list(await uow.approvals.list_for_task(task.id))
    assert len(signatures) == 1


@pytest.mark.asyncio
async def test_a_rejection_still_goes_through_when_the_output_is_missing(
    uow_factory,
) -> None:
    """Turning work down does not depend on the file being there — the reviewer may be
    rejecting it *because* it is missing, and blocking that would leave the task stuck in
    review with no way out."""
    _, alice, task = await _task_in_review_with_a_stored_artifact(uow_factory)
    approvals = ApprovalService(uow_factory, artifact_store=VanishedStore())

    await approvals.sign_as_leader(
        task.id, marius_id=alice.id, approve=False, reason="thiếu phần kết xuất"
    )

    async with uow_factory() as uow:
        assert len(list(await uow.approvals.list_for_task(task.id))) == 1
