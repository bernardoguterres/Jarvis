#!/usr/bin/env bash
# Jarvis local macOS runtime controller (Phase 7).
#
# Manages exactly two Jarvis-owned things:
#   - the FastAPI backend (which also serves the production frontend build
#     from the same origin/port — see docs/ARCHITECTURE.md §8b)
#   - opening/focusing a browser window pointed at it
#
# The Hermes gateway has its own independent lifecycle (scripts/hermes-gateway.sh)
# and is only ever started here if it isn't already running — this script
# never stops it, matching the existing dev.sh convention.
#
# All state this script owns lives under $JARVIS_RUNTIME_DIR (default:
# ~/Library/Application Support/Jarvis), never under JARVIS_DATA_DIR — PID
# files, logs, and the dedicated Chrome app-mode profile are operational
# state, not personal data, and must never appear in an export/backup.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Overridable for tests/isolation — never hardcode a real path here.
JARVIS_HOME="${JARVIS_HOME:-$HOME}"
JARVIS_RUNTIME_DIR="${JARVIS_RUNTIME_DIR:-$JARVIS_HOME/Library/Application Support/Jarvis}"
JARVIS_BACKEND_PORT="${JARVIS_BACKEND_PORT:-8000}"
JARVIS_LAUNCH_AGENTS_DIR="${JARVIS_LAUNCH_AGENTS_DIR:-$JARVIS_HOME/Library/LaunchAgents}"

LAUNCH_AGENT_LABEL="com.bernardo.jarvis.launcher"
RUN_DIR="$JARVIS_RUNTIME_DIR/run"
LOG_DIR="$JARVIS_RUNTIME_DIR/logs"
CHROME_PROFILE_DIR="$JARVIS_RUNTIME_DIR/chrome-profile"
PID_FILE="$RUN_DIR/backend.pid"
LOG_FILE="$LOG_DIR/backend.log"
HEALTH_URL="http://127.0.0.1:${JARVIS_BACKEND_PORT}/api/health"
APP_URL="http://127.0.0.1:${JARVIS_BACKEND_PORT}/"

usage() {
  cat >&2 <<EOF
Usage: $0 {open|focus|status|stop|install-startup|uninstall-startup}

  open              Start Jarvis if not already running, then open/focus it.
  focus             Alias for 'open' — idempotent either way.
  status            Report backend/gateway health and PIDs.
  stop              Stop the Jarvis-owned backend process only.
  install-startup   Install a LaunchAgent to run 'open' at login (requires
                     explicit confirmation; see README.md before running).
  uninstall-startup Remove that LaunchAgent, if installed.
EOF
  exit 1
}

log() { echo "[jarvisctl] $*" >&2; }

ensure_dirs() {
  mkdir -p "$RUN_DIR" "$LOG_DIR" "$CHROME_PROFILE_DIR"
}

rotate_log_if_large() {
  # Sensible size/retention limit: one rotation, capped at 5MB.
  if [ -f "$LOG_FILE" ]; then
    local size
    size=$(stat -f%z "$LOG_FILE" 2>/dev/null || echo 0)
    if [ "$size" -gt 5242880 ]; then
      mv -f "$LOG_FILE" "$LOG_FILE.1"
    fi
  fi
}

is_backend_healthy() {
  curl -s -o /dev/null -m 2 -w "%{http_code}" "$HEALTH_URL" 2>/dev/null | grep -q "^200$"
}

# Returns 0 (true) and prints the PID if $PID_FILE names a process that is
# actually still alive AND is genuinely our uvicorn backend — never trust a
# PID file blindly (a stale/reused PID could belong to an unrelated process).
verified_running_pid() {
  [ -f "$PID_FILE" ] || return 1
  local pid
  pid=$(cat "$PID_FILE" 2>/dev/null) || return 1
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  local cmd
  cmd=$(ps -p "$pid" -o command= 2>/dev/null || true)
  case "$cmd" in
    *uvicorn*app.main:app*) echo "$pid"; return 0 ;;
    *) return 1 ;;
  esac
}

