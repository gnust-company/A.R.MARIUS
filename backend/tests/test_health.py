"""Health endpoint — reports DB + artifact-store status (ARCHITECTURE §9)."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from armarius.main import app


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_health_reports_db_and_store_up():
    async with await _client() as c:
        r = await c.get("/health")
    assert r.status_code == 200
    body = r.json()
    # Under test the schema is provisioned and the (local) artifact store is ready.
    assert body["db"] == "up"
    assert body["minio"] == "up"
    assert body["status"] == "ok"


async def test_healthz_still_ok():
    async with await _client() as c:
        r = await c.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
