"""A task appearing must reach the project channel (T175, FR-080a, Hiến pháp IV).

Checked end to end — real HTTP route, real bus, real event stream — because that is the
whole distance the failure covered: the service wrote the row and returned, so every unit
around it was correct and the board still sat still until someone reloaded the page.

The push guard in ``test_constitution_guards`` was green throughout. It reads the frontend
source and asks whether a timer exists. No timer existed. "Does not poll" and "updates" are
different sentences, and the board was the first one without being the second.

``?live=0`` is the finite catch-up form of the stream: it replays the backlog and closes,
so the events can be read back in a test without holding an open connection.
"""

from __future__ import annotations

import json

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


async def test_creating_a_task_puts_something_on_the_project_channel():
    async with await _client() as c:
        h, ws_id = await _patron(c, "board-a@armarius.dev")
        project_id = await _project(c, h, ws_id)

        before = await _channel(c, h, project_id)

        r = await c.post(
            f"/v1/projects/{project_id}/tasks",
            headers=h,
            json={"title": "Việc vừa thêm", "description": "Từ ngoài trình duyệt"},
        )
        assert r.status_code == 201, r.text
        task_id = r.json()["id"]

        after = await _channel(c, h, project_id)
        fresh = after[len(before):]
        assert fresh, (
            "tạo đầu việc không đặt gì lên kênh dự án — bảng đang mở sẽ đứng im cho tới "
            "khi có người tải lại trang"
        )

        created = [data for kind, data in fresh if kind == "task.created"]
        assert created, f"kênh dự án nhận được {[k for k, _ in fresh]}, thiếu 'task.created'"
        assert created[0]["task_id"] == task_id


async def test_the_created_event_carries_no_task_content():
    """Contract `push-events` principle 4: identifiers and labels, never the text itself.

    An event is a signal — the page re-reads through the API, where the workspace guard
    still applies. Content on the wire would make the stream a second, unguarded way to
    read the same row.
    """
    async with await _client() as c:
        h, ws_id = await _patron(c, "board-b@armarius.dev")
        project_id = await _project(c, h, ws_id)

        secret = "Bí mật thương mại không được lên dây"
        r = await c.post(
            f"/v1/projects/{project_id}/tasks",
            headers=h,
            json={"title": secret, "description": secret},
        )
        assert r.status_code == 201, r.text

        for kind, data in await _channel(c, h, project_id):
            assert secret not in json.dumps(data, ensure_ascii=False), (
                f"sự kiện {kind!r} mang theo nội dung đầu việc"
            )


async def test_a_stranger_cannot_listen_to_the_project_channel():
    """The new event travels the same stream as the old ones, so it inherits the same guard
    — asserted here rather than assumed, since this is the first event a board draws from
    a row the listener may never have been allowed to see."""
    async with await _client() as c:
        h, ws_id = await _patron(c, "board-c@armarius.dev")
        project_id = await _project(c, h, ws_id)
        hb, _ = await _patron(c, "board-d@armarius.dev")

        r = await c.get(f"/v1/projects/{project_id}/events?live=0", headers=hb)
        assert r.status_code == 404, f"{r.status_code}: {r.text[:200]}"
