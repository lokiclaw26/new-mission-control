---
task_id: MC-KANBAN-3-EXPLICIT-RUNNING-STATE
title: Explicit Running State on Delegation — Thor moves tasks to running_now when delegating
project: mission-control
phase: live-monitor
status: done
priority: high
created: 2026-06-17T12:00:00+04:00
created_by: thor
assigned_to: forge, argus
approval_required: true
approval_status: approved
approval_phrase: "NOFI chose Option A: Thor explicitly sets kanban_status when delegating. No cron. No silent sub-agent state changes."
argus_passed: false
depends_on: [MC-KANBAN-RUNNING-NOW-1]
blocks: [MC-KANBAN-FREEZE-ACCEPTANCE]
tags: [mission-control, kanban, delegation, explicit-state, no-cron, option-a]
kanban_status: done
---

# MC-KANBAN-3-EXPLICIT-RUNNING-STATE — Thor owns delegation state transitions

## NOFI's decision (verbatim, 2026-06-17 ~11:55 Dubai)

*"Use Option A. Thor must explicitly set kanban_status when delegating work to a sub-agent. Do not implement cron yet. Do not let sub-agents silently set their own starting state yet. Do not add automatic demotion yet."*

NOFI wants:
- Explicit state transitions tied to delegation events
- Auditable (who set the state, when, why)
- No silent mutations
- Background cron comes LATER as a stale-task warning system, not as a silent state changer

## Approved state machine

| Event | Thor (parent) | Sub-agent (Forge/Argus) |
|---|---|---|
| 1. New task via + button | `status: triage` (default — NOT running) | n/a |
| 2. Thor delegates to Forge | PATCH: `assignee=forge, kanban_status=running_now` + append `work_started` event | n/a |
| 3. Thor delegates to Argus | PATCH: `assignee=argus, kanban_status=running_now` + append `work_started` event | n/a |
| 4. Sub-agent completes | (no action — let sub-agent do it) | PATCH: `status=complete, kanban_status=done` + append `task_completed` event |
| 5. Sub-agent blocked | (no action — let sub-agent do it) | PATCH: `kanban_status=blocked` + write blocker reason into task file + append `blocked` event |

## NOT approved (out of scope)

- ❌ Cron auto-promotion (ready → running_now)
- ❌ Cron auto-demotion (running_now → ready)
- ❌ Cron stale-task warnings
- ❌ Silent sub-agent state mutations unless Thor ordered it
- ❌ New Kanban UX features

## Goal

Make delegation explicit. When Thor calls `delegate_task(goal=..., toolsets=...)`, immediately afterwards Thor should:
1. PATCH the task file to set `assignee` and `kanban_status: running_now`
2. Append a `work_started` event to events.jsonl

When the sub-agent finishes (returns from delegate_task), it should:
1. PATCH the task file to set `status: complete, kanban_status: done` (on success)
2. OR `kanban_status: blocked` + write blocker reason (on failure)
3. Append the appropriate event

## Implementation

### Part 1 — Helper script (Forge)

Create `/home/nofidofi/.hermes/scripts/kanban-set-state.sh`:

