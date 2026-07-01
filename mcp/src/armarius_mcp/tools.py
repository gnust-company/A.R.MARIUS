"""Tool implementations — pure functions over a ServerState.

Each maps to one ``ArmariusClient`` call and adds the guardrails a weak model needs:
- ``update_status`` constrains the target to the agent-settable enum (no ``draft``).
- ``publish_artifact`` enforces the content-vs-uri rule per kind before the round-trip.
- ``enroll`` translates the server-side hold into a bounded wait with a ``claim`` hint.

``server.py`` wraps these with FastMCP typing; tests drive them with a fake client, so
nothing here imports fastmcp.
"""

from __future__ import annotations

from typing import Any, Literal

from armarius_mcp.client import ArmariusApiError
from armarius_mcp.state import ServerState

# Agent-settable statuses (backend TaskStatus minus `draft`, which is commission-only).
Status = Literal[
    "backlog", "todo", "in_progress", "in_review", "blocked", "done", "cancelled"
]
STATUSES: tuple[str, ...] = (
    "backlog", "todo", "in_progress", "in_review", "blocked", "done", "cancelled"
)

ArtifactKind = Literal["file", "patch", "note", "link"]
ARTIFACT_KINDS: tuple[str, ...] = ("file", "patch", "note", "link")
_BODY_KINDS = ("file", "patch", "note")  # need content/content_b64


class ToolError(ValueError):
    """A client-side validation failure, surfaced to the agent before any HTTP call."""


async def enroll(
    state: ServerState,
    marius_id: str,
    enrollment_code: str,
    *,
    capabilities: list[str] | None = None,
    adapter_config: dict[str, Any] | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Present the enrollment code and hold until the patron approves; persist the token."""
    if not marius_id or not enrollment_code:
        raise ToolError("enroll needs both marius_id and enrollment_code (from your invite).")
    timeout = (
        timeout_seconds if timeout_seconds is not None else state.config.enroll_timeout_seconds
    )
    # Remember identity so the token can be persisted to the onboarding path.
    state.config.marius_id = marius_id
    state.config.enrollment_code = enrollment_code
    try:
        token = await state.client.enroll(
            marius_id,
            enrollment_code,
            capabilities=capabilities,
            adapter_config=adapter_config,
            timeout=timeout,
        )
    except ArmariusApiError as exc:
        if exc.status_code == 0:  # timeout / transport
            raise ToolError(
                f"Enrollment did not complete within {timeout:.0f}s — your patron may not have "
                "approved you yet. Retry `enroll`, or call `claim` once you know you are approved."
            ) from exc
        raise
    state.on_token_minted(token)
    return {"enrolled": True, "credential_file": state.config.credential_path}


async def claim(state: ServerState, marius_id: str, enrollment_code: str) -> dict[str, Any]:
    """Recover an already-approved token (use when an enroll session dropped)."""
    if not marius_id or not enrollment_code:
        raise ToolError("claim needs both marius_id and enrollment_code (from your invite).")
    state.config.marius_id = marius_id
    state.config.enrollment_code = enrollment_code
    token = await state.client.claim(marius_id, enrollment_code)
    state.on_token_minted(token)
    return {"claimed": True, "credential_file": state.config.credential_path}


async def whoami(state: ServerState) -> Any:
    return await state.client.whoami()


async def get_task(state: ServerState, task_id: str) -> Any:
    return await state.client.get_task(task_id)


async def claim_task(state: ServerState, task_id: str) -> Any:
    return await state.client.claim_task(task_id)


async def post_comment(state: ServerState, task_id: str, body: str) -> Any:
    if not body.strip():
        raise ToolError("comment body cannot be empty.")
    return await state.client.post_comment(task_id, body)


async def update_status(
    state: ServerState, task_id: str, status: str, reason: str | None = None
) -> Any:
    if status not in STATUSES:
        raise ToolError(
            f"unknown status {status!r}. Use one of: {', '.join(STATUSES)}. "
            "(`draft` is set by the leader only.)"
        )
    return await state.client.update_status(task_id, status, reason)


async def set_next_action(state: ServerState, task_id: str, next_action: str | None) -> Any:
    return await state.client.set_next_action(task_id, next_action)


async def publish_artifact(
    state: ServerState,
    task_id: str,
    name: str,
    kind: str = "file",
    *,
    content: str | None = None,
    content_b64: str | None = None,
    content_sha256: str | None = None,
    uri: str | None = None,
) -> Any:
    if kind not in ARTIFACT_KINDS:
        raise ToolError(f"unknown kind {kind!r}. Use one of: {', '.join(ARTIFACT_KINDS)}.")
    if kind == "link":
        if not uri:
            raise ToolError("a `link` artifact needs a `uri`.")
    elif content is None and content_b64 is None:
        raise ToolError(f"a `{kind}` artifact needs `content` (text) or `content_b64` (bytes).")
    return await state.client.publish_artifact(
        task_id,
        name=name,
        kind=kind,
        content=content,
        content_b64=content_b64,
        content_sha256=content_sha256,
        uri=uri,
    )
