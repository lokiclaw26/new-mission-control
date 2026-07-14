#!/bin/bash
# start-mc.sh — Start NofiTech Mission Control in the background.
# v1.4.x — Stage 6+ (per NOFI directive, 2026-06-10).
# Usage: ./start-mc.sh
# Idempotent: refuses to start a duplicate.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PORT=8768
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/mission-control-v2.log"
PID_FILE="$LOG_DIR/mission-control-v2.pid"
URL="http://192.168.0.50:$PORT/"

mkdir -p "$LOG_DIR"

# 1. Is the PID file pointing at a live process AND port bound?
if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null || echo "")
    if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
        # Process is alive. Check if it's actually our server.
        if ss -tlnp 2>/dev/null | grep -q ":$PORT " && \
           ps -p "$OLD_PID" -o cmd= 2>/dev/null | grep -q "python3 serve.py"; then
            echo "Mission Control is already live (PID $OLD_PID) at $URL"
            exit 0
        fi
    fi
    # Stale PID file — clean it up
    rm -f "$PID_FILE"
fi

# 2. Quick port check: is something else holding 8767?
if ss -tlnp 2>/dev/null | grep -q ":$PORT "; then
    EXISTING=$(ss -tlnp 2>/dev/null | grep ":$PORT " | head -1)
    echo "ERROR: Port $PORT is already in use by another process:"
    echo "  $EXISTING"
    echo "If this is a stale binding, find and kill the holder, then retry."
    exit 1
fi

# 3. Start the server in the background using nohup
nohup python3 serve.py >> "$LOG_FILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

# 4. Wait briefly to confirm it actually bound
sleep 2
if ! kill -0 "$NEW_PID" 2>/dev/null; then
    echo "ERROR: server failed to start. Tail of $LOG_FILE:"
    tail -20 "$LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
fi

if ! ss -tlnp 2>/dev/null | grep -q ":$PORT "; then
    echo "ERROR: server started (PID $NEW_PID) but did not bind to port $PORT. Tail of log:"
    tail -20 "$LOG_FILE"
    exit 1
fi

echo "Mission Control live at $URL"
echo "PID: $NEW_PID"
echo "Log: $LOG_FILE"
