#!/usr/bin/env bash
# Automated, fully-isolated test of jarvisctl.sh's platform-independent
# behavior and safe simulation of its macOS-specific install/uninstall
# (Phase 7). Never touches the real ~/Library or ~/JarvisData — everything
# runs against a throwaway JARVIS_HOME/JARVIS_DATA_DIR/port. Safe to re-run.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TESTROOT="$(mktemp -d /tmp/jarvisctl-test.XXXXXX)"
export JARVIS_HOME="$TESTROOT/home"
export JARVIS_DATA_DIR="$TESTROOT/data"
export JARVIS_BACKEND_PORT="${JARVIS_TEST_PORT:-8123}"
export JARVIS_SKIP_LAUNCHCTL=1

PASS=0
FAIL=0

pass() { PASS=$((PASS + 1)); echo "  ok - $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL - $1"; }

cleanup() {
  "$ROOT_DIR/scripts/jarvisctl.sh" stop >/dev/null 2>&1 || true
  pkill -f "user-data-dir=$TESTROOT" >/dev/null 2>&1 || true
  sleep 1
  rm -rf "$TESTROOT" 2>/dev/null || true
}
trap cleanup EXIT

echo "=== Test 1: cold start becomes healthy ==="
if "$ROOT_DIR/scripts/jarvisctl.sh" open >"$TESTROOT/open1.log" 2>&1; then
  pass "open (cold start) exited 0"
else
  fail "open (cold start) exited non-zero"; cat "$TESTROOT/open1.log"
fi
if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${JARVIS_BACKEND_PORT}/api/health" | grep -q "^200$"; then
  pass "backend health endpoint returns 200"
else
  fail "backend health endpoint not 200"
fi

PID_FILE="$JARVIS_HOME/Library/Application Support/Jarvis/run/backend.pid"
FIRST_PID="$(cat "$PID_FILE" 2>/dev/null || echo "")"
if [ -n "$FIRST_PID" ]; then
  pass "PID file written ($FIRST_PID)"
else
  fail "PID file missing after cold start"
fi

echo "=== Test 2: repeated open is idempotent (no duplicate process) ==="
"$ROOT_DIR/scripts/jarvisctl.sh" open >"$TESTROOT/open2.log" 2>&1 || true
SECOND_PID="$(cat "$PID_FILE" 2>/dev/null || echo "")"
if [ "$FIRST_PID" = "$SECOND_PID" ] && [ -n "$SECOND_PID" ]; then
  pass "PID unchanged across repeated open ($SECOND_PID)"
else
  fail "PID changed across repeated open (first=$FIRST_PID second=$SECOND_PID) — duplicate started?"
fi
BACKEND_PROC_COUNT="$(pgrep -f "uvicorn app.main:app --host 127.0.0.1 --port ${JARVIS_BACKEND_PORT}" | wc -l | tr -d ' ')"
if [ "$BACKEND_PROC_COUNT" -le 2 ]; then
  # up to 2: the 'uv' wrapper plus the actual uvicorn/python process it execs
  pass "no duplicate backend process (found $BACKEND_PROC_COUNT matching process(es))"
else
  fail "found $BACKEND_PROC_COUNT backend-matching processes — expected at most 2"
fi

echo "=== Test 3: data persists across a stop + restart ==="
DB_PATH="$JARVIS_DATA_DIR/database/jarvis.sqlite"
BEFORE_HASH="$(shasum "$DB_PATH" | awk '{print $1}')"
"$ROOT_DIR/scripts/jarvisctl.sh" stop >"$TESTROOT/stop1.log" 2>&1 || true
if [ ! -f "$PID_FILE" ]; then
  pass "PID file removed after stop"
else
  fail "PID file still present after stop"
fi
"$ROOT_DIR/scripts/jarvisctl.sh" open >"$TESTROOT/open3.log" 2>&1 || true
if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${JARVIS_BACKEND_PORT}/api/health" | grep -q "^200$"; then
  pass "backend healthy again after restart"
else
  fail "backend not healthy after restart"
fi
AFTER_HASH="$(shasum "$DB_PATH" | awk '{print $1}')"
if [ "$BEFORE_HASH" = "$AFTER_HASH" ]; then
  pass "database file unchanged across stop/restart"
else
  fail "database file changed unexpectedly across stop/restart"
fi
"$ROOT_DIR/scripts/jarvisctl.sh" stop >/dev/null 2>&1 || true

echo "=== Test 4: an unverified/stale PID file is never trusted (stop) ==="
mkdir -p "$(dirname "$PID_FILE")"
( sleep 30 & echo $! > "$PID_FILE" )
UNRELATED_PID="$(cat "$PID_FILE")"
"$ROOT_DIR/scripts/jarvisctl.sh" stop >"$TESTROOT/stop2.log" 2>&1 || true
if kill -0 "$UNRELATED_PID" 2>/dev/null; then
  pass "unrelated process ($UNRELATED_PID) left running — stale PID correctly ignored"
  kill "$UNRELATED_PID" 2>/dev/null || true
else
  fail "unrelated process was killed — stale/unverified PID file was wrongly trusted!"
fi

echo "=== Test 5: install-startup / uninstall-startup (isolated fake HOME) ==="
"$ROOT_DIR/scripts/jarvisctl.sh" install-startup >"$TESTROOT/install.log" 2>&1 || true
PLIST_PATH="$JARVIS_HOME/Library/LaunchAgents/com.bernardo.jarvis.launcher.plist"
if [ -f "$PLIST_PATH" ]; then
  pass "LaunchAgent plist written to isolated fake LaunchAgents dir"
else
  fail "LaunchAgent plist not written"
fi
if command -v plutil >/dev/null 2>&1 && plutil -lint "$PLIST_PATH" >/dev/null 2>&1; then
  pass "rendered plist is valid (plutil -lint)"
else
  fail "rendered plist failed plutil -lint"
fi
if ! grep -q "__JARVIS_" "$PLIST_PATH"; then
  pass "no unsubstituted placeholders remain in the rendered plist"
else
  fail "unsubstituted placeholder(s) found in rendered plist"
fi
"$ROOT_DIR/scripts/jarvisctl.sh" uninstall-startup >"$TESTROOT/uninstall.log" 2>&1 || true
if [ ! -f "$PLIST_PATH" ]; then
  pass "LaunchAgent plist removed by uninstall-startup"
else
  fail "LaunchAgent plist still present after uninstall-startup"
fi

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ]
