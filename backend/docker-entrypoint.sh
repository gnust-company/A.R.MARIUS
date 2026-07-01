#!/bin/sh
# Backend container entrypoint (Sprint 6). Applies Alembic migrations on every boot
# (idempotent — `upgrade head` is a no-op once at head) before starting uvicorn, so the
# composed stack comes up schema-ready without a manual migrate step. Retries briefly
# while the DB finishes accepting connections.
set -e

echo "[entrypoint] applying alembic migrations..."
i=1
while [ "$i" -le 15 ]; do
  if alembic upgrade head; then
    echo "[entrypoint] migrations complete."
    exec "$@"
  fi
  echo "[entrypoint] db not ready, retrying in 2s ($i/15)..."
  i=$((i + 1))
  sleep 2
done

echo "[entrypoint] migrations failed after 15 attempts." >&2
exit 1
