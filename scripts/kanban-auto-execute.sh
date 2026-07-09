#!/bin/bash
# kanban-auto-execute.sh — the 4th piece. Scans 01_projects/*/tasks/ for
# MC-AUTO-* files in kanban_status: running_now, then for each one that
# passes every safety rail, actually spawns a subagent (hermes -z) so the
# work is hands-off: card in kanban -> subagent dispatched -> log file.
#
# Runs every 2 minutes via Hermes cronjob.
#
# Safety rails (non-negotiable, per NOFI's standing rules):
#   1. Kill switch — respect 00_company_os/04_agents/.auto-execute-paused.
#   2. 120s dedup via .executed-<task_id> dotfile (per-task).
#   3. Whitelist: thor|forge|argus only — refuse anything else with WARN.
#   4. Skip if pgrep says the agent is already running that task.
#   5. Cap-3-concurrent: at most 3 dispatches per cron run.
#   6. Per-agent rate limit: max 6 dispatches per agent per hour (counted from
#      this very log file).
#   7. Log everything to 00_company_os/04_agents/logs/auto-execute.log
#      (one TSV-ish line per dispatch; human-readable header lines are fine).
#
# Exit codes:
#   0 = success (or no work to do; stays quiet on idle so cron stays silent)
#   (no non-zero exits: this script is the safety net — it must NEVER block
#    the cron on a single bad task.)
#
# Spawn pattern:
#   nohup hermes -z "<prompt>" --accept-hooks >> "<log>.<task>.out" 2>&1 &
#   The shell-out keeps the cron tick fast (one tick = one scan, not one
#   multi-minute wait). The dedup dotfile + the pgrep skip stop re-spawning
#   a task whose subagent is still in flight.
#
# MC-AUTO-EXECUTE-1 (2026-06-18): new script — the "running_now is a lie" fix.

set -u  # no -e: one bad task must not crash the loop.

# ---- Paths -----------------------------------------------------------------
PROJECTS_ROOT="/home/nofidofi/NofiTech-Ind"
TASKS_GLOB="$PROJECTS_ROOT/01_projects"
LOG_DIR="$PROJECTS_ROOT/00_company_os/04_agents/logs"
LOG_FILE="$LOG_DIR/auto-execute.log"
PAUSE_FILE="$PROJECTS_ROOT/00_company_os/04_agents/.auto-execute-paused"

NOW_TS_ISO="$(TZ='Asia/Dubai' date '+%Y-%m-%dT%H:%M:%S+04:00')"
NOW_EPOCH="$(date +%s)"

# ---- Safety rail knobs ------------------------------------------------------
ALLOWED_AGENTS="thor|forge|argus"
DEDUP_WINDOW_SEC=120
MAX_CONCURRENT_DISPATCHES=3
RATE_LIMIT_WINDOW_SEC=3600       # 1 hour
RATE_LIMIT_MAX_PER_AGENT=6
HERMES_BIN="${HERMES_BIN_OVERRIDE:-$(command -v hermes)}"

mkdir -p "$LOG_DIR" 2>/dev/null || true

log() {
  # stderr so stdout stays empty when there's nothing to dispatch.
  echo "kanban-auto-execute: $*" >&2
}

# ---- Rail 1: kill switch ----------------------------------------------------
if [ -f "$PAUSE_FILE" ]; then
  log "PAUSED — $PAUSE_FILE exists. NOFI has paused auto-execute. Exiting 0."
  exit 0
fi

# ---- Sanity: hermes binary present ------------------------------------------
if [ -z "$HERMES_BIN" ] || [ ! -x "$HERMES_BIN" ]; then
  log "ERROR: hermes binary not found on PATH — cannot dispatch subagents."
  exit 0
fi

# ---- Find running_now tasks (Format A frontmatter) -------------------------
# We pick up BOTH `MC-AUTO-*` (auto-dispatch children, normal path) AND
# `MC-KANBAN-CREATE-*` (UI-created tasks that the auto-process cron moved
# to running_now but never spawned an MC-AUTO-* child for). The original
# spec only matched `MC-AUTO-*` which left user-created tasks permanently
# stuck in running_now — NOFI caught that. Format A only; the grep is
# anchored to ^kanban_status: so it never matches body prose. `-l` keeps
# the output to file paths only.
TASKS_ALL=$(find "$TASKS_GLOB" -path "*/tasks/*" \
  \( -name "MC-AUTO-*.md" -o -name "MC-KANBAN-CREATE-*.md" \) -type f \
  -exec grep -l "^kanban_status: running_now" {} \; 2>/dev/null | sort -u || true)

