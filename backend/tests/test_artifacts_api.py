"""Contract-conformance — Shared Artifact Store publish + the 409 DONE-gate (API_CONTRACT §7).

The fatal failure Armarius prevents: an agent finishes but leaves the output local. A task
cannot reach `in_review`/`done` without ≥1 published file/link artifact — rejected `409`.
"""

from __future__ import annotations

import base64
import hashlib

from httpx import ASGITransport, AsyncClient

from armarius.main import app
from tests.support.projects import force_operating


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(c: AsyncClient, email: str) -> tuple[str, str]:
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    token = r.json()["tokens"]["access_token"]
    ws = await c.get("/v1/workspaces", headers={"Authorization": f"Bearer {token}"})
    return token, ws.json()[0]["id"]


async def _task(c: AsyncClient, ws_id: str, h: dict) -> str:
    proj = await c.post(
        f"/v1/workspaces/{ws_id}/projects",
        headers=h,
        json={"name": "Apollo", "leader": {"description": "Leads.", "marius_id": None},
},
    )
    pid = proj.json()["id"]
    # FR-003: real tasks need a project past the plan gate. The Done-gate is what this
    # file is about, so step over the plan gate rather than replaying it here.
    await force_operating(pid)
    task = await c.post(
        f"/v1/projects/{pid}/tasks", headers=h, json={"title": "Implement /login"}
    )
    return task.json()["id"]


async def _status(c: AsyncClient, task_id: str, h: dict, status: str):
    return await c.post(f"/v1/tasks/{task_id}/status", headers=h, json={"status": status})


async def test_done_gate_blocks_until_an_artifact_is_published() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "art1@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        task_id = await _task(c, ws_id, h)

        assert (await _status(c, task_id, h, "todo")).status_code == 200
        assert (await _status(c, task_id, h, "in_progress")).status_code == 200

        # No artifact yet → the DONE gate rejects in_review with 409.
        blocked = await _status(c, task_id, h, "in_review")
        assert blocked.status_code == 409, blocked.text
        assert "artifact" in blocked.json()["detail"].lower()

        # Publish a link artifact, then the same transition is allowed.
        published = await c.post(
            f"/v1/tasks/{task_id}/artifacts",
            headers=h,
            json={"name": "PR #42", "kind": "link", "uri": "https://github.com/a/b/pull/42"},
        )
        assert published.status_code == 201, published.text
        assert published.json()["stored"] is False  # link ⇒ not stored in the bucket

        ok = await _status(c, task_id, h, "in_review")
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "in_review"


