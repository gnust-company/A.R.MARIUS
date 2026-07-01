"""ArmariusClient → HTTP mapping, verified with respx (httpx mock transport)."""

from __future__ import annotations

import httpx
import pytest
import respx

from armarius_mcp.client import ArmariusClient, NotEnrolledError
from armarius_mcp.http_error import ArmariusApiError

BASE = "http://api.test"


@pytest.fixture
async def client():
    c = ArmariusClient(BASE, "arm_tok")
    yield c
    await c.aclose()


@respx.mock
async def test_whoami_sends_bearer(client: ArmariusClient):
    route = respx.get(f"{BASE}/agent/me").mock(
        return_value=httpx.Response(200, json={"marius": {"name": "Marin"}})
    )
    out = await client.whoami()
    assert out == {"marius": {"name": "Marin"}}
    assert route.calls.last.request.headers["Authorization"] == "Bearer arm_tok"


@respx.mock
async def test_get_task_path(client: ArmariusClient):
    route = respx.get(f"{BASE}/agent/tasks/T1").mock(return_value=httpx.Response(200, json={}))
    await client.get_task("T1")
    assert route.called


@respx.mock
async def test_claim_task_posts_empty_body(client: ArmariusClient):
    route = respx.post(f"{BASE}/agent/tasks/T1/claim").mock(
        return_value=httpx.Response(200, json={"id": "T1", "status": "in_progress"})
    )
    await client.claim_task("T1")
    assert route.calls.last.request.content == b"{}"


@respx.mock
async def test_post_comment_body(client: ArmariusClient):
    route = respx.post(f"{BASE}/agent/tasks/T1/comment").mock(
        return_value=httpx.Response(201, json={"id": "c1", "body": "hi @Bob"})
    )
    await client.post_comment("T1", "hi @Bob")
    import json

    assert json.loads(route.calls.last.request.content) == {"body": "hi @Bob"}


@respx.mock
async def test_update_status_omits_reason_when_none(client: ArmariusClient):
    route = respx.post(f"{BASE}/agent/tasks/T1/status").mock(
        return_value=httpx.Response(200, json={"id": "T1", "status": "in_progress"})
    )
    await client.update_status("T1", "in_progress")
    import json

    assert json.loads(route.calls.last.request.content) == {"status": "in_progress"}


@respx.mock
async def test_update_status_includes_reason(client: ArmariusClient):
    route = respx.post(f"{BASE}/agent/tasks/T1/status").mock(
        return_value=httpx.Response(200, json={})
    )
    await client.update_status("T1", "blocked", "waiting on API")
    import json

    assert json.loads(route.calls.last.request.content) == {
        "status": "blocked",
        "reason": "waiting on API",
    }


@respx.mock
async def test_set_next_action_null_clears(client: ArmariusClient):
    route = respx.post(f"{BASE}/agent/tasks/T1/next-action").mock(
        return_value=httpx.Response(200, json={})
    )
    await client.set_next_action("T1", None)
    import json

    assert json.loads(route.calls.last.request.content) == {"next_action": None}


@respx.mock
async def test_publish_artifact_only_sends_present_fields(client: ArmariusClient):
    route = respx.post(f"{BASE}/agent/tasks/T1/artifact").mock(
        return_value=httpx.Response(201, json={"id": "a1"})
    )
    await client.publish_artifact("T1", name="notes.md", kind="note", content="hello")
    import json

    body = json.loads(route.calls.last.request.content)
    assert body == {"name": "notes.md", "kind": "note", "content": "hello"}
    assert "uri" not in body and "content_b64" not in body


@respx.mock
async def test_enroll_returns_token_no_auth_header(client: ArmariusClient):
    route = respx.post(f"{BASE}/agent/enroll").mock(
        return_value=httpx.Response(200, json={"agent_token": "arm_new"})
    )
    token = await ArmariusClient(BASE, None).enroll("M1", "code123")
    assert token == "arm_new"
    assert "Authorization" not in route.calls.last.request.headers
    import json

    sent = json.loads(route.calls.last.request.content)
    assert sent["marius_id"] == "M1" and sent["enrollment_code"] == "code123"
    assert sent["capabilities"] == [] and sent["adapter_config"] == {}


@respx.mock
async def test_claim_returns_token(client: ArmariusClient):
    respx.post(f"{BASE}/agent/claim").mock(
        return_value=httpx.Response(200, json={"agent_token": "arm_recovered"})
    )
    token = await ArmariusClient(BASE, None).claim("M1", "code123")
    assert token == "arm_recovered"


async def test_token_required_calls_raise_before_http():
    c = ArmariusClient(BASE, None)
    with pytest.raises(NotEnrolledError):
        await c.whoami()
    await c.aclose()


@respx.mock
async def test_401_becomes_api_error_with_hint(client: ArmariusClient):
    respx.get(f"{BASE}/agent/me").mock(
        return_value=httpx.Response(401, json={"detail": "invalid agent token"})
    )
    with pytest.raises(ArmariusApiError) as ei:
        await client.whoami()
    assert ei.value.status_code == 401
    assert "invalid agent token" in str(ei.value)
    assert "claim" in str(ei.value).lower()


@respx.mock
async def test_409_artifact_gate(client: ArmariusClient):
    respx.post(f"{BASE}/agent/tasks/T1/status").mock(
        return_value=httpx.Response(409, json={"detail": "artifact required before review"})
    )
    with pytest.raises(ArmariusApiError) as ei:
        await client.update_status("T1", "in_review")
    assert ei.value.status_code == 409


@respx.mock
async def test_transport_error_becomes_api_error(client: ArmariusClient):
    respx.get(f"{BASE}/agent/me").mock(side_effect=httpx.ConnectError("no route"))
    with pytest.raises(ArmariusApiError) as ei:
        await client.whoami()
    assert ei.value.status_code == 0
    assert "reach the backend" in str(ei.value)