```bash
#!/bin/bash
# kanban-set-state.sh — explicit state transitions for kanban tasks
# Usage: kanban-set-state.sh <task_id> <new_kanban_status> [assignee] [blocker_reason]
#
# Examples:
#   kanban-set-state.sh MC-XYZ running_now forge ""          # Thor delegating to Forge
#   kanban-set-state.sh MC-XYZ done         ""   ""           # Sub-agent completing
#   kanban-set-state.sh MC-XYZ blocked      ""   "waiting on NOFI approval"  # Sub-agent blocked
#
# This script:
# 1. Finds the task file
# 2. Updates the YAML frontmatter (Format A) or markdown table (Format B)
# 3. PATCHes the task via the running server
# 4. Appends an event to events.jsonl
# 5. Returns success/failure exit code

set -e
TASK_ID="$1"
NEW_STATUS="$2"
ASSIGNEE="${3:-}"
BLOCKER="${4:-}"

SERVER="http://192.168.0.29:8767"

if [ -z "$TASK_ID" ] || [ -z "$NEW_STATUS" ]; then
  echo "Usage: $0 <task_id> <new_status> [assignee] [blocker_reason]" >&2
  exit 1
fi

# 1. Build the JSON payload
if [ -n "$ASSIGNEE" ]; then
  PAYLOAD=$(python3 -c "import json; print(json.dumps({'status': '$NEW_STATUS', 'assignee': '$ASSIGNEE'}))")
elif [ -n "$BLOCKER" ]; then
  PAYLOAD=$(python3 -c "import json; print(json.dumps({'status': '$NEW_STATUS', 'blocker': '$BLOCKER'}))")
else
  PAYLOAD=$(python3 -c "import json; print(json.dumps({'status': '$NEW_STATUS'}))")
fi

# 2. PATCH the server
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X PATCH "$SERVER/api/data/kanban/task/$TASK_ID" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")

if [ "$HTTP_CODE" != "200" ]; then
  echo "kanban-set-state: PATCH failed for $TASK_ID (HTTP $HTTP_CODE)" >&2
  exit 1
fi

# 3. Append event to events.jsonl
TS=$(date -u +%Y-%m-%dT%H:%M:%S+04:00)  # Dubai time
EVENTS="/home/nofidofi/NofiTech-Ind/00_company_os/events.jsonl"
ACTOR=$(whoami)

if [ "$NEW_STATUS" = "running_now" ]; then
  EVENT_TYPE="work_started"
  NOTE="Thor delegated to ${ASSIGNEE}"
elif [ "$NEW_STATUS" = "done" ]; then
  EVENT_TYPE="task_completed"
  NOTE="Sub-agent completed task"
elif [ "$NEW_STATUS" = "blocked" ]; then
  EVENT_TYPE="task_blocked"
  NOTE="Sub-agent blocked: $BLOCKER"
else
  EVENT_TYPE="state_changed"
  NOTE="State changed to $NEW_STATUS"
fi

python3 -c "
import json
from datetime import datetime, timezone, timedelta
dubai = timezone(timedelta(hours=4))
now = datetime.now(dubai).isoformat()
e = {'ts': now, 'event_type': '$EVENT_TYPE', 'actor': '$ACTOR', 'project': 'mission-control', 'task_id': '$TASK_ID', 'note': '$NOTE'}
with open('$EVENTS', 'a') as f:
    f.write(json.dumps(e) + '\n')
"

echo "kanban-set-state: $TASK_ID -> $NEW_STATUS (event: $EVENT_TYPE)" >&2
exit 0
```

Make it executable: `chmod +x /home/nofidofi/.hermes/scripts/kanban-set-state.sh`

### Part 2 — No code changes to delegation flow itself

The `delegate_task` tool doesn't need modification. Thor just calls `kanban-set-state.sh` immediately BEFORE or AFTER each delegation:

```python
# Thor's pattern (in mental model / future automation):
# 1. Write task spec
# 2. Append task_created event
# 3. Update state.json
# 4. Run: kanban-set-state.sh $TASK_ID running_now forge
# 5. Run: delegate_task(goal=..., context=..., toolsets=[...])
# 6. After sub-agent finishes, it should call kanban-set-state.sh itself with done/blocked
```

The script is documented for Thor's use. It's a helper, not an auto-trigger.

### Part 3 — Verification (Argus, mandatory behavioral test)

Argus must verify:

