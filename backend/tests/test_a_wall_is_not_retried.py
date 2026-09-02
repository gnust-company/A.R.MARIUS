"""Lỗi cần người xử thì không được thử lại — không một lần nào (FR-032, FR-007c, FR-014f).

Every automatic retry spends an agent turn, a slot on somebody's machine and the minutes
between attempts. Against a wall it buys nothing at all, and it buys nothing *slowly*: the
run ends the same way every time, and the person who could have cleared it in a minute is
told half an hour later by a safety net instead of at the moment the machine already knew.

Two budgets are guarded here and they belong to different loops. The **continuation
budget** decides whether a run that ended badly is started again; the **Level-1 budget** of
the recovery ladder decides whether the assignee is called back. Both assume the same thing
about a retry — that it might land — and that assumption is exactly what a wall falsifies,
so both are checked, and each is checked against a control that proves the verdict is what
changed the answer.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update

from armarius.domain.entities.run import RunStatus
from armarius.domain.entities.task import TaskStatus
from armarius.domain.services.failure_kind import (
    CREDENTIAL_REJECTED,
    MISCONFIGURED,
    NEEDS_A_PERSON,
    QUOTA_EXHAUSTED,
    english,
    needs_a_person,
)
from armarius.domain.services.wake_policy import decide_self_wake
from armarius.infrastructure.daemon.models import WorkplaceModel
from armarius.infrastructure.database.engine import get_sessionmaker
from armarius.infrastructure.database.models import RunModel, TaskModel
from armarius.main import app
from tests.support.agents import invite_agent
from tests.support.machines import auth, link_machine
from tests.support.work import a_project, a_task, shelve

pytestmark = pytest.mark.anyio


# ── 1. phân loại thuần: danh sách đóng, và mặc định rẻ hơn ─────────────────────


def test_the_three_walls_are_named_and_nothing_else_is() -> None:
    """The list is closed on purpose — see the module it lives in for why."""
    assert NEEDS_A_PERSON == {QUOTA_EXHAUSTED, CREDENTIAL_REJECTED, MISCONFIGURED}
    for wall in NEEDS_A_PERSON:
        assert needs_a_person(wall), f"{wall} nằm trong danh sách mà vẫn bị coi là lỗi tạm"


def test_an_ending_nobody_has_classified_is_still_worth_trying_again() -> None:
    """The cheaper of the two mistakes.

    Guess *transient* wrongly and the budget bounds the loss to a few attempts before a
    person is asked anyway. Guess *needs a person* wrongly and every unfamiliar hiccup —
    a new CLI's new word for a timeout — becomes an interruption, and an alarm that cries
    wolf is an alarm that gets muted.
    """
    assert not needs_a_person("")
    assert not needs_a_person(None)
    assert not needs_a_person("network_wobbled")


def test_an_unknown_ending_still_reads_as_words() -> None:
    """A verdict written by a newer machine must not take an older reader down with it."""
    assert english("something_new") == "something_new"
    assert english("") == ""
    assert english(QUOTA_EXHAUSTED) and english(QUOTA_EXHAUSTED) != QUOTA_EXHAUSTED


# ── 2. ngân sách gọi lại lượt chạy ─────────────────────────────────────────────


def _decide(failure: str, *, attempt: int = 0):
    return decide_self_wake(
        task_status=TaskStatus.IN_PROGRESS,
        run_status=RunStatus.FAILED,
        has_next_action=False,
        has_block_reason=False,
        continuation_attempt=attempt,
        max_attempts=3,
        failure=failure,
    )


def test_a_wall_spends_not_one_continuation_attempt() -> None:
    """Zero, not *fewer*. A budget spent against a wall is a delay dressed as a retry: the
    ending is identical each time, so the only thing the three attempts buy is the half
    hour before the person who can fix it is finally told."""
    decision = _decide(QUOTA_EXHAUSTED)
    assert decision.should_wake is False, "đâm vào tường mà vẫn gọi dậy lần nữa"
    assert decision.escalate_to_human is True
    assert decision.code == QUOTA_EXHAUSTED, "leo lên người mà không nói leo vì cái gì"


def test_the_very_same_ending_without_a_verdict_is_retried() -> None:
    """The control. Without it the test above would also pass on a policy that had simply
    stopped retrying failed runs altogether."""
    decision = _decide("", attempt=0)
    assert decision.should_wake is True, "lỗi tạm mà cũng không thử lại nữa"
    assert decision.escalate_to_human is False


def test_a_wall_reads_the_same_on_the_last_attempt_as_on_the_first() -> None:
    """Checked ahead of the budget, not inside it — so it does not merely *look* right on a
    fresh run and quietly fall back to the budget on a task that already retried once."""
    for attempt in (0, 1, 2, 3):
        decision = _decide(CREDENTIAL_REJECTED, attempt=attempt)
        assert decision.should_wake is False and decision.escalate_to_human is True


# ── 3. qua cửa thật: chỗ làm đóng, và không ai bị gọi dậy lại ──────────────────


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _in_progress(task_id: UUID) -> None:
    async with get_sessionmaker()() as session:
        await session.execute(
            update(TaskModel)
            .where(TaskModel.id == task_id)
            .values(status=TaskStatus.IN_PROGRESS.value)
        )
        await session.commit()


async def _runs_on(task_id: UUID) -> int:
    async with get_sessionmaker()() as session:
        return (
            await session.execute(
                select(func.count()).select_from(RunModel).where(RunModel.task_id == task_id)
            )
        ).scalar_one()


async def _workplace(workplace_id: str) -> WorkplaceModel:
    async with get_sessionmaker()() as session:
        row = await session.get(WorkplaceModel, UUID(workplace_id))
        assert row is not None
        return row


async def _take_and_end(
    c: AsyncClient, machine, run_id: UUID, *, failure: str
) -> None:
    """One run, taken by the machine that was offered it and reported over — as a daemon
    does it. Going through the door rather than calling the service is the point: what is
    being proved is that a verdict a machine sends actually reaches the policy."""
    claimed = await c.post(
        "/daemon/runs/claim",
        json={"workplace_ids": [machine.workplace_id], "max": 1},
        headers=auth(machine.token),
    )
    assert claimed.status_code == 200, claimed.text
    assert [r["run_id"] for r in claimed.json()["runs"]] == [str(run_id)]
    started = await c.post(
        f"/daemon/runs/{run_id}/start", json={}, headers=auth(machine.token)
    )
    assert started.status_code == 200, started.text
    ended = await c.post(
        f"/daemon/runs/{run_id}/finish",
        json={"status": "failed", "error": "the CLI gave up", "failure": failure},
        headers=auth(machine.token),
    )
    assert ended.status_code == 200, ended.text


async def _two_agents_on_one_machine(c: AsyncClient, email: str):
    """One machine, one workplace, two agents living on it — which is the shape FR-007c is
    about: a quota belongs to the login the workplace was set up with, not to an agent."""
    machine = await link_machine(c, email)
    alice = await invite_agent(
        c, machine.workspace_id, machine.headers,
        name="Alice", workplace_id=machine.workplace_id,
    )
    bob = await invite_agent(
        c, machine.workspace_id, machine.headers,
        name="Bob", workplace_id=machine.workplace_id,
    )
    return machine, alice["id"], bob["id"]


async def _offline_reasons(c: AsyncClient, machine) -> dict[str, str | None]:
    listed = await c.get(
        f"/v1/workspaces/{machine.workspace_id}/mariuses", headers=machine.headers
    )
    assert listed.status_code == 200, listed.text
    return {m["name"]: m.get("offline_reason") for m in listed.json()}


async def test_a_run_that_runs_out_of_quota_closes_the_workplace_for_everyone_on_it() -> (
    None
):
    """FR-007c — the quota belongs to the workplace, so it runs out for everyone at once.

    Bob never ran anything. He is taken offline by Alice's ending because they share a
    login, and the alternative is the system sending him to the same wall a second time
    and calling it a new incident.
    """
    async with _client() as c:
        machine, alice, bob = await _two_agents_on_one_machine(c, "quota@t.dev")
        project = await a_project(machine.workspace_id)
        task = await a_task(project, assigned_to=alice)
        await _in_progress(task)
        run_id = await shelve(marius_id=alice, task_id=task)

        await _take_and_end(c, machine, run_id, failure=QUOTA_EXHAUSTED)

        place = await _workplace(machine.workplace_id)
        assert place.ready is False, "hết hạn mức mà chỗ làm vẫn mở cho lượt sau đâm vào"
        assert place.not_ready_reason == QUOTA_EXHAUSTED
        reasons = await _offline_reasons(c, machine)
        assert reasons["Alice"] == QUOTA_EXHAUSTED
        assert reasons["Bob"] == QUOTA_EXHAUSTED, (
            "chung một đăng nhập mà chỉ một người bị tuyên ngoại tuyến"
        )


async def test_a_run_that_runs_out_of_quota_is_never_started_again() -> None:
    """The whole point, measured where it costs: no second run row on that task."""
    async with _client() as c:
        machine, alice, _ = await _two_agents_on_one_machine(c, "quota-once@t.dev")
        project = await a_project(machine.workspace_id)
        task = await a_task(project, assigned_to=alice)
        await _in_progress(task)
        run_id = await shelve(marius_id=alice, task_id=task)

        await _take_and_end(c, machine, run_id, failure=QUOTA_EXHAUSTED)

        assert await _runs_on(task) == 1, "đâm vào tường xong lại mở thêm một lượt chạy nữa"


async def test_the_same_failure_with_no_verdict_is_tried_again() -> None:
    """The control for the door, and it is what makes the test above mean anything: the
    machine reporting *why* is the only difference between the two."""
    async with _client() as c:
        machine, alice, _ = await _two_agents_on_one_machine(c, "ordinary@t.dev")
        project = await a_project(machine.workspace_id)
        task = await a_task(project, assigned_to=alice)
        await _in_progress(task)
        run_id = await shelve(marius_id=alice, task_id=task)

        await _take_and_end(c, machine, run_id, failure="")

        assert await _runs_on(task) > 1, "lỗi tạm mà lượt chạy không được thử lại"
        place = await _workplace(machine.workplace_id)
        assert place.ready is True, "một lượt chạy hỏng tầm thường mà đóng cả chỗ làm"


async def test_a_verdict_this_build_does_not_know_changes_nothing() -> None:
    """A machine on a newer build must lose a refinement, never have its finish rejected —
    a rejected finish is a run the server never learns is over."""
    async with _client() as c:
        machine, alice, _ = await _two_agents_on_one_machine(c, "newer@t.dev")
        project = await a_project(machine.workspace_id)
        task = await a_task(project, assigned_to=alice)
        await _in_progress(task)
        run_id = await shelve(marius_id=alice, task_id=task)

        await _take_and_end(c, machine, run_id, failure="something_invented_later")

        assert await _runs_on(task) > 1
        assert (await _workplace(machine.workplace_id)).ready is True


async def test_a_run_that_ends_well_is_not_read_as_a_wall() -> None:
    """`failure` travels beside `status`, so a machine that fills it in on a run that
    finished cleanly must not be able to close a workplace with it."""
    async with _client() as c:
        machine, alice, _ = await _two_agents_on_one_machine(c, "clean@t.dev")
        project = await a_project(machine.workspace_id)
        task = await a_task(project, assigned_to=alice)
        run_id = await shelve(marius_id=alice, task_id=task)
        claimed = await c.post(
            "/daemon/runs/claim",
            json={"workplace_ids": [machine.workplace_id], "max": 1},
            headers=auth(machine.token),
        )
        assert claimed.status_code == 200
        ended = await c.post(
            f"/daemon/runs/{run_id}/finish",
            json={"status": "completed"},
            headers=auth(machine.token),
        )
        assert ended.status_code == 200, ended.text
        assert (await _workplace(machine.workplace_id)).ready is True

