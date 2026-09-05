#!/usr/bin/env bash
# Manage the dedicated 'jarvis' Hermes profile's local API server gateway.
# Runs manually in the foreground/background for this dev session only —
# does NOT install a persistent login-startup service (that belongs to a
# later phase). Requires the 'jarvis' wrapper (hermes -p jarvis) on PATH.
set -euo pipefail

usage() {
  echo "Usage: $0 {start|stop|health|doctor|status}"
  exit 1
}

cmd="${1:-}"

case "$cmd" in
  start)
    echo "Starting the jarvis Hermes gateway (foreground; Ctrl+C to stop)..."
    exec jarvis gateway run
    ;;
  start-background)
    echo "Starting the jarvis Hermes gateway in the background..."
    nohup jarvis gateway run > /tmp/jarvis-hermes-gateway.log 2>&1 &
    disown
    echo "Started (pid $!). Logs: /tmp/jarvis-hermes-gateway.log"
    ;;
  stop)
    jarvis gateway stop
    ;;
  status)
    jarvis gateway status
    ;;
  health)
    echo "Unauthenticated liveness check:"
    curl -s -o /dev/null -w "  GET /health -> HTTP %{http_code}\n" http://127.0.0.1:8642/health || true
    if [ -f "$(dirname "$0")/../backend/.env" ]; then
      token=$(grep '^HERMES_API_BEARER_TOKEN=' "$(dirname "$0")/../backend/.env" | cut -d= -f2-)
      if [ -n "$token" ]; then
        echo "Authenticated model check:"
        curl -s -H "Authorization: Bearer ${token}" -w "\n  GET /v1/models -> HTTP %{http_code}\n" \
          http://127.0.0.1:8642/v1/models
      fi
    fi
    ;;
  doctor)
    jarvis doctor
    ;;
  *)
    usage
    ;;
esac