# Filter out any "done" or "blocked" siblings — defensive. The frontmatter
# is the source of truth.
TASKS_ALL=$(echo "$TASKS_ALL" | grep -v '^$' || true)

if [ -z "$TASKS_ALL" ]; then
  log "no running_now MC-AUTO-* / MC-KANBAN-CREATE-* tasks at $NOW_TS_ISO"
  exit 0
fi

# ---- Helpers ---------------------------------------------------------------

# Count this agent's dispatches within the last hour from the log file.
# Each dispatch line is the canonical "kanban-auto-execute: dispatch ..."
# form, tagged with assignee=foo. We only trust lines we wrote.
count_dispatches_recent() {
  local agent="$1"
  local cutoff_epoch=$(( NOW_EPOCH - RATE_LIMIT_WINDOW_SEC ))
  # The log lines we wrote look like:
  #   2026-06-18T02:09:30+04:00  kanban-auto-execute: dispatch  MC-AUTO-...  agent=forge  title=...
  # We don't have a real epoch stamp in there, so we re-derive it from the
  # leading ISO timestamp (TZ=Asia/Dubai, +04:00). Pure bash + date:
  awk -v cutoff="$cutoff_epoch" -v agent="$agent" '
    {
      # line[0] is the ISO ts; we use mktime() so we need GNU awk.
      ts = $1
      gsub(/\+04:00/, "", ts)
      # mktime parses "YYYY MM DD HH MM SS" — split on T and -/:
      n = split(ts, a, /[-T:]/)
      if (n < 6) next
      Y = a[1]; M = a[2]; D = a[3]; h = a[4]; m = a[5]; s = a[6]
      epoch = mktime(sprintf("%d %d %d %d %d %d", Y, M, D, h, m, s))
      if (epoch < cutoff) next
      if (index($0, "agent=" agent " ") || index($0, "agent=" agent "\t") || $0 ~ ("agent=" agent "[[:space:]]*$")) {
        c++
      }
    }
    END { print c+0 }
  ' "$LOG_FILE" 2>/dev/null || echo 0
}

# Check if any process is currently running this task. The pgrep pattern
# matches our own `hermes -z` invocation (the prompt embeds the task_id)
# and any "hermes chat" the user kicked off.
#
# IMPORTANT — what we filter OUT:
#   * The current shell $$ — so the script's own short-lived bash process
#     (whose argv contains the task_id as we scan) doesn't false-positive.
#     The subagent process is a SEPARATE pid from this script's bash, so
#     this is safe.
#
# What we DO NOT filter:
#   * "kanban-auto-execute" — this string appears in the subagent's OWN
#     prompt ("dispatched by kanban-auto-execute (Hermes cron) at …"), so
#     filtering by it would mask the very process we want to detect. Earlier
#     revisions did this wrong; fixing here.
#   * The user's own `hermes chat` sessions — those legitimately matter too.
is_agent_running_task() {
  local task_id="$1"
  # Quotes around the task_id prevent shell globbing against whatever the
  # user named the card. pgrep -af returns "PID cmdline" lines; the final
  # grep -q . returns success iff at least one surviving match remains.
  pgrep -af "hermes" 2>/dev/null \
    | grep -F " $task_id" 2>/dev/null \
    | awk -v selfpid="$$" '$1 != selfpid' \
    | grep -q . && return 0
  return 1
}

DISPATCHED_COUNT=0
SKIPPED_DEDUP=0
SKIPPED_PGREP=0
SKIPPED_AGENT=0
SKIPPED_RATELIMIT=0
SCANNED=0

for task_file in $TASKS_ALL; do
  SCANNED=$(( SCANNED + 1 ))

  task_id="$(basename "$task_file" .md)"
  dotfile="$TASKS_GLOB/mission-control/tasks/.executed-$task_id"

  # ---- Cap-3-concurrent: stop after 3 dispatches in this run ---------------
  if [ "$DISPATCHED_COUNT" -ge "$MAX_CONCURRENT_DISPATCHES" ]; then
    log "cap reached (max=$MAX_CONCURRENT_DISPATCHES dispatched this run); leaving $task_id for next tick"
    break
  fi

  # ---- Rail 2: 120s dedup via dotfile -------------------------------------
  if [ -f "$dotfile" ]; then
    last_epoch=$(stat -c %Y "$dotfile" 2>/dev/null || echo 0)
    age=$(( NOW_EPOCH - last_epoch ))
    if [ "$age" -lt "$DEDUP_WINDOW_SEC" ]; then
      log "skip $task_id (executed ${age}s ago, dedup window=${DEDUP_WINDOW_SEC}s)"
      SKIPPED_DEDUP=$(( SKIPPED_DEDUP + 1 ))
      continue
    fi
  fi

  # ---- Extract frontmatter fields via python -----------------------------
  EXTRACT_OUT="$(TASK_FILE="$task_file" python3 <<'PYEOF'