port_owner_description() {
  lsof -nP -iTCP:"$JARVIS_BACKEND_PORT" -sTCP:LISTEN 2>/dev/null || true
}

start_hermes_gateway_if_needed() {
  if curl -s -o /dev/null -m 1 http://127.0.0.1:8642/health 2>/dev/null; then
    log "Hermes gateway already running."
    return 0
  fi
  if command -v jarvis >/dev/null 2>&1; then
    log "Hermes gateway not running; starting it in the background..."
    "$ROOT_DIR/scripts/hermes-gateway.sh" start-background || true
  else
    log "Note: 'jarvis' command not found — Hermes gateway not started."
    log "  Jarvis's own storage/HUD still work; only model replies need it."
  fi
}

build_frontend() {
  log "Building the production frontend..."
  (cd "$ROOT_DIR/frontend" && npm run build) >>"$LOG_FILE" 2>&1
}

apply_migrations() {
  # Forward-only, additive, never resets/overwrites existing data — the same
  # migration path used throughout Phases 1-4. Safe and idempotent to run on
  # every start: a fully up-to-date database is a no-op.
  log "Applying database migrations (if any are pending)..."
  (cd "$ROOT_DIR/backend" && uv run alembic upgrade head) >>"$LOG_FILE" 2>&1
}

start_backend() {
  ensure_dirs
  rotate_log_if_large
  build_frontend
  apply_migrations

  log "Starting the Jarvis backend on 127.0.0.1:${JARVIS_BACKEND_PORT}..."
  (
    cd "$ROOT_DIR/backend"
    exec uv run uvicorn app.main:app --host 127.0.0.1 --port "$JARVIS_BACKEND_PORT"
  ) >>"$LOG_FILE" 2>&1 &
  local pid=$!
  echo "$pid" > "$PID_FILE"

  log "Waiting for the backend to become healthy (PID $pid)..."
  local attempt=0
  while [ "$attempt" -lt 30 ]; do
    if is_backend_healthy; then
      log "Backend is healthy."
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$PID_FILE"
      if grep -q "address already in use" "$LOG_FILE" 2>/dev/null; then
        log "ERROR: port ${JARVIS_BACKEND_PORT} is already in use by another process."
        log "  Details (best effort):"
        port_owner_description >&2 || true
        log "Stop whatever is using that port, or set JARVIS_BACKEND_PORT to a free one, and retry."
      else
        log "ERROR: backend process exited before becoming healthy. Last log lines:"
        tail -n 20 "$LOG_FILE" >&2 || true
      fi
      return 1
    fi
    sleep 0.5
    attempt=$((attempt + 1))
  done

  log "ERROR: backend did not become healthy within 15s. Last log lines:"
  tail -n 20 "$LOG_FILE" >&2 || true
  return 1
}

open_browser() {
  log "Opening Jarvis at $APP_URL ..."
  if open -na "Google Chrome" --args --app="$APP_URL" --user-data-dir="$CHROME_PROFILE_DIR" 2>/dev/null; then
    return 0
  fi
  log "Google Chrome app-mode launch failed or unavailable; opening with the default browser instead."
  open "$APP_URL"
}

cmd_open() {
  ensure_dirs

  start_hermes_gateway_if_needed

  if is_backend_healthy; then
    log "Jarvis backend already running and healthy — reusing it."
  else
    local existing_pid
    if existing_pid=$(verified_running_pid); then
      log "A verified backend process (PID $existing_pid) is running but not yet healthy; waiting..."
    elif [ -n "$(port_owner_description)" ]; then
      log "ERROR: port ${JARVIS_BACKEND_PORT} is already in use by another process, and it did not"
      log "  respond as the Jarvis backend. Not starting a duplicate. Details:"
      port_owner_description >&2
      log "Stop whatever is using that port, or set JARVIS_BACKEND_PORT to a free one, and retry."
      return 1
    else
      [ -f "$PID_FILE" ] && rm -f "$PID_FILE" # stale/unverifiable pidfile — never trusted, just cleared
      start_backend || return 1
    fi
  fi

  open_browser
}

