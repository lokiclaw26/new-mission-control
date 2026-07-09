#!/bin/bash
# test_auto_execute.sh — sandboxed test harness for kanban-auto-execute.sh.
# Verifies every safety rail. Uses a fresh tempdir per test so state never
# leaks between cases.
set -u

SCRIPT="/home/nofidofi/.hermes/scripts/kanban-auto-execute.sh"
STUB_DIR="$(mktemp -d /tmp/mc-auto-exec-stub-XXXXXX)"
PROJECTS_ROOT_TEMPLATE="/tmp/mc-auto-exec-test-XXXXXX"

# Build a stub hermes once — logs every invocation to a known file.
# Note: this stub EXITS immediately. For TEST 6 (pgrep-skip) we use a
# separate sleep-stub instead, so the live process is detectable by pgrep
# long enough for the auto-execute script to inspect it.
cat > "$STUB_DIR/hermes" <<'STUB'
#!/bin/bash
echo "STUB_INVOKED at $(date +%s) pid=$$" >> "/tmp/mc-auto-exec-test-invocations.log"
STUB
chmod +x "$STUB_DIR/hermes"

# Build a SEPARATE sleep-stub for the pgrep-skip test. This one lingers
# so pgrep can find it. Crucially, its argv mimics the real subagent's:
# it embeds the literal string "kanban-auto-execute" in the prompt, which
# is exactly the case where the OLD buggy filter
# `grep -v -F "kanban-auto-execute"` would have wrongly hidden the
# subagent from pgrep.
cat > "$STUB_DIR/hermes-sleep-stub" <<'STUB2'
#!/bin/bash
# Sleep long enough for the test to pgrep us.
sleep 30
STUB2
chmod +x "$STUB_DIR/hermes-sleep-stub"

reset_invocations() {
  : > /tmp/mc-auto-exec-test-invocations.log
}

count_invocations() {
  if [ -f /tmp/mc-auto-exec-test-invocations.log ]; then
    grep -c "STUB_INVOKED" /tmp/mc-auto-exec-test-invocations.log 2>/dev/null
  else
    echo 0
  fi
}

# Create a fresh sandbox and a patched copy of the script pointed at it.
# Echoes the absolute path on stdout, format: ROOT|PROJECTS|LOGS|PAUSE|SCRIPT
setup_sandbox() {
  local root
  root="$(mktemp -d $PROJECTS_ROOT_TEMPLATE)"
  local projects="$root/01_projects/mission-control/tasks"
  local logs="$root/00_company_os/04_agents/logs"
  local pause="$root/00_company_os/04_agents/.auto-execute-paused"
  mkdir -p "$projects" "$logs" "$(dirname "$pause")"

  local patched="$root/auto-execute.sh"
  sed -e "s|^PROJECTS_ROOT=.*|PROJECTS_ROOT=\"$root\"|" \
      -e "s|^LOG_DIR=.*|LOG_DIR=\"$logs\"|" \
      -e "s|^LOG_FILE=.*|LOG_FILE=\"$logs/auto-execute.log\"|" \
      -e "s|^PAUSE_FILE=.*|PAUSE_FILE=\"$pause\"|" \
      "$SCRIPT" > "$patched"
  chmod +x "$patched"
  # TASKS_GLOB stays at $PROJECTS_ROOT/01_projects (the script's default).
  # The script's hardcoded "$TASKS_GLOB/mission-control/tasks/" then resolves
  # to $root/01_projects/mission-control/tasks/ — matching the actual task
  # dir we set up.

  echo "$root|$projects|$logs|$pause|$patched"
}

make_task() {
  # args: projects_dir id agent
  local projects="$1"; local id="$2"; local agent="$3"
  cat > "$projects/$id.md" <<EOF
---
id: $id
title: test task $id
assigned_to: $agent
status: in_progress
kanban_status: running_now
---
# test task $id
EOF
}

# Wait for any stub-hermes children to finish writing their log lines.
wait_for_stubs() {
  local waited=0
  while pgrep -f "STUB_INVOKED\|$STUB_DIR/hermes" >/dev/null 2>&1; do
    sleep 0.1
    waited=$(( waited + 1 ))
    if [ "$waited" -gt 50 ]; then break; fi  # 5s max
  done
}

