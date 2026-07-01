"""Auth flow tests — register, login, refresh, me, duplicate handling."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from armarius.infrastructure.database.engine import init_db
from armarius.main import app
from armarius.presentation.container import build_container


@pytest.fixture(autouse=True)
async def _bootstrap():
    """Fresh DB + container for each test."""
    await init_db()
    app.state.container = build_container()
    yield


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_register_returns_user_and_tokens():
    async with await _client() as c:
        r = await c.post(
            "/auth/register",
            json={
                "email": "patron@armarius.dev",
                "username": "patron",
                "full_name": "Test Patron",
                "password": "supersecret123",
            },
        )
    assert r.status_code == 201
    body = r.json()
    assert body["user"]["email"] == "patron@armarius.dev"
    assert body["user"]["username"] == "patron"
    assert body["tokens"]["access_token"]
    assert body["tokens"]["refresh_token"]


async def test_register_personal_workspace_starts_empty():
    """Sprint 6 review fix: a freshly registered user's Personal workspace has NO
    auto-created project — the old "General" default was removed so the patron
    commissions the first project explicitly (board empty state guides them).
    """
    async with await _client() as c:
        r = await c.post(
            "/auth/register",
            json={
                "email": "freshpatron@armarius.dev",
                "username": "freshpatron",
                "full_name": "Fresh Patron",
                "password": "supersecret123",
            },
        )
        assert r.status_code == 201
        token = r.json()["tokens"]["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        workspaces = (await c.get("/v1/workspaces", headers=h)).json()
        assert len(workspaces) == 1
        ws = workspaces[0]
        assert ws["name"] == "Personal"

        # No auto-created "General" project anymore.
        projects = (await c.get(f"/v1/workspaces/{ws['id']}/projects", headers=h)).json()
        assert projects == []


async def test_login_and_me():
    async with await _client() as c:
        await c.post(
            "/auth/register",
            json={
                "email": "alice@armarius.dev",
                "username": "alice",
                "full_name": "Alice",
                "password": "password1234",
            },
        )
        login = await c.post(
            "/auth/login",
            json={"email": "alice@armarius.dev", "password": "password1234"},
        )
        assert login.status_code == 200
        token = login.json()["tokens"]["access_token"]

        me = await c.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == "alice"


async def test_login_wrong_password():
    async with await _client() as c:
        await c.post(
            "/auth/register",
            json={
                "email": "bob@armarius.dev",
                "username": "bob",
                "full_name": "Bob",
                "password": "password1234",
            },
        )
        r = await c.post(
            "/auth/login",
            json={"email": "bob@armarius.dev", "password": "wrongpassword"},
        )
    assert r.status_code == 401


async def test_duplicate_email_rejected():
    payload = {
        "email": "dup@armarius.dev",
        "username": "first",
        "full_name": "First",
        "password": "password1234",
    }
    async with await _client() as c:
        first = await c.post("/auth/register", json=payload)
        assert first.status_code == 201
        second = await c.post(
            "/auth/register",
            json={**payload, "username": "second"},
        )
    assert second.status_code == 409


async def test_refresh_issues_new_tokens():
    async with await _client() as c:
        reg = await c.post(
            "/auth/register",
            json={
                "email": "ref@armarius.dev",
                "username": "ref",
                "full_name": "Ref",
                "password": "password1234",
            },
        )
        refresh_token = reg.json()["tokens"]["refresh_token"]
        r = await c.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert r.status_code == 200
    assert r.json()["access_token"]


async def test_me_without_token_is_401():
    async with await _client() as c:
        r = await c.get("/auth/me")
    assert r.status_code == 401


async def test_invalid_token_is_401():
    async with await _client() as c:
        r = await c.get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401
