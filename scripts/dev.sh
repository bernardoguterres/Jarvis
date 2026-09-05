#!/usr/bin/env bash
# Convenience launcher: runs the backend and frontend dev servers together.
# Each command remains independently runnable — see README.md.
#
# The Hermes gateway is a separate process with its own lifecycle
# (scripts/hermes-gateway.sh) and is NOT started here — Jarvis's own
# persistence and HUD must work fine whether or not Hermes is running.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! curl -s -o /dev/null -m 1 http://127.0.0.1:8642/health; then
  echo "Note: the Hermes gateway does not appear to be running." >&2
  echo "  Jarvis conversation storage still works without it — only" >&2
  echo "  'Send to Jarvis' will report Hermes as unavailable." >&2
  echo "  To start it: scripts/hermes-gateway.sh start-background" >&2
fi

cleanup() {
  kill "${BACKEND_PID:-}" "${FRONTEND_PID:-}" 2>/dev/null || true
}
trap cleanup EXIT

(cd "$ROOT_DIR/backend" && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000) &
BACKEND_PID=$!

(cd "$ROOT_DIR/frontend" && npm run dev) &
FRONTEND_PID=$!

wait