PASS=0; FAIL=0
declare -a RESULTS
assert() {
  local label="$1"; local expect="$2"; local actual="$3"
  if [ "$expect" = "$actual" ]; then
    PASS=$(( PASS + 1 ))
    RESULTS+=( "PASS: $label" )
  else
    FAIL=$(( FAIL + 1 ))
    RESULTS+=( "FAIL: $label (expected $expect, got $actual)" )
  fi
}

# ============================================================
# TEST 1: Kill switch
# ============================================================
echo "=== TEST 1: kill switch ==="
IFS='|' read -r ROOT PROJECTS LOGS PAUSE PSCRIPT < <(setup_sandbox)
reset_invocations
touch "$PAUSE"
make_task "$PROJECTS" "MC-AUTO-TEST-PAUSE-1" "forge"
HERMES_BIN_OVERRIDE="$STUB_DIR/hermes" "$PSCRIPT" 2>/tmp/t1.err
EC=$?; INV=$(count_invocations); PL=$(grep -c "PAUSED" /tmp/t1.err || echo 0)
assert "T1: exit 0" "0" "$EC"
assert "T1: no dispatches" "0" "$INV"
assert "T1: PAUSED logged" "1" "$PL"
rm -rf "$ROOT"

# ============================================================
# TEST 2: 120s dedup — fresh dotfile blocks re-dispatch; 121s old allows it
# ============================================================
echo "=== TEST 2: 120s dedup ==="
IFS='|' read -r ROOT PROJECTS LOGS PAUSE PSCRIPT < <(setup_sandbox)
reset_invocations
make_task "$PROJECTS" "MC-AUTO-TEST-DEDUP-1" "forge"
touch "$PROJECTS/.executed-MC-AUTO-TEST-DEDUP-1"
HERMES_BIN_OVERRIDE="$STUB_DIR/hermes" "$PSCRIPT" 2>/tmp/t2a.err
wait_for_stubs
INV=$(count_invocations)
assert "T2a: fresh dotfile blocks dispatch" "0" "$INV"

# Move dotfile 121s into the past — should now dispatch
touch -d "121 seconds ago" "$PROJECTS/.executed-MC-AUTO-TEST-DEDUP-1"
HERMES_BIN_OVERRIDE="$STUB_DIR/hermes" "$PSCRIPT" 2>/tmp/t2b.err
wait_for_stubs
INV=$(count_invocations)
assert "T2b: 121s-old dotfile allows dispatch" "1" "$INV"
rm -rf "$ROOT"

# ============================================================
# TEST 3: Whitelist
# ============================================================
echo "=== TEST 3: whitelist (hacker rejected) ==="
IFS='|' read -r ROOT PROJECTS LOGS PAUSE PSCRIPT < <(setup_sandbox)
reset_invocations
make_task "$PROJECTS" "MC-AUTO-TEST-WL-1" "hacker"
HERMES_BIN_OVERRIDE="$STUB_DIR/hermes" "$PSCRIPT" 2>/tmp/t3.err
wait_for_stubs
INV=$(count_invocations); WARN=$(grep -c "WARN.*unsupported assignee='hacker'" /tmp/t3.err || echo 0)
assert "T3: hacker not dispatched" "0" "$INV"
assert "T3: WARN logged" "1" "$WARN"
rm -rf "$ROOT"

# ============================================================
# TEST 4: Cap-3-concurrent
# ============================================================
echo "=== TEST 4: cap-3-concurrent ==="
IFS='|' read -r ROOT PROJECTS LOGS PAUSE PSCRIPT < <(setup_sandbox)
reset_invocations
make_task "$PROJECTS" "MC-AUTO-TEST-CAP-1" "forge"
make_task "$PROJECTS" "MC-AUTO-TEST-CAP-2" "forge"
make_task "$PROJECTS" "MC-AUTO-TEST-CAP-3" "forge"
make_task "$PROJECTS" "MC-AUTO-TEST-CAP-4" "forge"
HERMES_BIN_OVERRIDE="$STUB_DIR/hermes" "$PSCRIPT" 2>/tmp/t4.err
wait_for_stubs
INV=$(count_invocations); CAP=$(grep -c "cap reached" /tmp/t4.err || echo 0)
assert "T4: exactly 3 dispatches" "3" "$INV"
assert "T4: cap-reached line present" "1" "$CAP"
rm -rf "$ROOT"

