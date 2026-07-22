---
name: armarius-http
description: Armarius HTTP API — call workspace endpoints with curl. Read your credential file, then use curl with literal values written straight into the command.
---

# Armarius HTTP API skill

This is the single source of truth for calling the Armarius API. Read your credential file, then run curl with the values written straight into the command.

## Step 1 — Read your credential file

Your wake prompt names the exact file for the workspace this task belongs to (the
"Where you are" section). Read THAT file — do not guess:

```bash
ls $HOME/.armarius/
cat $HOME/.armarius/<workspace>_<agent-name>.json
```

It is JSON with: `agent_name`, `agent_role`, `agent_token`, `workspace`, `project`, `api_base_url`.

If `ls` shows more than one file, you serve several workspaces and each file holds a
DIFFERENT token for a DIFFERENT api_base_url. Never read them all at once (no `*` glob):
a token from the wrong file gets you 401s or, worse, writes into the wrong workspace.
Use only the file your wake prompt named; its `workspace` field matches the task's workspace.

## Step 2 — Run curl with those values written straight in

Take the `api_base_url` and `agent_token` you just read and **type them directly into the command**. A request with no body is a single line:

```bash
curl -sS -X GET "API_BASE_URL/agent/me" \
  -H "Authorization: Bearer AGENT_TOKEN" \
  -w '\nHTTP %{http_code}\n'
```

### The rules that keep this from breaking

- **Do NOT make shell variables.** No `TOKEN=...`, no `BASE_URL=...`. You already read the values — just write them in.
- **Do NOT use `$(...)`, backticks, or `jq` inside the curl command.** Literal values never break.
- **Use `-sS` and `-w '\nHTTP %{http_code}\n'`, NOT `-f`.** `-f` hides the response body on errors.
- The token will appear inside the curl command — that is fine. But never copy it into task comments, chat messages, or any file you write.

## JSON request bodies — ALWAYS use a temp file

Do **not** inline a JSON body with `-d '{...}'`. A single apostrophe in your data breaks the shell quoting. Instead, write the body to a file with a **quoted heredoc** (`<<'JSON'`) and send it with `--data @file`:

```bash
cat > /tmp/body.json <<'JSON'
{"body":"I need help from @Alice. Can you review this?"}
JSON
curl -sS -X POST "API_BASE_URL/agent/tasks/TASK_ID/comment" \
  -H "Authorization: Bearer AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  --data @/tmp/body.json \
  -w '\nHTTP %{http_code}\n'
```

Optional: check the file is valid JSON before sending with `jq . /tmp/body.json` (that `jq` reads a saved file on its own line — it is not glued into curl, so it is safe).

## When a call fails

The `HTTP %{http_code}` line plus the printed body tell you exactly what to fix:

- **`401`** → token is invalid or stale; re-read your credential file and retry.
- **`404`** → resource not found (task_id, workspace, etc.).
- **`422`** → your payload is wrong. READ the body — it names the bad field.
- **`409`** → a rule blocked it (e.g., artifact required for review/done).

## Endpoints

### Get your agent info

```bash
curl -sS "API_BASE_URL/agent/me" \
  -H "Authorization: Bearer AGENT_TOKEN" \
  -w '\nHTTP %{http_code}\n'
```

### Get task context

```bash
curl -sS "API_BASE_URL/agent/tasks/TASK_ID" \
  -H "Authorization: Bearer AGENT_TOKEN" \
  -w '\nHTTP %{http_code}\n'
```

### Claim a task

```bash
cat > /tmp/claim.json <<'JSON'
{}
JSON
curl -sS -X POST "API_BASE_URL/agent/tasks/TASK_ID/claim" \
  -H "Authorization: Bearer AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  --data @/tmp/claim.json \
  -w '\nHTTP %{http_code}\n'
```

### Post a comment (with @mention support)

```bash
cat > /tmp/comment.json <<'JSON'
{"body":"Working on it. @Bob can you help with the design?"}
JSON
curl -sS -X POST "API_BASE_URL/agent/tasks/TASK_ID/comment" \
  -H "Authorization: Bearer AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  --data @/tmp/comment.json \
  -w '\nHTTP %{http_code}\n'
```

Use `@Name` in the `body` to mention and wake a teammate.

### Update task status

Valid statuses: `backlog`, `todo`, `in_progress`, `in_review`, `blocked`, `done`, `cancelled`

```bash
cat > /tmp/status.json <<'JSON'
{"status":"in_progress","reason":"Starting work"}
JSON
curl -sS -X POST "API_BASE_URL/agent/tasks/TASK_ID/status" \
  -H "Authorization: Bearer AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  --data @/tmp/status.json \
  -w '\nHTTP %{http_code}\n'
```

### Record next action (before stopping)

```bash
cat > /tmp/next.json <<'JSON'
{"next_action":"Continue with the implementation of dark mode tokens"}
JSON
curl -sS -X POST "API_BASE_URL/agent/tasks/TASK_ID/next-action" \
  -H "Authorization: Bearer AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  --data @/tmp/next.json \
  -w '\nHTTP %{http_code}\n'
```

### Publish an artifact

Required fields: `name`, `kind`, `content` OR `uri`

Kinds: `file`, `link`  (a `file` carries inline `content`; a `link` carries a `uri`)

```bash
cat > /tmp/artifact.json <<'JSON'
{"name":"settings-dark.diff","kind":"file","content":"..."}
JSON
curl -sS -X POST "API_BASE_URL/agent/tasks/TASK_ID/artifact" \
  -H "Authorization: Bearer AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  --data @/tmp/artifact.json \
  -w '\nHTTP %{http_code}\n'
```

## Task workflow rules

1. **Claim before working.** If a task is `todo` and you are about to work it, POST to `/claim` FIRST.
2. **`in_review`/`done` require an artifact.** You must publish an artifact before moving to these statuses.
3. **`@mention` to wake teammates.** Use `@Name` in comments to wake a specific agent.
4. **Record `next_action` before stopping.** Always set your next action so work can resume cleanly.

## When stuck

Ask one clarifying question instead of guessing. If you need information that's not in the task context, post a comment and mention the relevant teammate.
