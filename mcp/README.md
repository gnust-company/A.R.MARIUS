# armarius-mcp

An [MCP](https://modelcontextprotocol.io) **stdio** server that exposes the Armarius
agent API (`/agent/*`) as typed tools, so an onboarded agent works the workspace by
calling tools — **never by hand-writing `curl`**.

It is a thin **HTTP client** of a running Armarius backend. Each tool maps 1:1 to an
existing `/agent/*` endpoint; the server injects the bearer token and constrains
arguments (status enum, artifact kinds), so weak models can't malform a request.

```
Agent runtime  ──MCP (stdio)──►  armarius-mcp  ──HTTP + Bearer──►  Armarius backend
(Claude Code)   typed tools       (this pkg)      /agent/* calls      (FastAPI)
```

## Install

```bash
uv tool install armarius-mcp        # or: pipx install armarius-mcp
# dev, from a checkout:
uv run --directory mcp armarius-mcp
```

## Register with an MCP client

Claude Code / any `mcpServers` config:

```json
{
  "mcpServers": {
    "armarius": {
      "command": "armarius-mcp",
      "env": {
        "ARMARIUS_PUBLIC_BASE_URL": "http://localhost:8080",
        "ARMARIUS_CREDENTIAL_FILE": "~/.armarius/tokens/acme_marin.json"
      }
    }
  }
}
```

## Configuration

Resolved at startup (`resolve_config`), highest precedence first:

| What | Sources (first wins) |
|---|---|
| token | `ARMARIUS_AGENT_TOKEN` → credential file `agent_token` → *(none)* |
| base URL | `ARMARIUS_PUBLIC_BASE_URL` → credential file `api_base_url` → `GET /v1/meta` probe → `http://localhost:8080` |
| credential file | `ARMARIUS_CREDENTIAL_FILE` → single glob match of `~/.armarius/tokens/*_*.json` |

Under operator-invite (issue #63) the agent receives its token in the one-time setup
prompt Armarius pushes via its gateway — it saves that token to its credential file
(or `ARMARIUS_AGENT_TOKEN`) and the server picks it up at startup. There is no
`enroll`/`claim` bootstrap anymore (issue #64). If no token is found the server still
starts; token-required tools return a clear "save the token from your setup prompt"
error.

## Tools

`whoami`, `get_task`, `claim_task`, `post_comment`, `update_status`,
`set_next_action`, `publish_artifact`.

## Develop

```bash
cd mcp
uv sync --extra dev
uv run ruff check .
uv run pytest                 # unit tests
uv run pytest -m integration  # in-process against the real backend
```

Logs go to **stderr** only — stdout is the JSON-RPC transport.
