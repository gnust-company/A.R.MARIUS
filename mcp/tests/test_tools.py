"""Tool-layer behaviour: arg validation, client mapping, token persistence."""

from __future__ import annotations

import pytest

from armarius_mcp import tools
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
