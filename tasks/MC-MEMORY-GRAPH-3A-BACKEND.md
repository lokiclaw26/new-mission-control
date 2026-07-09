---
task_id: MC-MEMORY-GRAPH-3A-BACKEND
assigned_to: forge
title: Backend hardening: auth, redaction, validation, SQLite, threading, module split
type: refactor
priority: critical
status: done
kanban_status: done
assignee: forge
argus_passed: true
completed: 2026-06-17T22:40:00+04:00
created: 2026-06-17T18:05:00+04:00
created_by: thor
approval_required: true
depends_on: [MC-MEMORY-GRAPH-2B-SIDEBAR-FIX]
---

## Sub-task of MC-MEMORY-GRAPH-3-HARDENING (the umbrella)

## Scope (7 of 11 items from umbrella)

### 1. Auth (MC_ADMIN_TOKEN)
- `security.py`: `is_authorized(request)` function
- `MC_ADMIN_TOKEN` env var. If unset: loopback only (127.0.0.1, ::1). If set: require `Authorization: Bearer <token>` OR `X-MC-Admin-Token: <token>`.
- Apply to: POST /api/memory-graph/events, POST /api/memory-graph/reset, POST /api/data/kanban/task, PATCH /api/data/kanban/task/:id, PATCH /api/data/kanban/task/:id/assign, POST /api/data/order
- Do NOT treat {confirm:true} as auth

### 2. Redaction (field-aware)
- Move redactor to `security.py`
- New `redact_secrets(obj)` walks dict, classifies keys:
  - SECRET_KEYS (api_key, password, token, etc) → value becomes `[REDACTED]`
  - GRAPH_KEYS (id, source, target, kind, label, etc) → recurse but don't redact unless whole value is a secret
  - FREETEXT_KEYS (summary, message, body) → apply secret PATTERNS only
- Patterns: sk-[A-Za-z0-9_-]{16,}, ghp_[A-Za-z0-9]{8,}, xox[bp]-, AKIA, Bearer ..., Authorization: ..., api_key=..., password=..., token=..., JWT (eyJ...)
- Truncate strings > 500 chars to first 500 + '...[truncated]'

### 3. Validation
- `memory_graph_api.py` validate event payloads before ingest
- Node: id required, bounded, safe chars; kind in {goal,task,memory,decision,tool,file,error,concept,entity,session,message,status,endpoint} (default concept if missing); importance/confidence clamped 0..1
- Edge: source/target required; if missing, auto-create placeholder concept node; weight clamped; duplicate edge id rejected
- Return 400 with clear error message on validation failure

### 4. SQLite migration
- New `memory_graph_store.py` with SQLite (WAL mode)
- DB: `data/memory-graph.sqlite3`
- Tables: nodes, edges, events (with seq primary key)
- Compatibility: on first startup, if SQLite missing + JSON present, import JSON. Never write to JSON after migration.
- Event append: INSERT into events table (atomic, no read-rewrite)
- All public API response shapes unchanged

### 5. Threading server
- Replace `socketserver.TCPServer` with `socketserver.ThreadingTCPServer`
- Add `daemon_threads = True` so server can shut down cleanly
- Add `socketserver.ThreadingMixIn` to the existing server class

### 6. SSE disable
- `/api/memory-graph/stream` returns 410 Gone with explanation, OR remove entirely
- NO 30s sleep anywhere in the request handlers

### 7. Module split
- `security.py` — auth + redaction
- `memory_graph_store.py` — SQLite layer
- `memory_graph_api.py` — endpoint handlers
- `kanban_service.py` — kanban logic
- `github_status.py` — GitHub panel logic
- `server.py` — main HTTP server + route registration
- `serve.py` — thin entrypoint: `from server import *; run()`

Each file < 500 lines. Imports only stdlib. start-mc.sh still works (it should still call `python3 serve.py`).

## Out of scope (deferred to 3B and 3C)
- Frontend canvas resize, selection, responsive
- Inspector cleanup
- Filtering UX
- Tests (deferred to 3C)

## Verification (you do this yourself)

```bash
cd /home/nofidofi/NofiTech-Ind/01_projects/mission-control/code
python3 -m py_compile *.py
echo "syntax OK"

# Restart server
pkill -f "serve.py" 2>/dev/null
sleep 2

# Test without token: LAN write should fail
curl -s -X POST http://192.168.0.29:8767/api/memory-graph/events \
  -H "Content-Type: application/json" \
  -d '{"type":"node.upsert","node":{"id":"auth-test-1","kind":"concept","label":"test"}}'
# Expected: 403 with setup error message

# Test with token: LAN write should succeed
export MC_ADMIN_TOKEN="dev-test-token-12345"
# Need to start server with the token env var
nohup python3 serve.py > /tmp/mc-serve.log 2>&1 &
sleep 3

curl -s -X POST http://192.168.0.29:8767/api/memory-graph/events \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-test-token-12345" \
  -d '{"type":"node.upsert","node":{"id":"auth-test-2","kind":"concept","label":"test with auth"}}'
# Expected: 200 OK

# Verify redaction preserves task IDs
curl -s -X POST http://192.168.0.29:8767/api/memory-graph/events \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-test-token-12345" \
  -d '{"type":"node.upsert","node":{"id":"task-MC-MEMORY-GRAPH-3","kind":"task","label":"preserve this id","summary":"***"}}}'
sleep 1
curl -s http://192.168.0.29:8767/api/memory-graph | python3 -c "
import json, sys
d = json.load(sys.stdin)
for n in d.get('nodes', []):
    if n.get('id') == 'task-MC-MEMORY-GRAPH-3':
        print('FOUND ID:', n.get('id'))
        print('summary:', n.get('summary'))
        if n.get('id') == 'task-MC-MEMORY-GRAPH-3' and n.get('summary') == '[REDACTED]':
            print('REDACTION OK')
"

# Verify SQLite is being used
ls -la /home/nofidofi/NofiTech-Ind/01_projects/mission-control/data/
# Should see memory-graph.sqlite3, memory-graph.sqlite3-wal, memory-graph.sqlite3-shm

# Verify threading
ps aux | grep "serve.py" | grep -v grep

# Verify no SSE 30s sleep
grep -n "time.sleep(30)\|time.sleep(60)" /home/nofidofi/NofiTech-Ind/01_projects/mission-control/code/*.py

# Cleanup
curl -s -X POST http://192.168.0.29:8767/api/memory-graph/events \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-test-token-12345" \
  -d '{"type":"node.delete","node":{"id":"auth-test-2"}}' > /dev/null
```

## Out of scope
- DO NOT touch memory-graph.html
- DO NOT touch the frontend
- DO NOT add new features
- DO NOT touch roguelike or DIY Hub

## Return
- List of files created/modified
- Module sizes (wc -l)
- HTTP test results (auth required + redaction)
- Git commit SHA
- Any issues encountered

## Constraints
- 50 tool calls max. Be efficient.
- Run `python3 -m py_compile code/*.py` after every backend change.
- If you hit the call limit mid-task, STOP cleanly: commit what you have, write a partial log, mark the task for continuation.