async def test_publish_file_decodes_content_b64_and_verifies_sha256() -> None:
    raw = b"def login():\n    return 200\n"
    b64 = base64.b64encode(raw).decode()
    sha = hashlib.sha256(raw).hexdigest()
    async with await _client() as c:
        token, ws_id = await _register(c, "art2@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        task_id = await _task(c, ws_id, h)

        r = await c.post(
            f"/v1/tasks/{task_id}/artifacts",
            headers=h,
            json={"name": "login.py", "kind": "file", "content_b64": b64,
                  "content_sha256": sha, "size_bytes": len(raw)},
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["stored"] is True
    assert body["content_sha256"] == sha
    assert body["size_bytes"] == len(raw)


async def test_publish_file_with_mismatched_sha256_is_400() -> None:
    raw = b"the real bytes"
    b64 = base64.b64encode(raw).decode()
    async with await _client() as c:
        token, ws_id = await _register(c, "art3@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        task_id = await _task(c, ws_id, h)

        r = await c.post(
            f"/v1/tasks/{task_id}/artifacts",
            headers=h,
            json={"name": "x.txt", "kind": "file", "content_b64": b64,
                  "content_sha256": "deadbeef" * 8},
        )
    assert r.status_code == 400, r.text


# ── spec 002: a publish survives being called twice, and is proven stored ────────
# (FR-020, FR-020b, FR-020c, FR-020d — the agent's own publish route)


async def _operating_task(c: AsyncClient, email: str):
    """An operating project with one task handed to the worker, over the real routes."""
    from tests.support.planning import operating_project

    p = await operating_project(c, email)
    created = await c.post(
        f"/agent/projects/{p.project_id}/tasks",
        headers=p.leader_headers,
        json={
            "title": "Kết xuất báo cáo",
            "description": "Gom số liệu rồi kết xuất ra tệp.",
            "assignee_marius_id": p.worker_id,
            "plan_item_id": p.item_id(0),
        },
    )
    assert created.status_code == 201, created.text
    return p, str(created.json()["id"])


def _file_body(name: str, raw: bytes) -> dict:
    return {
        "name": name,
        "kind": "file",
        "content_b64": base64.b64encode(raw).decode(),
    }


async def test_republish_same_bytes_is_200_and_fathers_no_duplicate() -> None:
    """FR-020c: the retry after a dropped upload lands on the row already written."""
    async with await _client() as c:
        p, task_id = await _operating_task(c, "art-dup@armarius.dev")
        body = _file_body("report.md", b"monthly report, v1\n")

        first = await c.post(
            f"/agent/tasks/{task_id}/artifact", headers=p.worker_headers, json=body
        )
        assert first.status_code == 201, first.text
        assert first.json()["created"] is True
        assert first.json()["version"] == 1

        again = await c.post(
            f"/agent/tasks/{task_id}/artifact", headers=p.worker_headers, json=body
        )
        assert again.status_code == 200, again.text
        assert again.json()["created"] is False
        assert again.json()["id"] == first.json()["id"]

        # FR-020b: no attempt counter — the third retry is as welcome as the second.
        third = await c.post(
            f"/agent/tasks/{task_id}/artifact", headers=p.worker_headers, json=body
        )
        assert third.status_code == 200, third.text

        listed = await c.get(f"/v1/tasks/{task_id}/artifacts", headers=p.headers)
        assert [a["id"] for a in listed.json()] == [first.json()["id"]]


async def test_same_name_with_new_bytes_is_a_new_version() -> None:
    """FR-020c: same name, different bytes — a new version of the one artifact meant."""
    async with await _client() as c:
        p, task_id = await _operating_task(c, "art-ver@armarius.dev")

        first = await c.post(
            f"/agent/tasks/{task_id}/artifact",
            headers=p.worker_headers,
            json=_file_body("report.md", b"v1\n"),
        )
        assert first.status_code == 201, first.text

        changed = await c.post(
            f"/agent/tasks/{task_id}/artifact",
            headers=p.worker_headers,
            json=_file_body("report.md", b"v2 - more numbers\n"),
        )
        assert changed.status_code == 201, changed.text
        assert changed.json()["created"] is True
        assert changed.json()["version"] == 2
        assert changed.json()["id"] != first.json()["id"]

        listed = await c.get(f"/v1/tasks/{task_id}/artifacts", headers=p.headers)
        assert len(listed.json()) == 2


async def test_a_republished_link_is_found_not_duplicated() -> None:
    """A link has no bytes; its URL is the fingerprint (research §6)."""
    async with await _client() as c:
        p, task_id = await _operating_task(c, "art-link@armarius.dev")
        body = {"name": "PR", "kind": "link", "uri": "https://github.com/a/b/pull/42"}

        first = await c.post(
            f"/agent/tasks/{task_id}/artifact", headers=p.worker_headers, json=body
        )
        assert first.status_code == 201, first.text

        again = await c.post(
            f"/agent/tasks/{task_id}/artifact", headers=p.worker_headers, json=body
        )
        assert again.status_code == 200, again.text
        assert again.json()["id"] == first.json()["id"]

        moved = await c.post(
            f"/agent/tasks/{task_id}/artifact",
            headers=p.worker_headers,
            json={"name": "PR", "kind": "link", "uri": "https://github.com/a/b/pull/43"},
        )
        assert moved.status_code == 201, moved.text
        assert moved.json()["version"] == 2


async def test_the_retry_is_welcome_after_the_task_has_moved_on() -> None:
    """FR-020b: the dedup key carries no run — the working directory lives with the
    task, so the same bytes published in a later run still land on the same row."""
    async with await _client() as c:
        p, task_id = await _operating_task(c, "art-run@armarius.dev")
        body = _file_body("report.md", b"same bytes, another day\n")

        first = await c.post(
            f"/agent/tasks/{task_id}/artifact", headers=p.worker_headers, json=body
        )
        assert first.status_code == 201, first.text

        moved = await c.post(
            f"/v1/tasks/{task_id}/status", headers=p.headers, json={"status": "in_progress"}
        )
        assert moved.status_code == 200, moved.text

        later = await c.post(
            f"/agent/tasks/{task_id}/artifact", headers=p.worker_headers, json=body
        )
        assert later.status_code == 200, later.text
        assert later.json()["created"] is False
        assert later.json()["id"] == first.json()["id"]


async def test_a_publish_in_flight_keeps_the_drive_alive() -> None:
    """FR-020d: at the Done gate with no run speaking, the publish itself is the sign of
    life — the task must not read as dropped while it is being published into."""
    from uuid import UUID

    from armarius.infrastructure.database.models import TaskModel
    from tests.support.app_db import app_uow

    async with await _client() as c:
        p, task_id = await _operating_task(c, "art-drive@armarius.dev")
        moved = await c.post(
            f"/v1/tasks/{task_id}/status", headers=p.headers, json={"status": "in_progress"}
        )
        assert moved.status_code == 200, moved.text

        # Take the provisional drive away, so the publish is the only thing left that
        # could keep this task alive. Nothing else changed — this is the run that went
        # quiet the moment before the agent pushed its output.
        async with app_uow() as uow:
            session = uow._session  # noqa: SLF001 — reading the app's own database
            row = await session.get(TaskModel, UUID(task_id))
            assert row is not None
            row.drive = None
            row.drive_expires_at = None
            await session.commit()

        published = await c.post(
            f"/agent/tasks/{task_id}/artifact",
            headers=p.worker_headers,
            json=_file_body("report.md", b"the output\n"),
        )
        assert published.status_code == 201, published.text

        shown = await c.get(f"/v1/tasks/{task_id}", headers=p.headers)
        assert shown.status_code == 200, shown.text
        assert shown.json()["drive"] == "run_active"
        assert shown.json()["stalled"] is False


async def test_a_store_that_cannot_return_the_bytes_records_nothing() -> None:
    """FR-020: the row is written only after the bytes are fetched back and match."""
    from armarius.main import app

    async with await _client() as c:
        p, task_id = await _operating_task(c, "art-store@armarius.dev")
        store = app.state.container.artifact_store
        original = store.read_bytes

        async def corrupt(uri: str) -> bytes:  # noqa: ARG001
            return b"not what was written"

        store.read_bytes = corrupt  # type: ignore[method-assign]
        try:
            failed = await c.post(
                f"/agent/tasks/{task_id}/artifact",
                headers=p.worker_headers,
                json=_file_body("report.md", b"the real bytes\n"),
            )
            assert failed.status_code == 502, failed.text
            assert failed.json()["code"] == "artifact_store_unreadable"
        finally:
            store.read_bytes = original  # type: ignore[method-assign]

        listed = await c.get(f"/v1/tasks/{task_id}/artifacts", headers=p.headers)
        assert listed.json() == []

        # FR-020b: once the store is well again, the very same call goes through.
        retry = await c.post(
            f"/agent/tasks/{task_id}/artifact",
            headers=p.worker_headers,
            json=_file_body("report.md", b"the real bytes\n"),
        )
        assert retry.status_code == 201, retry.text


# ── Getting the bytes back out again (SC-004, T129) ──────────────────────────
#
# Publishing had been proving only half of SC-004. The bytes went into the shared store and
# were read back to check the store had kept them — and then nothing could ever ask for them
# again: no route, and a screen whose link pointed at the store-relative path, which resolves
# to nothing. *Stored* and *gettable* are two claims, and the second is the one a person needs.


async def test_a_published_file_can_be_fetched_back_byte_for_byte() -> None:
    raw = b"DELIVERED\n"
    b64 = base64.b64encode(raw).decode()
    async with await _client() as c:
        token, ws_id = await _register(c, "art-get@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        task_id = await _task(c, ws_id, h)
        published = await c.post(
            f"/v1/tasks/{task_id}/artifacts",
            headers=h,
            json={"name": "report.txt", "kind": "file", "content_b64": b64,
                  "content_sha256": hashlib.sha256(raw).hexdigest()},
        )
        assert published.status_code == 201, published.text
        artifact_id = published.json()["id"]

        got = await c.get(
            f"/v1/tasks/{task_id}/artifacts/{artifact_id}/content", headers=h
        )
    assert got.status_code == 200, got.text
    assert got.content == raw
    # The agent's own name for it, so what lands on the person's disk is what they published.
    assert 'filename="report.txt"' in got.headers["content-disposition"]
    assert got.headers["content-disposition"].startswith("attachment")


async def test_a_link_artifact_says_there_is_nothing_here_to_download() -> None:
    """A link names something somewhere else. An empty file would be a worse answer."""
    async with await _client() as c:
        token, ws_id = await _register(c, "art-link@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        task_id = await _task(c, ws_id, h)
        published = await c.post(
            f"/v1/tasks/{task_id}/artifacts",
            headers=h,
            json={"name": "PR #42", "kind": "link", "uri": "https://example.invalid/pull/42"},
        )
        assert published.status_code == 201, published.text

        refused = await c.get(
            f"/v1/tasks/{task_id}/artifacts/{published.json()['id']}/content", headers=h
        )
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "artifact_has_no_stored_bytes"


async def test_an_artifact_of_another_task_reads_as_no_such_artifact() -> None:
    """Điều I: the right to be here was decided about *this* task, so the id alone is not a key."""
    raw = b"not yours"
    async with await _client() as c:
        token, ws_id = await _register(c, "art-scope@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        mine = await _task(c, ws_id, h)
        published = await c.post(
            f"/v1/tasks/{mine}/artifacts",
            headers=h,
            json={"name": "mine.txt", "kind": "file", "content_b64": base64.b64encode(raw).decode(),
                  "content_sha256": hashlib.sha256(raw).hexdigest()},
        )
        assert published.status_code == 201, published.text
        other = await _task(c, ws_id, h)

        refused = await c.get(
            f"/v1/tasks/{other}/artifacts/{published.json()['id']}/content", headers=h
        )
    assert refused.status_code == 404, refused.text
    assert refused.json()["code"] == "artifact_not_found"


async def test_somebody_elses_artifact_reads_as_no_such_task() -> None:
    raw = b"theirs"
    async with await _client() as c:
        theirs, their_ws = await _register(c, "art-them@armarius.dev")
        th = {"Authorization": f"Bearer {theirs}"}
        their_task = await _task(c, their_ws, th)
        published = await c.post(
            f"/v1/tasks/{their_task}/artifacts",
            headers=th,
            json={"name": "theirs.txt", "kind": "file",
                  "content_b64": base64.b64encode(raw).decode(),
                  "content_sha256": hashlib.sha256(raw).hexdigest()},
        )
        assert published.status_code == 201, published.text

        mine, _ = await _register(c, "art-me@armarius.dev")
        refused = await c.get(
            f"/v1/tasks/{their_task}/artifacts/{published.json()['id']}/content",
            headers={"Authorization": f"Bearer {mine}"},
        )
    assert refused.status_code == 404, refused.text
    assert refused.json()["code"] == "task_not_found"


async def test_a_retried_publish_leaves_one_artifact_that_still_downloads() -> None:
    """SC-004a end to end: publish, publish the very same bytes again, fetch what is there.

    The retry is the case a dropped reply produces — the caller cannot tell its first attempt
    landed. One row, one download, and the bytes are the ones that were sent.
    """
    raw = b"exactly once\n"
    body = {"name": "once.txt", "kind": "file",
            "content_b64": base64.b64encode(raw).decode(),
            "content_sha256": hashlib.sha256(raw).hexdigest()}
    async with await _client() as c:
        token, ws_id = await _register(c, "art-retry@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        task_id = await _task(c, ws_id, h)

        first = await c.post(f"/v1/tasks/{task_id}/artifacts", headers=h, json=body)
        again = await c.post(f"/v1/tasks/{task_id}/artifacts", headers=h, json=body)
        assert first.status_code == 201, first.text
        # 200, not 201: nothing was created the second time, and the status code is the one
        # field a caller reads without parsing (FR-020c).
        assert again.status_code == 200, again.text
        assert again.json()["id"] == first.json()["id"], "một lần thử lại đẻ ra hiện vật thứ hai"

        listed = await c.get(f"/v1/tasks/{task_id}/artifacts", headers=h)
        got = await c.get(
            f"/v1/tasks/{task_id}/artifacts/{first.json()['id']}/content", headers=h
        )
    assert len(listed.json()) == 1, listed.json()
    assert got.status_code == 200, got.text
    assert got.content == raw
