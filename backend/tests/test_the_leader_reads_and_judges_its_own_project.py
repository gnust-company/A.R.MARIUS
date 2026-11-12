"""The Leader can see its own project, and judges work where the work is (FR-047b, FR-047c).

Measured 2026-11-12 on a real team of three building a small web app. The Leader was woken
*in the project chat* to judge each task handed in, on a run that carried only project
commands: it could not open the task, read what was published, or sign. Asked afterwards which
files were final, it told the patron to paste the list in — about work it had, when mentioned
on the task's own thread, already read and signed.

Two halves, one cause. The call to judge now arrives **on the task**, and the Leader's project
run can **read** the whole board.
"""

from __future__ import annotations

from tests.support.app_db import wakeups_for_project, wakeups_for_task
from tests.support.approvals import task_awaiting_acceptance
from tests.support.planning import client, operating_project


async def test_work_handed_in_wakes_the_leader_on_that_task() -> None:
    async with client() as c:
        p = await operating_project(c, "judge-a@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p)

        on_the_task = await wakeups_for_task(task_id)
        on_the_project = await wakeups_for_project(p.project_id)

    judged = [w for w in on_the_task if w["source"] == "task_in_review"]
    assert len(judged) == 1, on_the_task
    assert judged[0]["marius_id"] == p.leader_id, "the call to judge went to somebody else"
    assert [w for w in on_the_project if "task_in_review" in w["codes"]] == [], (
        "the Leader was also called in the project chat about work it can only judge on the task"
    )


async def test_the_leader_reads_the_whole_board_of_its_project() -> None:
    async with client() as c:
        p = await operating_project(c, "judge-b@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p, title="Kết xuất báo cáo tháng")

        board = await c.get(f"/agent/projects/{p.project_id}/tasks", headers=p.leader_headers)

    assert board.status_code == 200, board.text
    rows = board.json()
    assert [r["id"] for r in rows] == [task_id]
    row = rows[0]
    assert row["status"] == "in_review"
    assert row["assigned_marius_id"] == p.worker_id
    assert row["artifacts"] == ["bao-cao.csv"], row
    assert row["identifier"], "the board gives the Leader no name to open the task by"


async def test_the_leader_opens_one_task_and_reads_what_was_published() -> None:
    async with client() as c:
        p = await operating_project(c, "judge-c@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p)
        said = await c.post(
            f"/v1/tasks/{task_id}/comments", headers=p.headers, json={"body": "Đã kiểm, đạt."}
        )
        assert said.status_code == 201, said.text
        # A report, published the way agents publish them: as a note. On the first real run
        # the Leader could list four of these and open none.
        noted = await c.post(
            f"/agent/tasks/{task_id}/artifact",
            headers=p.worker_headers,
            json={"name": "bao-cao.md", "kind": "note", "content": "Đạt 23/23."},
        )
        assert noted.status_code == 201, noted.text
        board = await c.get(f"/agent/projects/{p.project_id}/tasks", headers=p.leader_headers)
        identifier = board.json()[0]["identifier"]

        by_name = await c.get(
            f"/agent/projects/{p.project_id}/tasks/{identifier.lower()}", headers=p.leader_headers
        )
        by_id = await c.get(
            f"/agent/projects/{p.project_id}/tasks/{task_id}", headers=p.leader_headers
        )

    assert by_name.status_code == 200, by_name.text
    assert by_id.status_code == 200, by_id.text
    opened = by_name.json()
    assert opened["task"]["id"] == task_id == by_id.json()["task"]["id"]
    assert [c_["body"] for c_ in opened["thread"]] == ["Đã kiểm, đạt."]
    published = opened["artifacts"]
    assert [a["name"] for a in published] == ["bao-cao.csv", "bao-cao.md"]
    # The point of opening a task from the chat: the report is read, not merely listed.
    assert published[0]["text"] == "thang,doanh-thu\n7,100", published[0]
    assert published[1]["text"] == "Đạt 23/23.", published[1]


async def test_only_the_leader_reads_the_board_and_only_of_its_own_project() -> None:
    """A worker's run is about its task (FR-049); another project is not there at all."""
    async with client() as c:
        p = await operating_project(c, "judge-d@armarius.dev")
        other = await operating_project(c, "judge-e@armarius.dev")
        task_id = await task_awaiting_acceptance(c, p)
        elsewhere = await task_awaiting_acceptance(c, other)

        as_worker = await c.get(
            f"/agent/projects/{p.project_id}/tasks", headers=p.worker_headers
        )
        worker_opens = await c.get(
            f"/agent/projects/{p.project_id}/tasks/{task_id}", headers=p.worker_headers
        )
        next_door = await c.get(
            f"/agent/projects/{other.project_id}/tasks", headers=p.leader_headers
        )
        # A task that exists, named under a project it does not belong to.
        smuggled = await c.get(
            f"/agent/projects/{p.project_id}/tasks/{elsewhere}", headers=p.leader_headers
        )
        nothing = await c.get(
            f"/agent/projects/{p.project_id}/tasks/NOPE-99", headers=p.leader_headers
        )

    assert as_worker.status_code == 404, as_worker.text
    assert worker_opens.status_code == 404, worker_opens.text
    assert next_door.status_code == 404, next_door.text
    assert smuggled.status_code == 404, smuggled.text
    assert nothing.status_code == 404, nothing.text