cmd_status() {
  echo "Hermes gateway:"
  if curl -s -o /dev/null -m 1 http://127.0.0.1:8642/health 2>/dev/null; then
    echo "  running (http://127.0.0.1:8642)"
  else
    echo "  not reachable"
  fi

  echo "Jarvis backend (127.0.0.1:${JARVIS_BACKEND_PORT}):"
  if is_backend_healthy; then
    local pid
    pid=$(verified_running_pid || echo "unknown-but-healthy")
    echo "  healthy (pid: $pid)"
  else
    echo "  not healthy"
  fi

  if [ -f "$JARVIS_LAUNCH_AGENTS_DIR/$LAUNCH_AGENT_LABEL.plist" ]; then
    echo "Start-at-login: installed ($JARVIS_LAUNCH_AGENTS_DIR/$LAUNCH_AGENT_LABEL.plist)"
  else
    echo "Start-at-login: not installed"
  fi
}

cmd_stop() {
  local pid
  if pid=$(verified_running_pid); then
    log "Stopping Jarvis backend (verified PID $pid)..."
    kill "$pid"
    local attempt=0
    while kill -0 "$pid" 2>/dev/null && [ "$attempt" -lt 20 ]; do
      sleep 0.25
      attempt=$((attempt + 1))
    done
    if kill -0 "$pid" 2>/dev/null; then
      log "Process did not exit in time; leaving it running rather than force-killing."
      return 1
    fi
    rm -f "$PID_FILE"
    log "Stopped."
  else
    log "No verified Jarvis-owned backend process found running; nothing to stop."
    rm -f "$PID_FILE" 2>/dev/null || true
  fi
}

launch_agent_plist_path() {
  echo "$JARVIS_LAUNCH_AGENTS_DIR/$LAUNCH_AGENT_LABEL.plist"
}

render_launch_agent_plist() {
  # Renders the repository-owned template with this machine's absolute
  # paths substituted in — the template itself has none (see
  # macos/com.bernardo.jarvis.launcher.plist.template).
  local template="$ROOT_DIR/macos/com.bernardo.jarvis.launcher.plist.template"
  sed \
    -e "s#__JARVIS_ROOT__#$ROOT_DIR#g" \
    -e "s#__JARVIS_LOG_DIR__#$LOG_DIR#g" \
    -e "s#__JARVIS_LABEL__#$LAUNCH_AGENT_LABEL#g" \
    "$template"
}

cmd_install_startup() {
  local dest
  dest="$(launch_agent_plist_path)"
  ensure_dirs
  mkdir -p "$JARVIS_LAUNCH_AGENTS_DIR"
  render_launch_agent_plist > "$dest"
  log "Installed: $dest"
  if [ "${JARVIS_SKIP_LAUNCHCTL:-}" != "1" ]; then
    launchctl bootstrap "gui/$(id -u)" "$dest" 2>/dev/null || launchctl load "$dest" 2>/dev/null || true
  fi
  log "Jarvis will now start automatically at login for this user."
}

cmd_uninstall_startup() {
  local dest
  dest="$(launch_agent_plist_path)"
  if [ -f "$dest" ]; then
    if [ "${JARVIS_SKIP_LAUNCHCTL:-}" != "1" ]; then
      launchctl bootout "gui/$(id -u)" "$dest" 2>/dev/null || launchctl unload "$dest" 2>/dev/null || true
    fi
    rm -f "$dest"
    log "Removed: $dest"
  else
    log "Not installed; nothing to remove."
  fi
}

cmd="${1:-}"
case "$cmd" in
  open|start) cmd_open ;;
  focus) cmd_open ;;
  status) cmd_status ;;
  stop) cmd_stop ;;
  install-startup) cmd_install_startup ;;
  uninstall-startup) cmd_uninstall_startup ;;
  *) usage ;;
esac
