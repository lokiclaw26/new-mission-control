#!/bin/bash
# kanban-auto-dispatch.sh — actually spawn agent work for tasks in kanban_status: ready
# Runs every 60s via Hermes cronjob (NOT system crontab).
#
# For each task with `kanban_status: ready`:
#   1. Skip if assignee missing/blank, or .dispatched-<task_id> dotfile is <60s old.
#   2. Call python ondemand.dispatch() to create a real MC-AUTO-* child task and
#      PATCH the child to running_now.
#   3. Update the ORIGINAL (parent) task file's frontmatter to
#      `kanban_status: running_now` so the next scan sees it as no longer ready
#      (otherwise the cron re-dispatches the same card every minute).
#   4. Touch the dotfile for dedup.
#   5. Append one line to 00_company_os/04_agents/logs/auto-dispatch.log.
#
# Exit codes:
#   0 = success (or no tasks to dispatch; same shape so the cron stays quiet on idle)
#
# MC-AUTO-DISPATCH-1 (2026-06-18): new script — the "running_now is a lie" fix.

set -u  # NOTE: no -e. We want one bad task to NOT crash the loop.

PROJECTS_ROOT="/home/nofidofi/NofiTech-Ind"
TASKS_DIR="$PROJECTS_ROOT/01_projects/mission-control/tasks"
MISSION_CODE="$PROJECTS_ROOT/01_projects/mission-control/code"
LOG_DIR="$PROJECTS_ROOT/00_company_os/04_agents/logs"
LOG_FILE="$LOG_DIR/auto-dispatch.log"
NOW_TS_ISO="$(TZ='Asia/Dubai' date '+%Y-%m-%dT%H:%M:%S+04:00')"
NOW_EPOCH="$(date +%s)"

mkdir -p "$LOG_DIR" 2>/dev/null || true

log() {
  # log to stderr (so stdout stays empty when there's nothing to dispatch — watchdog-friendly)
  echo "kanban-auto-dispatch: $*" >&2
}

# ---- Find ready tasks (Format A + Format B) -----------------------------
TASKS_A=$(find "$PROJECTS_ROOT/01_projects" -name "*.md" -path "*/tasks/*" -exec grep -l "^kanban_status: ready" {} \; 2>/dev/null || true)
TASKS_B=$(find "$PROJECTS_ROOT/01_projects" -name "*.md" -path "*/tasks/*" -exec grep -l "^| \*\*kanban_status\*\* | ready |" {} \; 2>/dev/null || true)

TASKS_ALL=$(printf "%s\n%s\n" "$TASKS_A" "$TASKS_B" | sort -u | grep -v '^$' || true)

if [ -z "$TASKS_ALL" ]; then
  # Idle: stay quiet on stdout, log a heartbeat to stderr so cron-debug works
  log "no ready tasks at $NOW_TS_ISO"
  exit 0
fi

DISPATCHED_COUNT=0

for task_file in $TASKS_ALL; do
  task_id=$(basename "$task_file" .md)
  dotfile="$TASKS_DIR/.dispatched-$task_id"

  # ---- Dedup: skip if dispatched within last 60s --------------------------
  if [ -f "$dotfile" ]; then
    last_epoch=$(stat -c %Y "$dotfile" 2>/dev/null || echo 0)
    age=$(( NOW_EPOCH - last_epoch ))
    if [ "$age" -lt 60 ]; then
      log "skip $task_id (dispatched ${age}s ago, dedup window=60s)"
      continue
    fi
  fi

  # ---- Extract fields (python handles both frontmatter formats) ----------
  # Use | separator because titles can contain spaces. __NONE__ sentinel means
  # assigned_to was absent.
  EXTRACT_OUT="$(TASK_FILE="$task_file" python3 <<'PYEOF'
import os, re, sys

task_file = os.environ['TASK_FILE']
try:
    with open(task_file) as f:
        text = f.read()
except Exception:
    print("|||normal")
    sys.exit(0)