1. **No cron added** — `cronjob list` should not have any new kanban-state cron
2. **No new UX features** — diff the served /kanban page against the previous version
3. **Helper script exists + is executable** — `ls -la /home/nofidofi/.hermes/scripts/kanban-set-state.sh`
4. **Helper script works**:
   - Pick a real task (e.g. MC-007-token-budget)
   - Run: `kanban-set-state.sh MC-007-token-budget running_now forge`
   - Verify: task file now has `kanban_status: running_now` and `assignee: forge`
   - Verify: events.jsonl got a new `work_started` event
   - Run: `kanban-set-state.sh MC-007-token-budget done`
   - Verify: task file now has `status: complete` and `kanban_status: done`
   - Verify: events.jsonl got a new `task_completed` event
   - Run: `kanban-set-state.sh MC-007-token-budget blocked "" "test blocker"`
   - Verify: task file now has `kanban_status: blocked` and a blocker note in the body
   - Verify: events.jsonl got a new `task_blocked` event
5. **No regressions** — all existing endpoints 200, parser still reads both formats
6. **New + button tasks** are not auto-marked as running_now (default is `triage`)
7. **Mission Control dashboard still loads**
8. **Git commit exists**

## Out of scope

- No cron jobs added
- No changes to delegation flow (just add a helper script)
- No new UX features
- No auto-detection of active work
- No stale-task warnings

## Acceptance criteria

- [ ] `/home/nofidofi/.hermes/scripts/kanban-set-state.sh` exists, executable
- [ ] `kanban-set-state.sh <task> running_now <assignee>` works (PATCH + event)
- [ ] `kanban-set-state.sh <task> done` works
- [ ] `kanban-set-state.sh <task> blocked <reason>` works
- [ ] No new cron job added (cronjob list shows no kanban-state cron)
- [ ] No new UX features (diff /kanban page = no change except possibly the script reference)
- [ ] All 10 existing endpoints still 200
- [ ] Parser still reads both YAML and table formats
- [ ] Drag/drop, inline create, polling, lanes all still work
- [ ] Mission Control still loads
- [ ] No data loss to lifecycle status
- [ ] Argus behavioral test PASS
- [ ] Git commit exists

## Files to touch

- `/home/nofidofi/.hermes/scripts/kanban-set-state.sh` (NEW, ~50 lines bash)
- `01_projects/mission-control/tasks/MC-KANBAN-3-EXPLICIT-RUNNING-STATE.md` (task spec, just created)
- `00_company_os/04_agents/logs/2026-06-17/forge-mc-kanban-3.md` (forge log)
- `00_company_os/04_agents/logs/2026-06-17/argus-mc-kanban-3.md` (argus log)

NO changes to serve.py, kanban.html, kanban_parser.py, mission-control.html, or any task file.

## Handoff to Forge

1. Read this task spec
2. Create the script at `/home/nofidofi/.hermes/scripts/kanban-set-state.sh`
3. `chmod +x` it
4. Test it manually with a real task (e.g. MC-007-token-budget)
5. Verify the task file is updated and events.jsonl gets new events
6. REVERT the test changes
7. Commit (the script lives outside the repo, but the task file, log file are in the repo)
8. Write your log

## Handoff to Argus

1. Verify the script exists + is executable
2. Run the 4 test scenarios (running_now, done, blocked, no-op-no-cron)
3. Verify NO cron was added
4. Verify NO new UX features
5. Verify all endpoints 200
6. Verify parser still works for both formats
7. Write argus log

## Self-criticism

This is a small, focused change. The risk:
- The script could fail silently (no exit code, no error visible to caller)
- The script could write malformed events.jsonl (need to be careful with newlines)
- The helper script approach is manual — Thor needs to remember to call it. This is the cost of "explicit" per NOFI's request. A future cron could automate it; for now, manual.

The behavioral test is MANDATORY. No structural-only verification this time. Pattern continues.

## Open follow-ups

- After this: MC-KANBAN-FREEZE-ACCEPTANCE
- Future: when this is well-tested, consider making Thor's delegation flow call the helper automatically (still explicit, just less manual)
- Future: cron stale-task warning (NOT a state changer — just alerts)
