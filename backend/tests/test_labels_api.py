"""Contract-conformance — workspace-scoped Labels (API_CONTRACT §5.4)."""

from __future__ import annotations

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


async def test_create_then_list_label() -> None:
    async with await _client() as c:
        token, ws_id = await _register(c, "lab1@armarius.dev")
        h = {"Authorization": f"Bearer {token}"}
        created = await c.post(
            f"/v1/workspaces/{ws_id}/labels",
            headers=h,
            json={"name": "bug", "color": "#b91c1c"},
        )
        assert created.status_code == 201, created.text
        assert created.json()["name"] == "bug"
        assert created.json()["color"] == "#b91c1c"

        listed = await c.get(f"/v1/workspaces/{ws_id}/labels", headers=h)
    assert listed.status_code == 200
    names = {label["name"] for label in listed.json()}
    assert names == {"bug"}


async def test_labels_are_workspace_scoped() -> None:
    async with await _client() as c:
        token_a, ws_a = await _register(c, "lab-a@armarius.dev")
        ha = {"Authorization": f"Bearer {token_a}"}
        await c.post(
            f"/v1/workspaces/{ws_a}/labels", headers=ha, json={"name": "a-only"}
        )

        token_b, ws_b = await _register(c, "lab-b@armarius.dev")
        hb = {"Authorization": f"Bearer {token_b}"}
        b_labels = await c.get(f"/v1/workspaces/{ws_b}/labels", headers=hb)
    assert b_labels.status_code == 200
    assert b_labels.json() == []


async def test_label_cross_workspace_is_404() -> None:
    async with await _client() as c:
        _, ws_a = await _register(c, "lab-owner@armarius.dev")
        token_b, _ = await _register(c, "lab-intruder@armarius.dev")
        hb = {"Authorization": f"Bearer {token_b}"}
        r = await c.post(
            f"/v1/workspaces/{ws_a}/labels", headers=hb, json={"name": "x"}
        )
    assert r.status_code == 404, r.text