def fm_field(text, key):
    """Extract `key: value` from YAML frontmatter (None if absent)."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return None
    fm = m.group(1)
    mm = re.search(rf"^{re.escape(key)}\s*:\s*(.+?)\s*$", fm, re.MULTILINE)
    return mm.group(1).strip().strip('"').strip("'") if mm else None

def table_field(text, key):
    """Extract `| **key** | value |` row (None if absent)."""
    mm = re.search(rf"^\|\s*\*\*{re.escape(key)}\*\*\s*\|\s*(.+?)\s*\|\s*$", text, re.MULTILINE)
    return mm.group(1).strip().strip('"').strip("'") if mm else None

# title: use explicit `title:` then `id:` then filename
title_raw = fm_field(text, "title") if text.lstrip().startswith("---") else table_field(text, "title")
if not title_raw:
    title_raw = fm_field(text, "id") if text.lstrip().startswith("---") else None

# assigned_to: ONLY the assigned_to field — must not fall through to priority
if text.lstrip().startswith("---"):
    assignee_raw = fm_field(text, "assigned_to")
    priority_raw = fm_field(text, "priority")
else:
    assignee_raw = table_field(text, "assigned_to")
    priority_raw = table_field(text, "priority")

# Use a sentinel so the bash side can detect missing assignee cleanly
title = (title_raw or "").replace("\n", " ").replace("\r", " ").strip()
assignee = (assignee_raw or "").replace("\n", " ").replace("\r", " ").strip().lower()
priority = (priority_raw or "normal").replace("\n", " ").replace("\r", " ").strip().lower() or "normal"
# Sentinel for missing assignee
if not assignee:
    assignee = "__NONE__"

print(f"{title}|{assignee}|{priority}")
PYEOF
)"
  # Split on the LAST two pipes (priority may contain |). Title is everything before first |.
  # Priority is after the last |. Assignee is between.
  PRIORITY="${EXTRACT_OUT##*|}"
  REM="${EXTRACT_OUT%|*}"
  ASSIGNEE="${REM##*|}"
  TITLE="${REM%|*}"

  # ---- Skip if no assignee -----------------------------------------------
  if [ -z "$ASSIGNEE" ] || [ "$ASSIGNEE" = "-" ] || [ "$ASSIGNEE" = "—" ] || [ "$ASSIGNEE" = "__none__" ]; then
    log "WARN $task_id has no assigned_to — skipping"
    continue
  fi

  # ---- Skip non-allow-listed assignees (defense-in-depth) ----------------
  case "$ASSIGNEE" in
    thor|forge|argus) ;;
    *) log "WARN $task_id has unsupported assignee='$ASSIGNEE' — skipping"; continue ;;
  esac

  # ---- Skip if title is empty (refuse to dispatch a blank topic) ---------
  if [ -z "$TITLE" ]; then
    log "WARN $task_id has no title — skipping"
    continue
  fi

  log "dispatching $task_id → $ASSIGNEE  title='$TITLE' priority=$PRIORITY"

  # ---- Call python ondemand.dispatch() -----------------------------------
  # Pass via env vars (cleanest) to avoid quote-injection. The python module
  # will create a MC-AUTO-* child task, PATCH the original to running_now,
  # and append events.jsonl entries.
  RESULT=$(cd "$MISSION_CODE" && TITLE="$TITLE" ASSIGNEE="$ASSIGNEE" PRIORITY="$PRIORITY" python3 <<'PYEOF' 2>&1
import json, os, sys
try:
    from ondemand import dispatch
    tid, path = dispatch(
        topic=os.environ["TITLE"],
        agent=os.environ["ASSIGNEE"],
        source="auto-dispatch",
        priority=os.environ.get("PRIORITY", "normal"),
    )
    print(json.dumps({"ok": True, "task_id": tid, "path": str(path)}))
except Exception as e:
    print(json.dumps({"ok": False, "error": str(e)}))
PYEOF
)

  # Parse result
  OK=$(echo "$RESULT" | grep -oE '"ok":\s*true' || true)
  if [ -n "$OK" ]; then
    NEW_TASK_ID=$(echo "$RESULT" | python3 -c "import sys, json; print(json.loads(sys.stdin.read()).get('task_id', ''))" 2>/dev/null || echo "")
    DISPATCHED_COUNT=$(( DISPATCHED_COUNT + 1 ))

    # ---- MC-AUTO-DISPATCH-1 patch: update the parent task's frontmatter ----
    # ondemand.dispatch() creates a NEW MC-AUTO-* child task and patches the
    # CHILD to running_now, but the PARENT task file on disk still has
    # kanban_status: ready. Without updating the parent, the NEXT cron run
    # re-dispatches the same task every minute (and the 60s dotfile dedup is
    # the only thing stopping a loop). Fix: write kanban_status: running_now
    # directly into the parent task file's frontmatter so the next scan sees
    # it as no longer ready. This is the same format the parser reads.
    python3 - "$task_file" "$ASSIGNEE" "$NEW_TASK_ID" <<'PYEOF' || true
import re, sys
path, assignee, child_id = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    with open(path) as f:
        text = f.read()
except Exception:
    sys.exit(0)
# Format A frontmatter: replace or insert kanban_status: running_now
if text.lstrip().startswith("---"):
    m = re.match(r"^(---\s*\n)(.*?)(\n---\s*\n)(.*)$", text, re.DOTALL)
    if m:
        head, fm, sep, body = m.group(1), m.group(2), m.group(3), m.group(4)
        if re.search(r"^kanban_status\s*:", fm, flags=re.MULTILINE):
            fm2 = re.sub(r"^kanban_status\s*:.*$", "kanban_status: running_now", fm, count=1, flags=re.MULTILINE)
        else:
            # Insert after status: line if present, else after task_id:, else append
            if re.search(r"^status\s*:", fm, flags=re.MULTILINE):
                fm2 = re.sub(r"^(status:.*)$", r"\1\nkanban_status: running_now", fm, count=1, flags=re.MULTILINE)
            elif re.search(r"^task_id\s*:", fm, flags=re.MULTILINE):
                fm2 = re.sub(r"^(task_id:.*)$", r"\1\nkanban_status: running_now", fm, count=1, flags=re.MULTILINE)
            else:
                fm2 = fm + "\nkanban_status: running_now"
        text = head + fm2 + sep + body
# Format B table: replace or insert the kanban_status row
else:
    lines = text.splitlines()
    new_lines = []
    found = False
    status_idx = -1
    for i, line in enumerate(lines):
        if re.match(r"^\|\s*\*\*kanban_status\*\*\s*\|", line):
            new_lines.append("| **kanban_status** | running_now |")
            found = True
        else:
            new_lines.append(line)
        if re.match(r"^\|\s*\*\*status\*\*\s*\|", line):
            status_idx = len(new_lines) - 1
    if not found and status_idx >= 0:
        new_lines.insert(status_idx + 1, "| **kanban_status** | running_now |")
    text = "\n".join(new_lines) + "\n"
# Also: record which child task is the active work, in a body note (best-effort,
# only if the body doesn't already mention the child).
if child_id and f"## Active work ({child_id})" not in text:
    note = f"\n## Active work ({child_id})\n\nThis task was auto-dispatched at dispatch time. The actual work is happening in the child task `{child_id}` (assignee `{assignee}`). Re-dispatch is suppressed for 60s via a dotfile; this file's `kanban_status` is `running_now` so subsequent cron runs skip it.\n"
    # Append at end of body (after frontmatter close for format A, or anywhere for B)
    text = text.rstrip() + "\n" + note
with open(path, "w") as f:
    f.write(text)
PYEOF

    # Touch dotfile for dedup
    touch "$dotfile" 2>/dev/null || true

    # Append to log
    echo "$NOW_TS_ISO  $task_id  ->  $NEW_TASK_ID  assignee=$ASSIGNEE priority=$PRIORITY  title='$TITLE'" >> "$LOG_FILE" 2>/dev/null || true

    log "dispatched $task_id → $NEW_TASK_ID (parent frontmatter updated to running_now)"
  else
    log "WARN dispatch FAILED for $task_id: $RESULT"
  fi
done

log "done. dispatched=$DISPATCHED_COUNT scanned=$(echo "$TASKS_ALL" | wc -l)"
exit 0