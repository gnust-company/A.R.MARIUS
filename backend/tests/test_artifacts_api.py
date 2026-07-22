"""Contract-conformance — Shared Artifact Store publish + the 409 DONE-gate (API_CONTRACT §7).

The fatal failure Armarius prevents: an agent finishes but leaves the output local. A task
cannot reach `in_review`/`done` without ≥1 published file/link artifact — rejected `409`.
"""

from __future__ import annotations

import base64
import hashlib

from httpx import ASGITransport, AsyncClient

from armarius.main import app


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
              "roles": [{"title": "Backend", "seats": 1, "description": "Owns the API."}]},
    )
    pid = proj.json()["id"]
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
