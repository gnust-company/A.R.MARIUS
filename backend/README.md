# Armarius Backend

Clean-architecture FastAPI core for Armarius — the provisioner for cross-team agent
collaboration. See [../PROJECT_DESCRIPTION.md](../PROJECT_DESCRIPTION.md) for the design.

## Layers (`armarius/`)

| Layer | Contents | Depends on |
|---|---|---|
| `domain` | Entities, task lifecycle rules, wake policy, repo ports | nothing |
| `application` | Ports (adapter/event-bus/store/uow) + use cases (incl. WakeEngine) | `domain` |
| `infrastructure` | SQLAlchemy models/repos, adapters (Hermes/echo), event bus, store | `application`, `domain` |
| `presentation` | FastAPI routers, schemas, composition root | all |

## Run locally (SQLite, zero setup)

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"
uvicorn armarius.main:app --reload
# http://localhost:8000/docs  ·  health: /healthz
```

A demo workspace ("Settings Redesign") is seeded on first boot. Wakes use the bundled
`echo` adapter, so you can drive the full loop without a real gateway.

## Connect a real Hermes agent

Register a Marius with `adapter_type: "hermes_gateway"` and
`adapter_config: {"base_url": "http://host:8642", "api_key": "<API_SERVER_KEY>"}`.
The adapter calls `POST /v1/runs`, tees the SSE `/events` stream into the live trace +
durable run-log, and persists `{session_id, session_key}` so each (agent, task) resumes.

## Test & lint

```bash
pytest -q
ruff check armarius
```

## Key endpoints

- `POST /v1/workspaces`, `/workspaces/{id}/projects`, `/workspaces/{id}/mariuses`
- `POST /v1/projects/{id}/tasks`, `POST /v1/tasks/{id}/assign|status|wake`
- `GET  /v1/tasks/{id}/comments` · `POST` to comment (with `@mentions`)
- `GET  /v1/runs/{id}/stream` — live SSE trace · `GET /v1/runs/{id}/events` — durable trace
- `/agent/*` — agent-facing skills (bearer = per-Marius token): claim, comment, status,
  next-action, publish artifact.