# ============================================================
# TEST 5: Per-agent rate limit (6 dispatches/agent/hour)
# ============================================================
echo "=== TEST 5: per-agent rate limit ==="
IFS='|' read -r ROOT PROJECTS LOGS PAUSE PSCRIPT < <(setup_sandbox)
: > "$LOGS/auto-execute.log"
NOW_EPOCH=$(date +%s)
for i in 1 2 3 4 5 6; do
  TS=$(TZ='Asia/Dubai' date -d "@$((NOW_EPOCH - i*10))" '+%Y-%m-%dT%H:%M:%S+04:00')
  echo "$TS  kanban-auto-execute: dispatch  MC-AUTO-RATE-PRIOR-$i  agent=forge  title='prior'  priority=low" >> "$LOGS/auto-execute.log"
done
reset_invocations
make_task "$PROJECTS" "MC-AUTO-TEST-RATE-7" "forge"
HERMES_BIN_OVERRIDE="$STUB_DIR/hermes" "$PSCRIPT" 2>/tmp/t5.err
wait_for_stubs
INV=$(count_invocations); RL=$(grep -c "skip.*agent=forge has 6 dispatches" /tmp/t5.err || echo 0)
assert "T5: 7th dispatch skipped" "0" "$INV"
assert "T5: skip message present" "1" "$RL"
rm -rf "$ROOT"

# ============================================================
# TEST 6: pgrep-skip (live subagent detected)
# ============================================================
echo "=== TEST 6: pgrep-skip (live subagent detected) ==="
IFS='|' read -r ROOT PROJECTS LOGS PAUSE PSCRIPT < <(setup_sandbox)
reset_invocations
make_task "$PROJECTS" "MC-AUTO-TEST-PGREP-1" "forge"
# Spawn a fake "hermes" whose argv contains the task_id AND the literal
# "kanban-auto-execute" string — exactly mimicking a real subagent whose
# prompt begins with "dispatched by kanban-auto-execute (Hermes cron)".
# We kill it after the test.
"$STUB_DIR/hermes-sleep-stub" -z "You are forge, dispatched by kanban-auto-execute (Hermes cron). Task: MC-AUTO-TEST-PGREP-1. Title: …" --accept-hooks --yolo > /dev/null 2>&1 &
FAKE_PID=$!
# Give pgrep a moment to see the process.
sleep 0.5
HERMES_BIN_OVERRIDE="$STUB_DIR/hermes" "$PSCRIPT" 2>/tmp/t6.err
INV=$(count_invocations); SK=$(grep -c "already executing it" /tmp/t6.err || echo 0)
kill "$FAKE_PID" 2>/dev/null || true
wait "$FAKE_PID" 2>/dev/null || true
assert "T6: pgrep skipped dispatch" "0" "$INV"
assert "T6: skip message present" "1" "$SK"
rm -rf "$ROOT"

# ============================================================
# TEST 7: Happy path
# ============================================================
echo "=== TEST 7: happy path ==="
IFS='|' read -r ROOT PROJECTS LOGS PAUSE PSCRIPT < <(setup_sandbox)
reset_invocations
make_task "$PROJECTS" "MC-AUTO-TEST-HAPPY-1" "forge"
HERMES_BIN_OVERRIDE="$STUB_DIR/hermes" "$PSCRIPT" 2>/tmp/t7.err
wait_for_stubs
INV=$(count_invocations); DOT=$([ -f "$PROJECTS/.executed-MC-AUTO-TEST-HAPPY-1" ] && echo 1 || echo 0)
assert "T7: exactly 1 dispatch" "1" "$INV"
assert "T7: dotfile created" "1" "$DOT"
rm -rf "$ROOT"

# ============================================================
echo ""
echo "=== RESULTS ==="
printf '%s\n' "${RESULTS[@]}"
echo ""
echo "PASS=$PASS FAIL=$FAIL"

# Cleanup (debug-mode: leave artifacts)
rm -f /tmp/mc-auto-exec-test-invocations.log /tmp/t*.err
rm -rf "$STUB_DIR"

if [ "$FAIL" -ne 0 ]; then exit 1; fi
exit 0