import os, re, sys
task_file = os.environ['TASK_FILE']
try:
    with open(task_file) as f:
        text = f.read()
except Exception:
    print("__ERR__|__ERR__|__ERR__")
    sys.exit(0)
m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
if not m:
    print("__ERR__|__ERR__|__ERR__")
    sys.exit(0)
fm = m.group(1)
def field(k):
    mm = re.search(rf"^{re.escape(k)}\s*:\s*(.+?)\s*$", fm, re.MULTILINE)
    return mm.group(1).strip().strip('"').strip("'") if mm else ""
title = field("title")
agent = field("assigned_to").lower()
priority = field("priority") or "normal"
# sentinel for missing
if not agent:
    agent = "__NONE__"
if not title:
    title = "__NONE__"
# title may contain pipes — use a delimiter that's vanishingly unlikely
print(f"{title}||{agent}||{priority}")
PYEOF
)"

  PRIORITY="${EXTRACT_OUT##*||*||}"
  REM="${EXTRACT_OUT%||*}"
  AGENT="${REM##*||}"
  TITLE="${REM%||*}"

  # ---- Rail 3: whitelist -------------------------------------------------
  case "$AGENT" in
    thor|forge|argus) ;;
    __NONE__) log "skip $task_id (no assigned_to)"; SKIPPED_AGENT=$(( SKIPPED_AGENT + 1 )); continue ;;
    *) log "WARN $task_id has unsupported assignee='$AGENT' — skipping"; SKIPPED_AGENT=$(( SKIPPED_AGENT + 1 )); continue ;;
  esac

  if [ "$TITLE" = "__NONE__" ] || [ -z "$TITLE" ]; then
    log "WARN $task_id has no title — skipping"
    SKIPPED_AGENT=$(( SKIPPED_AGENT + 1 ))
    continue
  fi

  # ---- Rail 4: per-agent rate limit (max 6/agent/hour) --------------------
  RECENT=$(count_dispatches_recent "$AGENT")
  if [ "$RECENT" -ge "$RATE_LIMIT_MAX_PER_AGENT" ]; then
    log "skip $task_id — agent=$AGENT has $RECENT dispatches in the last hour (limit=$RATE_LIMIT_MAX_PER_AGENT)"
    SKIPPED_RATELIMIT=$(( SKIPPED_RATELIMIT + 1 ))
    continue
  fi

  # ---- Rail 5: skip if pgrep says an agent is already running that task ---
  if is_agent_running_task "$task_id"; then
    log "skip $task_id — an agent is already executing it (pgrep match)"
    SKIPPED_PGREP=$(( SKIPPED_PGREP + 1 ))
    continue
  fi

  # ---- Build the prompt for the subagent ----------------------------------
  # Read body (everything after the closing --- of frontmatter)
  BODY="$(python3 - "$task_file" <<'PYEOF'
import sys, re
try:
    with open(sys.argv[1]) as f:
        text = f.read()
except Exception:
    print("")
    raise SystemExit
