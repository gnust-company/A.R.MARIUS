"""FastMCP stdio server — registers the 9 tools and runs the JSON-RPC loop.

Thin binding layer: every tool delegates to ``tools.py`` (which holds the guardrails)
against a shared ``ServerState``. Typed signatures here are what the model sees; the
``Literal`` types make the status/kind enums self-documenting in the tool schema.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from armarius_mcp import tools
from armarius_mcp.client import ArmariusClient
from armarius_mcp.config import Config, resolve_config
from armarius_mcp.logging_setup import configure_logging, get_logger
from armarius_mcp.state import ServerState
from armarius_mcp.tools import ArtifactKind, Status

log = get_logger(__name__)


def build_server(state: ServerState) -> FastMCP:
    """Create a FastMCP instance with all tools bound to ``state``."""
    mcp: FastMCP = FastMCP(
        name="armarius",
        instructions=(
            "Armarius workspace tools. Your token was provided in the setup prompt pushed "
            "via your gateway. Start with `whoami` to confirm you're online, then `get_task` "
            "for context. Work the task you were **assigned** — you cannot take work for "
            "yourself; `request_task` asks your project Leader, and `hand_back_task` returns "
            "it with a reason or a question. Use `post_comment` (@Name wakes a teammate), "
            "`publish_artifact` before moving a task to in_review, `update_status`, and "
            "`set_next_action` before you stop. Never write curl — these tools are the whole "
            "interface."
        ),
    )

    @mcp.tool
    async def whoami() -> Any:
        """Who you are + the directory of teammates you can @mention. Marks you online."""
        return await tools.whoami(state)

    @mcp.tool
    async def get_task(task_id: str) -> Any:
        """Full task context: brief, comment thread, artifacts, and the teammate directory."""
        return await tools.get_task(state, task_id)

    @mcp.tool
    async def request_task(task_id: str, note: str | None = None) -> Any:
        """Ask your Leader to put you on a task. It decides — this assigns nothing."""
        return await tools.request_task(state, task_id, note)

    @mcp.tool
    async def hand_back_task(task_id: str, reason: str) -> Any:
        """Hand a task back, or ask a clarifying question. Your Leader is woken to read it."""
        return await tools.hand_back_task(state, task_id, reason)

    @mcp.tool
    async def post_comment(task_id: str, body: str) -> Any:
        """Post a comment on a task. Use @Name to wake a specific teammate."""
        return await tools.post_comment(state, task_id, body)

    @mcp.tool
    async def update_status(task_id: str, status: Status, reason: str | None = None) -> Any:
        """Move a task to a new status. `in_review`/`done` require a published artifact first."""
        return await tools.update_status(state, task_id, status, reason)

    @mcp.tool
    async def set_next_action(task_id: str, next_action: str | None) -> Any:
        """Record what you'll do next (or null to clear it) before you stop, so work resumes."""
        return await tools.set_next_action(state, task_id, next_action)

    @mcp.tool
    async def publish_artifact(
        task_id: str,
        name: str,
        kind: ArtifactKind = "file",
        content: str | None = None,
        content_b64: str | None = None,
        content_sha256: str | None = None,
        uri: str | None = None,
    ) -> Any:
        """Publish an artifact. file/patch/note need `content` (or `content_b64`); link needs a `uri`."""  # noqa: E501
        return await tools.publish_artifact(
            state,
            task_id,
            name,
            kind,
            content=content,
            content_b64=content_b64,
            content_sha256=content_sha256,
            uri=uri,
        )

    return mcp


def build_state(config: Config | None = None) -> ServerState:
    cfg = config or resolve_config()
    client = ArmariusClient(
        cfg.base_url, cfg.token, request_timeout=cfg.request_timeout_seconds
    )
    return ServerState(cfg, client)


def main() -> None:
    """Entry point: configure stderr logging, resolve config, run stdio."""
    configure_logging()
    state = build_state()
    log.info(
        "armarius-mcp starting: base_url=%s token=%s",
        state.config.base_url,
        "present" if state.config.has_token else "none (from setup prompt)",
    )
    server = build_server(state)
    # stdio transport by default; suppress the banner so nothing but JSON-RPC hits stdout.
    server.run(show_banner=False)


if __name__ == "__main__":
    main()
