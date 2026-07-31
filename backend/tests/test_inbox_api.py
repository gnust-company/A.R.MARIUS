"""Patron inbox — real surface, routed per recipient, tenant-scoped (spec 001 §11).

Replaces the browser-side filtering the Inbox page does today. Two things must hold:
an item is visible to **exactly** the patron it was addressed to (FR-035), and nothing
crosses a workspace boundary (Constitution I).
"""

from __future__ import annotations

from uuid import UUID

from httpx import ASGITransport, AsyncClient

from armarius.domain.entities.inbox_item import InboxItemKind
from armarius.main import app


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(c: AsyncClient, email: str) -> tuple[str, str, str]:
    """Register a patron; return (token, workspace_id, user_id)."""
    r = await c.post(
        "/auth/register",
        json={"email": email, "full_name": "Patron", "password": "password1234"},
    )
    body = r.json()
    token = body["tokens"]["access_token"]
    user_id = body["user"]["id"]
    ws = await c.get("/v1/workspaces", headers={"Authorization": f"Bearer {token}"})
    return token, ws.json()[0]["id"], user_id


async def _put_item(
    *, workspace_id: str, recipient: str, kind: InboxItemKind, title: str
) -> UUID:
    item = await app.state.container.inbox.place(
        workspace_id=UUID(workspace_id),
        recipient_user_id=recipient,
        kind=kind,
        title=title,
    )
    return item.id


async def test_lists_only_my_pending_items() -> None:
    async with await _client() as c:
        token, ws_id, uid = await _register(c, "inbox-mine@armarius.dev")
        await _put_item(
            workspace_id=ws_id,
            recipient=uid,
            kind=InboxItemKind.PLAN_APPROVAL,
            title="Kế hoạch chờ duyệt",
        )
        await _put_item(
            workspace_id=ws_id,
            recipient="someone-else",
            kind=InboxItemKind.QUESTION,
            title="Không phải của tôi",
        )

        r = await c.get("/v1/inbox", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200, r.text
    items = r.json()
    assert [i["title"] for i in items] == ["Kế hoạch chờ duyệt"]
    assert items[0]["kind"] == "plan_approval"
    assert items[0]["status"] == "pending"
    assert items[0]["reminder_tier"] == 0


async def test_resolve_removes_it_from_the_pending_list() -> None:
    async with await _client() as c:
        token, ws_id, uid = await _register(c, "inbox-resolve@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        item_id = await _put_item(
            workspace_id=ws_id,
            recipient=uid,
            kind=InboxItemKind.OUTPUT_ACCEPTANCE,
            title="Chờ công nhận",
        )

        done = await c.post(f"/v1/inbox/{item_id}/resolve", headers=h)
        assert done.status_code == 200, done.text
        assert done.json()["status"] == "resolved"
        assert done.json()["resolved_at"] is not None

        still_pending = await c.get("/v1/inbox", headers=h)
        assert still_pending.json() == []

        all_items = await c.get("/v1/inbox?status=resolved", headers=h)
    assert [i["id"] for i in all_items.json()] == [str(item_id)]


async def test_another_patron_cannot_see_or_resolve_my_item() -> None:
    async with await _client() as c:
        _, ws_a, uid_a = await _register(c, "inbox-a@armarius.dev")
        token_b, _, _ = await _register(c, "inbox-b@armarius.dev")
        item_id = await _put_item(
            workspace_id=ws_a,
            recipient=uid_a,
            kind=InboxItemKind.ESCALATION,
            title="Việc của A",
        )

        h_b = {"Authorization": f"Bearer {token_b}"}
        listed = await c.get("/v1/inbox", headers=h_b)
        assert listed.json() == []

        # Not "forbidden" — B must not learn the item exists at all (Constitution I).
        stolen = await c.post(f"/v1/inbox/{item_id}/resolve", headers=h_b)
    assert stolen.status_code == 404, stolen.text


async def test_filter_by_project() -> None:
    from uuid import uuid4

    async with await _client() as c:
        token, ws_id, uid = await _register(c, "inbox-filter@armarius.dev")
        project_a, project_b = uuid4(), uuid4()

        for project_id, title in ((project_a, "của A"), (project_b, "của B")):
            await app.state.container.inbox.place(
                workspace_id=UUID(ws_id),
                recipient_user_id=uid,
                kind=InboxItemKind.QUESTION,
                title=title,
                project_id=project_id,
            )

        r = await c.get(
            f"/v1/inbox?project_id={project_a}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert [i["title"] for i in r.json()] == ["của A"]


async def test_inbox_requires_authentication() -> None:
    async with await _client() as c:
        r = await c.get("/v1/inbox")
    assert r.status_code == 401
