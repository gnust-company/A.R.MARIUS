"""The four things a board card draws besides its status (T177, FR-080a, Hiến pháp IV).

T175 fixed a card *appearing* in silence. Auditing the rest of the card turned up four more
values that change with nobody told: the criteria tally, the comment count, the artifact
clip, and the blocker count.

Three of them turned out to be a step worse than "changes in silence". The card reads them
off ``task.comments`` / ``task.artifacts`` / ``task.checklist``, and the board only ever
loaded task rows — those arrays were filled by the single-task screen and nothing else. So
on the board they were empty for every card, always, reload or no reload. An event alone
would have fixed nothing: there was no loaded value for it to refresh. Hence two halves
here — a route that carries the counts, and an event for each way they change.

Driven end to end through real HTTP, a real bus and the real stream, because that is the
distance the failure covered: every layer was individually correct and the badge still
never appeared.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.infrastructure.adapters.echo import EchoAdapter
from armarius.infrastructure.database.engine import init_db
from armarius.main import app
from armarius.presentation.container import build_container
from tests.support.projects import force_operating


@pytest.fixture(autouse=True)
async def _bootstrap():
    await init_db()
    container = build_container()
    container.registry.register(EchoAdapter(step_delay=0.0))
    app.state.container = container
    yield


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _patron(c: AsyncClient, email: str) -> tuple[dict, str]:
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    assert r.status_code == 201, r.text
    h = {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}
    ws = await c.get("/v1/workspaces", headers=h)
    return h, ws.json()[0]["id"]


async def _project(c: AsyncClient, h: dict, ws_id: str) -> str:
    r = await c.post(
        f"/v1/workspaces/{ws_id}/projects",
        headers=h,
        json={
            "name": "Bảng đang mở",
            "objective": "Có người đang nhìn nó",
            "leader": {"description": "lead", "marius_id": None},
        },
    )
    assert r.status_code == 201, r.text
    project_id = r.json()["id"]
    await force_operating(project_id)
    return project_id


async def _task(c: AsyncClient, h: dict, project_id: str, title: str) -> str:
    r = await c.post(
        f"/v1/projects/{project_id}/tasks",
        headers=h,
        json={"title": title, "description": "Việc để đo bảng"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _frames(body: str) -> list[tuple[str, dict]]:
    """Parse an SSE catch-up response into (event type, data) pairs.

    Normalize the line endings first. SSE frames are separated by a blank line, and this
    server writes CRLF — so splitting on ``\\n\\n`` finds no separator at all, folds the
    whole response into one block, and the loop below then reports only the *last* event
    in it. A parser that silently returns one frame for any number of events reads like a
    channel that published once, which is the exact failure these tests exist to catch.
    """
    out: list[tuple[str, dict]] = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        kind, data = None, None
        for line in block.splitlines():
            if line.startswith("event:"):
                kind = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data = json.loads(line.removeprefix("data:").strip())
        if kind is not None:
            out.append((kind, data or {}))
    return out


async def _channel(c: AsyncClient, h: dict, project_id: str) -> list[tuple[str, dict]]:
    r = await c.get(f"/v1/projects/{project_id}/events?live=0", headers=h)
    assert r.status_code == 200, r.text
    return _frames(r.text)


async def _counts(c: AsyncClient, h: dict, project_id: str, task_id: str) -> dict[str, Any]:
    """What the board would draw on one card. A task with nothing to report is left out of
    the list, so absent reads as all-zero — the same card, one row cheaper."""
    r = await c.get(f"/v1/projects/{project_id}/task-counts", headers=h)
    assert r.status_code == 200, r.text
    for row in r.json():
        if row["task_id"] == task_id:
            return row
    return {"comments": 0, "artifacts": 0, "criteria_total": 0, "criteria_passed": 0}


async def test_the_board_can_read_every_count_its_card_draws():
    """The half an event cannot fix: the board had no route carrying these at all."""
    async with await _client() as c:
        h, ws_id = await _patron(c, "counts-a@armarius.dev")
        project_id = await _project(c, h, ws_id)
        task_id = await _task(c, h, project_id, "Việc có đủ thứ treo trên thẻ")

        blank = await _counts(c, h, project_id, task_id)
        assert (blank["comments"], blank["artifacts"], blank["criteria_total"]) == (0, 0, 0)

        await c.put(
            f"/v1/tasks/{task_id}/criteria",
            headers=h,
            json={"items": [{"text": t} for t in ("Chạy được", "Có bài kiểm", "Có tài liệu")]},
        )
        await c.post(
            f"/v1/tasks/{task_id}/comments",
            headers=h,
            json={"body": "Việc này cần làm sớm.", "author_kind": "human"},
        )
        await c.post(
            f"/v1/tasks/{task_id}/artifacts",
            headers=h,
            json={
                "name": "ket-qua.txt",
                "kind": "file",
                "content_b64": base64.b64encode(b"xong").decode(),
            },
        )

        row = await _counts(c, h, project_id, task_id)
        assert row["criteria_total"] == 3, row
        assert row["comments"] == 1, row
        assert row["artifacts"] == 1, row
        # Nothing scores a criterion anywhere in the service yet, so this is 0 by fact and
        # not by accident — asserted so the day something does score one, the board's
        # "passed/total" is known to carry it.
        assert row["criteria_passed"] == 0, row


async def test_counts_are_reported_per_task_not_per_project():
    """One busy card must not put its numbers on the quiet card beside it."""
    async with await _client() as c:
        h, ws_id = await _patron(c, "counts-b@armarius.dev")
        project_id = await _project(c, h, ws_id)
        busy = await _task(c, h, project_id, "Thẻ đông")
        quiet = await _task(c, h, project_id, "Thẻ vắng")

        for i in range(3):
            await c.post(
                f"/v1/tasks/{busy}/comments",
                headers=h,
                json={"body": f"lời bình {i}", "author_kind": "human"},
            )

        assert (await _counts(c, h, project_id, busy))["comments"] == 3
        assert (await _counts(c, h, project_id, quiet))["comments"] == 0


async def test_each_of_the_four_changes_puts_something_on_the_project_channel():
    """One case per way a card's numbers move. Written as four separate assertions rather
    than one sweep at the end: knowing *which* of the four went quiet is the whole value —
    they live in three different services, and a single failed count says none of that."""
    async with await _client() as c:
        h, ws_id = await _patron(c, "counts-c@armarius.dev")
        project_id = await _project(c, h, ws_id)
        task_id = await _task(c, h, project_id, "Việc được sửa từ ngoài")
        blocker_id = await _task(c, h, project_id, "Việc chặn")

        async def emitted_by(action) -> list[str]:
            before = len(await _channel(c, h, project_id))
            await action()
            fresh = (await _channel(c, h, project_id))[before:]
            return [kind for kind, _ in fresh]

        criteria = await emitted_by(
            lambda: c.put(
                f"/v1/tasks/{task_id}/criteria",
                headers=h,
                json={"items": [{"text": "Một tiêu chí"}]},
            )
        )
        assert "task.checklist_changed" in criteria, (
            f"đặt bộ tiêu chí chỉ bắn {criteria} — thẻ trên bảng vẽ 'đạt/tổng' từ đó"
        )

        comment = await emitted_by(
            lambda: c.post(
                f"/v1/tasks/{task_id}/comments",
                headers=h,
                json={"body": "một lời bình", "author_kind": "human"},
            )
        )
        assert "task.comment_added" in comment, f"thêm lời bình chỉ bắn {comment}"

        artifact = await emitted_by(
            lambda: c.post(
                f"/v1/tasks/{task_id}/artifacts",
                headers=h,
                json={
                    "name": "a.txt",
                    "kind": "file",
                    "content_b64": base64.b64encode(b"a").decode(),
                },
            )
        )
        assert "task.artifact_added" in artifact, f"nộp thành phẩm chỉ bắn {artifact}"

        added = await emitted_by(
            lambda: c.post(
                f"/v1/tasks/{task_id}/dependencies",
                headers=h,
                json={"blocks_task_id": blocker_id},
            )
        )
        assert "task.dependencies_changed" in added, f"thêm ràng buộc chỉ bắn {added}"

        removed = await emitted_by(
            lambda: c.delete(
                f"/v1/tasks/{task_id}/dependencies/{blocker_id}", headers=h
            )
        )
        assert "task.dependencies_changed" in removed, (
            f"gỡ ràng buộc chỉ bắn {removed} — ổ khoá trên thẻ phải biến mất theo"
        )


async def test_the_new_events_carry_no_task_content():
    """Contract `push-events` principle 4. A comment body or an artifact name on the
    channel would be a second way to read the row with no workspace guard in front of it."""
    async with await _client() as c:
        h, ws_id = await _patron(c, "counts-d@armarius.dev")
        project_id = await _project(c, h, ws_id)
        task_id = await _task(c, h, project_id, "Việc mang bí mật")

        secret = "Bí mật thương mại không được lên dây"
        await c.put(
            f"/v1/tasks/{task_id}/criteria", headers=h, json={"items": [{"text": secret}]}
        )
        await c.post(
            f"/v1/tasks/{task_id}/comments",
            headers=h,
            json={"body": secret, "author_kind": "human"},
        )
        await c.post(
            f"/v1/tasks/{task_id}/artifacts",
            headers=h,
            json={
                "name": f"{secret}.txt",
                "kind": "file",
                "content_b64": base64.b64encode(secret.encode()).decode(),
            },
        )

        for kind, data in await _channel(c, h, project_id):
            assert secret not in json.dumps(data, ensure_ascii=False), (
                f"sự kiện {kind!r} mang theo nội dung đầu việc"
            )


async def test_a_stranger_cannot_read_a_project_card_counts():
    """New route, same guard as its neighbours (Hiến pháp I, FR-081). Asserted rather than
    assumed: T174 found seven routes that answered a stranger because nobody had ever
    pointed one at them."""
    async with await _client() as c:
        h, ws_id = await _patron(c, "counts-e@armarius.dev")
        project_id = await _project(c, h, ws_id)
        await _task(c, h, project_id, "Việc riêng")
        hb, _ = await _patron(c, "counts-f@armarius.dev")

        r = await c.get(f"/v1/projects/{project_id}/task-counts", headers=hb)
        assert r.status_code == 404, f"{r.status_code}: {r.text[:200]}"
