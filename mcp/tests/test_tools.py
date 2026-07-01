"""Tool-layer behaviour: arg validation, client mapping, token persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from armarius_mcp import tools
from armarius_mcp.client import ArmariusApiError
from armarius_mcp.credentials import CREDENTIAL_KEYS, load
from armarius_mcp.state import ServerState


async def test_whoami_delegates(state: ServerState):
    await tools.whoami(state)
    assert state.client.last()[0] == "whoami"  # type: ignore[attr-defined]


async def test_update_status_rejects_unknown(state: ServerState):
    with pytest.raises(tools.ToolError) as ei:
        await tools.update_status(state, "T1", "shipped")
    assert "shipped" in str(ei.value)
    # No HTTP call was made.
    assert not state.client.calls  # type: ignore[attr-defined]


async def test_update_status_rejects_draft(state: ServerState):
    with pytest.raises(tools.ToolError):
        await tools.update_status(state, "T1", "draft")


async def test_update_status_accepts_valid(state: ServerState):
    await tools.update_status(state, "T1", "in_progress", "starting")
    name, args, _ = state.client.last()  # type: ignore[attr-defined]
    assert name == "update_status"
    assert args == ("T1", "in_progress", "starting")


async def test_publish_artifact_link_needs_uri(state: ServerState):
    with pytest.raises(tools.ToolError) as ei:
        await tools.publish_artifact(state, "T1", "ref", kind="link")
    assert "uri" in str(ei.value)


async def test_publish_artifact_file_needs_content(state: ServerState):
    with pytest.raises(tools.ToolError):
        await tools.publish_artifact(state, "T1", "out.txt", kind="file")


async def test_publish_artifact_note_with_content_ok(state: ServerState):
    await tools.publish_artifact(state, "T1", "n", kind="note", content="hi")
    name, args, kwargs = state.client.last()  # type: ignore[attr-defined]
    assert name == "publish_artifact"
    assert kwargs["kind"] == "note" and kwargs["content"] == "hi"


async def test_publish_artifact_unknown_kind(state: ServerState):
    with pytest.raises(tools.ToolError):
        await tools.publish_artifact(state, "T1", "n", kind="binary")


async def test_post_comment_rejects_empty(state: ServerState):
    with pytest.raises(tools.ToolError):
        await tools.post_comment(state, "T1", "   ")


async def test_enroll_requires_both_args(state: ServerState):
    with pytest.raises(tools.ToolError):
        await tools.enroll(state, "", "code")
    with pytest.raises(tools.ToolError):
        await tools.enroll(state, "M1", "")


async def test_enroll_persists_token_and_writes_credentials(state: ServerState):
    out = await tools.enroll(state, "M1", "code123")
    assert out["enrolled"] is True
    # Token cached in client + config.
    assert state.client.token == "arm_minted_token"  # type: ignore[attr-defined]
    assert state.config.token == "arm_minted_token"
    # Credential file written with the full 6-key shape.
    creds = load(state.config.credential_path)
    data = json.loads(Path(state.config.credential_path).read_text(encoding="utf-8"))
    assert set(data.keys()) == set(CREDENTIAL_KEYS)
    assert creds.agent_token == "arm_minted_token"
    assert creds.agent_name == "Marin" and creds.workspace == "Acme"


async def test_claim_persists_token(state: ServerState):
    out = await tools.claim(state, "M1", "code123")
    assert out["claimed"] is True
    assert state.config.token == "arm_claimed_token"


async def test_enroll_timeout_maps_to_claim_hint(state: ServerState):
    async def boom(*a, **k):
        raise ArmariusApiError(0, "request timed out", "the call took too long")

    state.client.enroll = boom  # type: ignore[attr-defined]
    with pytest.raises(tools.ToolError) as ei:
        await tools.enroll(state, "M1", "code123", timeout_seconds=1)
    msg = str(ei.value)
    assert "claim" in msg and "approve" in msg.lower()


async def test_enroll_reraises_real_api_error(state: ServerState):
    async def bad_code(*a, **k):
        raise ArmariusApiError(400, "invalid enrollment code")

    state.client.enroll = bad_code  # type: ignore[attr-defined]
    with pytest.raises(ArmariusApiError) as ei:
        await tools.enroll(state, "M1", "wrong")
    assert ei.value.status_code == 400