m = re.match(r"^---\s*\n.*?\n---\s*\n(.*)$", text, re.DOTALL)
print(m.group(1) if m else "")
PYEOF
)"

  # Pull out an "## Acceptance" section if present
  ACCEPTANCE="$(printf '%s' "$BODY" | awk '
    /^##[ ]*Acceptance/ { flag=1; next }
    /^##[ ]/ { if (flag) { flag=0 } }
    flag { print }
  ' | head -c 4000)"

  # Log dispatch line first (so a crash here still leaves a trail)
  LOG_LINE="$NOW_TS_ISO  kanban-auto-execute: dispatch  $task_id  agent=$AGENT  title='$TITLE'  priority=$PRIORITY"
  echo "$LOG_LINE" >> "$LOG_FILE" 2>/dev/null || true

  # Mark dedup dotfile BEFORE spawning so a fast re-tick never re-dispatches
  touch "$dotfile" 2>/dev/null || true

  # ---- LLM Guard (MC-LLM-BURN-FIX-1) --------------------------------------
  # Verify the LLM call is allowed: must have a real card_id and a non-idle
  # reason. If blocked, skip the spawn and log the rejection — this prevents
  # accidental token burn from runaway cron ticks.
  GUARD_RESULT="$(printf '{"trigger":"cron","reason":"execute","card_id":"%s","job_id":""}\n' "$task_id" \
    | python3 /home/nofidofi/NofiTech-Ind/00_company_os/llm_guard.py check 2>&1)"
  GUARD_RC=$?
  if [ "$GUARD_RC" -ne 0 ]; then
    log "guard BLOCKED spawn of $task_id: $GUARD_RESULT"
    SKIPPED_GUARD=$(( ${SKIPPED_GUARD:-0} + 1 ))
    continue
  fi

  # ---- Spawn the subagent in the background -------------------------------
  # We shell out to `hermes -z` with --accept-hooks --yolo so the unattended
  # subagent doesn't get blocked on a TTY prompt. Stdout+stderr go to a
  # per-task log so the parent cron tick stays fast and quiet.
  SUB_LOG="$LOG_DIR/auto-execute-${task_id}.$(date +%s).out"
  SPAWN_TS="$(TZ='Asia/Dubai' date +%Y-%m-%dT%H:%M:%S+04:00)"
  PROMPT=$(cat <<EOF
You are $AGENT, dispatched by kanban-auto-execute (Hermes cron) at $NOW_TS_ISO (Dubai). Task: $task_id.

Title: $TITLE

Body (verbatim from task file at $task_file):
$BODY

Acceptance (extracted from the task file's "## Acceptance" section, if present):
$ACCEPTANCE

Process:
1. Read the full task file at $task_file for full context.
2. Do the work described there.
3. Write a log file to 00_company_os/04_agents/logs/$(TZ='Asia/Dubai' date +%Y-%m-%d)/$AGENT-$task_id.md with what you did + a "result: success|blocked" line.
4. PATCH the task to status=done via: PATCH http://127.0.0.1:8767/api/data/kanban/task/$task_id with body {"status":"done","kanban_status":"done"} and the X-MC-Admin-Token header (read from /home/nofidofi/.hermes/scripts/.env.mc if needed).
5. If you cannot complete, PATCH to status=blocked with a blocker reason in the body.
6. Append a one-liner to 00_company_os/events.jsonl with event_type=task_completed (or task_blocked) and task_id=$task_id.

You have 15 minutes. If you need more, write a heartbeat log entry and continue. NOFI is asleep / AFK; do not ask for input.
EOF
)

  # Background it. nohup is unnecessary because the cron ticks in a fresh
  # shell each time, but `disown` is harmless and signals intent. The
  # redirect to a per-task file means a runaway subagent can't fill the
  # main log.
  nohup "$HERMES_BIN" -z "$PROMPT" --accept-hooks --yolo \
    >> "$SUB_LOG" 2>&1 < /dev/null &
  SUBPID=$!
  disown $SUBPID 2>/dev/null || true

  log "dispatched $task_id → $AGENT  (subagent pid=$SUBPID, log=$SUB_LOG)"
  DISPATCHED_COUNT=$(( DISPATCHED_COUNT + 1 ))

  # ---- Audit log (MC-LLM-BURN-FIX-1) --------------------------------------
  # Record the LLM spawn for downstream analysis. Best-effort — never breaks
  # the dispatch path if logging fails. llm_guard.py writes directly to
  # /home/nofidofi/NofiTech-Ind/00_company_os/logs/llm-calls.jsonl.
  printf '{"agent":"%s","provider":"minimax","model":"MiniMax-M3","trigger":"cron","reason":"execute","card_id":"%s","job_id":"","user_message_id":"","input_tokens":null,"output_tokens":null,"status":"spawned","spawn_ts":"%s","spawn_pid":%s,"sub_log":"%s","guard_passed":true}\n' \
    "$AGENT" "$task_id" "$SPAWN_TS" "$SUBPID" "$SUB_LOG" \
    | python3 /home/nofidofi/NofiTech-Ind/00_company_os/llm_guard.py log \
    > /dev/null 2>&1 || true
done

log "done. scanned=$SCANNED dispatched=$DISPATCHED_COUNT skipped(dedup)=$SKIPPED_DEDUP skipped(pgrep)=$SKIPPED_PGREP skipped(agent)=$SKIPPED_AGENT skipped(ratelimit)=$SKIPPED_RATELIMIT skipped(guard)=${SKIPPED_GUARD:-0}"
exit 0
