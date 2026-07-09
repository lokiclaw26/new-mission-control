#!/bin/bash
# kanban-delegate.sh — atomic wrapper for the "I'm about to delegate this task" flow
# Usage: kanban-delegate.sh <TASK_ID> <assignee> [note]
#
# Assignee must be one of: thor, forge, argus
#
# This wrapper does THREE things, in order, and refuses to do them halfway:
#   1. Validate the task file exists and the assignee is allowed
#   2. PATCH the running Mission Control server: kanban_status=running_now, assignee=<agent>
#   3. Append a work_started event to 00_company_os/04_agents/events.jsonl
#
# On success it prints a clear "Now safe to call delegate_task" message so the
# calling agent (Thor) knows it is finally safe to actually call delegate_task.
# If any step fails it exits non-zero WITHOUT mutating state silently.
#
# Why this exists: NOFI reported that the RUNNING NOW column never showed the
# task Thor was actively working on. Root cause: Thor had to remember TWO
# separate actions (set running_now + call delegate_task) and was forgetting
# the first one. This wrapper makes the two a single atomic op that Thor
# cannot delegate without.

set -e

TASK_ID="${1:-}"
ASSIGNEE="${2:-}"
NOTE="${3:-Thor delegated to $ASSIGNEE via kanban-delegate.sh}"
SERVER="http://192.168.0.29:8767"
COMPANY_ROOT="/home/nofidofi/NofiTech-Ind"
AGENT_EVENTS_FILE="$COMPANY_ROOT/00_company_os/04_agents/events.jsonl"
ALLOWED_ASSIGNEES="thor forge argus"

# ---- Argument validation ----
if [ -z "$TASK_ID" ] || [ -z "$ASSIGNEE" ]; then
  echo "Usage: $0 <task_id> <assignee> [note]" >&2
  echo "  assignee must be one of: $ALLOWED_ASSIGNEES" >&2
  exit 2
fi

# Validate assignee is in allow-list
ASSIGNEE_OK=0
for a in $ALLOWED_ASSIGNEES; do
  if [ "$a" = "$ASSIGNEE" ]; then
    ASSIGNEE_OK=1
    break
  fi
done
if [ "$ASSIGNEE_OK" -ne 1 ]; then
  echo "kanban-delegate: REJECTED assignee='$ASSIGNEE'" >&2
  echo "  allowed: $ALLOWED_ASSIGNEES" >&2
  echo "  no state change performed" >&2
  exit 3
fi

# ---- Task file validation ----
TASK_FILE=$(find "$COMPANY_ROOT/01_projects" -path "*/tasks/${TASK_ID}.md" -type f 2>/dev/null | head -1)
if [ -z "$TASK_FILE" ]; then
  echo "kanban-delegate: REJECTED task_id='$TASK_ID' (no task file found under 01_projects/*/tasks/)" >&2
  exit 4
fi

# Capture old kanban_status for the report
OLD_STATUS=$(grep -E '^kanban_status:' "$TASK_FILE" | head -1 | sed 's/^kanban_status:[[:space:]]*//' | tr -d '"' || echo "unknown")
OLD_ASSIGNEE=$(grep -E '^assignee:' "$TASK_FILE" | head -1 | sed 's/^assignee:[[:space:]]*//' | tr -d '"' || echo "unknown")

# ---- PATCH the server ----
PAYLOAD=$(python3 -c "import json,sys; print(json.dumps({'status': 'running_now', 'assignee': sys.argv[1]}))" "$ASSIGNEE")
HTTP_CODE=$(curl -s -o /tmp/kanban-delegate-curl.err -w "%{http_code}" -X PATCH "$SERVER/api/data/kanban/task/$TASK_ID" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" || echo "000")

if [ "$HTTP_CODE" != "200" ]; then
  echo "kanban-delegate: PATCH failed for $TASK_ID (HTTP $HTTP_CODE)" >&2
  cat /tmp/kanban-delegate-curl.err >&2 2>/dev/null || true
  echo "  payload: $PAYLOAD" >&2
  echo "  no event appended" >&2
  exit 5
fi

# ---- Update task file frontmatter (best-effort, does not block event log on minor failure) ----
python3 - "$TASK_FILE" "$ASSIGNEE" <<'PY' || true
import re, sys
path, assignee = sys.argv[1], sys.argv[2]
with open(path) as f:
    text = f.read()
# Update assignee line
text2 = re.sub(r'^(assignee:\s*).*$', r'\g<1>' + assignee, text, count=1, flags=re.MULTILINE)
# Update kanban_status line
text3 = re.sub(r'^(kanban_status:\s*).*$', r'\g<1>running_now', text2, count=1, flags=re.MULTILINE)
with open(path, 'w') as f:
    f.write(text3)
PY

# ---- Append work_started event to agent events log ----
python3 - "$TASK_ID" "$ASSIGNEE" "$NOTE" "$AGENT_EVENTS_FILE" <<'PY'
import json, sys
from datetime import datetime, timezone, timedelta
task_id, assignee, note, path = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
dubai = timezone(timedelta(hours=4))
ts = datetime.now(dubai).isoformat()
event = {
    "event_type": "work_started",
    "task_id": task_id,
    "actor": "thor",
    "assignee": assignee,
    "timestamp": ts,
    "note": note,
}
with open(path, 'a') as f:
    f.write(json.dumps(event) + '\n')
PY

# ---- Success report ----
cat <<EOF
kanban-delegate: $TASK_ID
  kanban_status: running_now (was $OLD_STATUS)
  assignee: $ASSIGNEE (was $OLD_ASSIGNEE)
  event: work_started appended to 04_agents/events.jsonl
  task file: $TASK_FILE

Now safe to call delegate_task for this task.
EOF
exit 0
