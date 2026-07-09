---
task_id: MC-MEMORY-GRAPH-3-HARDENING
title: Backend + frontend hardening: auth, redaction, validation, SQLite, layout fixes, mobile, clean inspector
type: refactor
priority: critical
status: done
kanban_status: done
assignee: forge
created: 2026-06-17T18:00:00+04:00
created_by: thor
approval_required: true
depends_on: [MC-MEMORY-GRAPH-2B-SIDEBAR-FIX]
---

## Context (NOFI 2026-06-17 ~18:00 Dubai)

NOFI reviewed Mission Control and identified security, data integrity, reliability, maintainability, and UI issues. Plus a critical Memory Graph bug: **the graph resets every 5 seconds and no node is selectable**.

The "resets every 5s" bug is likely because the polling `fetchGraph()` rebuilds the entire `ForceGraph3D` object (or rebuilds the data in a way that resets the camera and node selection). The "no node selectable" bug is likely the 3D ForceGraph click handler not firing — possibly because `onNodeClick` was not bound to a re-rendered canvas.

## Phase breakdown (in order)

This is a LARGE refactor. **Plan A**: split into multiple sub-tasks run sequentially so each can succeed within the 50-call sub-agent limit. **Plan B**: do it as one big task with continuation sub-agents. **Plan A is safer.**

For this task spec, define ALL the work but recommend Forge split into sub-tasks MC-MEMORY-GRAPH-3A (backend), 3B (frontend bug fixes), 3C (tests). This task file is the umbrella; the sub-agents will create their own task files.

---

## Backend requirements

### 1. Write-endpoint protection

**Add admin token via env var `MC_ADMIN_TOKEN`.**

For each mutating endpoint, check auth:

```python
def _is_authorized(request) -> bool:
    token = os.environ.get('MC_ADMIN_TOKEN', '').strip()
    if not token:
        # No token configured: deny LAN writes, allow only loopback
        client_ip = request.client_address[0]
        if client_ip in ('127.0.0.1', '::1', 'localhost'):
            return True
        return False
    # Token configured: require it
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        provided = auth_header[7:].strip()
    else:
        provided = request.headers.get('X-MC-Admin-Token', '').strip()
    return provided == token
```

Endpoints that require auth:
- `POST /api/memory-graph/events`
- `POST /api/memory-graph/reset`
- `POST /api/data/kanban/task`
- `PATCH /api/data/kanban/task/:id`
- `PATCH /api/data/kanban/task/:id/assign`
- `POST /api/data/order`

If `MC_ADMIN_TOKEN` is unset:
- Loopback (127.0.0.1, ::1) writes are allowed (for testing)
- LAN writes return 403 with a clear setup error message: `{"error": "MC_ADMIN_TOKEN env var is not set. LAN writes are disabled. Set MC_ADMIN_TOKEN or use loopback."}`

**Do NOT treat `{confirm: true}` as auth.** That was the previous bug.

Update frontend write calls to handle 401/403 by:
- Showing a banner if a write fails
- The 4 places that POST/PATCH from JS need a helper: `mcFetch(url, opts)` that wraps fetch and surfaces errors

**update start-mc.sh to export MC_ADMIN_TOKEN** (with a sensible default for dev, e.g. a random uuid generated on first run, stored in `~/.hermes/scripts/.env.mc`). Or document that the user must set it.

### 2. Memory Graph redaction (field-aware, NOT regex-on-everything)

Current bug: `redact_secrets()` was over-aggressive. It ate substrings of normal IDs.

**New approach**: walk the dict, classify each key:

```python
SECRET_KEYS = {'token', 'api_key', 'apikey', 'authorization', 'auth', 'password', 'pwd',
               'secret', 'bearer', 'credential', 'credentials', 'access_token', 'refresh_token',
               'private_key', 'session_token', 'csrf'}

FREETEXT_KEYS = {'summary', 'message', 'body', 'log', 'text', 'content', 'description',
                 'notes', 'note'}

GRAPH_KEYS = {'id', 'source', 'target', 'kind', 'label', 'tags', 'status', 'project',
              'path', 'task_id', 'created', 'updated', 'weight', 'importance', 'confidence',
              'actor', 'assignee', 'assigned_to', 'kanban_status'}

# Patterns for free-text secret detection
SECRET_PATTERNS = [
    (r'sk-[A-Za-z0-9_-]{16,}', 'sk-...'),
    (r'sk-ant-[A-Za-z0-9_-]{16,}', 'sk-ant-...'),
    (r'gh[pousr]_[A-Za-z0-9]{8,}', 'gh*_...'),
    (r'xox[bp]-[A-Za-z0-9-]{8,}', 'xox*-...'),
    (r'AKIA[0-9A-Z]{16}', 'AKIA...'),
    (r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', 'JWT'),
    (r'Bearer\s+[A-Za-z0-9._-]{8,}', 'Bearer [REDACTED]'),
    (r'Authorization:\s*[A-Za-z0-9._-]{8,}', 'Authorization [REDACTED]'),
    (r'api[_-]?key[=:]\s*[^\s"]+', 'api_key=[REDACTED]'),
    (r'token[=:]\s*[^\s"]+', 'token=[REDACTED]'),
    (r'password[=:]\s*[^\s"]+', 'password=[REDACTED]'),
]

def redact_secrets(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = k.lower()
            if kl in SECRET_KEYS:
                out[k] = '[REDACTED]' if v else v
            elif kl in GRAPH_KEYS:
                out[k] = redact_secrets(v) if isinstance(v, (dict, list)) else v
            else:
                out[k] = redact_secrets(v) if isinstance(v, (dict, list)) else _redact_freetext(v)
        return out
    elif isinstance(obj, list):
        return [redact_secrets(x) if isinstance(x, (dict, list)) else _redact_freetext(x) for x in obj]
    else:
        return _redact_freetext(obj)

def _redact_freetext(s):
    if not isinstance(s, str):
        return s
    if len(s) > 500:
        s = s[:500] + '...[truncated]'
    for pat, repl in SECRET_PATTERNS:
        s = re.sub(pat, repl, s, flags=re.IGNORECASE)
    return s
```

This way:
- `task-MC-MEMORY-GRAPH-2B` (a normal ID) is NOT touched
- `summary: "ghp_abcdefgh leaked"` has the ghp_ stripped
- `metadata.api_key = "..."` becomes `[REDACTED]`
- `metadata.session_token = "..."` becomes `[REDACTED]`

### 3. Memory Graph validation

**Node validation:**
- `id`: required, str, 1-200 chars, only `[A-Za-z0-9._-]`
- `kind`: required, str, one of `{goal, task, memory, decision, tool, file, error, concept, entity, session, message, status, endpoint}`. If missing, default to `concept`. If unknown, set to `concept` and log warning.
- `label`: optional str, max 500 chars
- `summary`: optional str, max 5000 chars
- `status`: optional str, max 100 chars
- `importance`: optional float, clamp 0..1
- `confidence`: optional float, clamp 0..1
- `metadata`: optional dict (will be redacted)

**Edge validation:**
- `source`: required, str, must exist as a node id (otherwise reject with 400, OR auto-create a placeholder node of kind `concept` with id=`source`)
- `target`: required, str, same rule
- `kind`: optional, one of the 16 allowed edge kinds
- `weight`: optional float, clamp 0..1
- `metadata`: optional dict

**Stable edge id**: `edge-<source>-<target>-<kind>` (existing behavior). Reject if duplicate id (i.e. don't double-upsert edges).

**Dangling edge handling on ingest**: if source or target doesn't exist, **auto-create a placeholder concept node** rather than rejecting. This is more lenient and matches Obsidian's behavior of auto-creating missing references.

**Repair/migration function** `repair_graph()`:
- Find all edges where source or target doesn't exist as a node
- Either: (a) create placeholders, or (b) drop the edges
- Default: (a) create placeholders
- Run on every `GET /api/memory-graph` call (cheap) OR on startup once

**Repair the existing ta[REDACTED] node/edge**: this was caused by the old redactor. Scan the JSONL event log for events that mention the original task IDs. If found, restore the original id. If not found, leave as-is (the placeholder gets dropped or merged).

### 4. Persistence reliability

**Process-level lock** around RMW and event log writes:
- Use `threading.RLock()` (works across threads in the same process)
- For multi-process safety, also use `fcntl.flock()` on a lockfile

**Migrate memory graph storage to SQLite with WAL**:
- DB file: `01_projects/mission-control/data/memory-graph.sqlite3`
- Tables:
  ```sql
  CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    label TEXT,
    summary TEXT,
    status TEXT,
    importance REAL DEFAULT 0.5,
    confidence REAL DEFAULT 0.5,
    source TEXT,
    metadata TEXT,  -- JSON
    created TEXT,
    updated TEXT
  );
  CREATE TABLE edges (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    kind TEXT,
    weight REAL DEFAULT 0.5,
    metadata TEXT,  -- JSON
    created TEXT
  );
  CREATE TABLE events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    actor TEXT,
    task_id TEXT,
    payload TEXT NOT NULL  -- JSON
  );
  CREATE INDEX idx_edges_source ON edges(source);
  CREATE INDEX idx_edges_target ON edges(target);
  CREATE INDEX idx_events_task_id ON events(task_id);
  ```
- WAL mode: `PRAGMA journal_mode=WAL`
- Keep `/api/memory-graph` response shape unchanged (same JSON: `{nodes, edges, last_updated, node_count, edge_count, metadata}`)

**Compatibility path**: on first startup, if `memory-graph.sqlite3` doesn't exist, check for `memory-graph.json` and import. After import, the JSON file is no longer used.

**Event log**:
- SQLite is the source of truth for events
- The old `memory-graph-events.jsonl` is read once on startup, imported into the events table, then never written to again
- `/api/memory-graph/events/recent` reads from the events table

### 5. Avoid request blocking

**Replace `socketserver.TCPServer` with `socketserver.ThreadingTCPServer`** (one thread per request). This is the standard pattern for the stdlib `http.server`.

**Disable the SSE stream endpoint** (`/api/memory-graph/stream`): it currently sleeps up to 30s per connection and can block the server. Since the frontend uses polling, SSE is unused. Remove or keep the route as a stub that returns 410 Gone. NOFI's spec says "remove/disable it if unused".

**Add timeouts**: any `subprocess.run` or `urllib.request` call should have a `timeout=` parameter (e.g. 5 seconds for health checks, 30 for git ops).

### 6. Split serve.py into maintainable modules

Current `serve.py` is ~2540 lines. Split into:
- `security.py` — auth, redactor
- `memory_graph_store.py` — SQLite layer (or JSON-file fallback)
- `memory_graph_api.py` — endpoint handlers
- `kanban_service.py` — kanban-related logic
- `github_status.py` — GitHub panel
- `server.py` — main HTTP server, route registration
- `serve.py` — thin entrypoint that imports server and runs it

Each file should be < 500 lines. Behavior MUST be identical. start-mc.sh still works.

### 7. HTTP/static behavior

- `Content-Type` for JS: `application/javascript`
- CSS: `text/css`
- Vendor files: keep `no-store` for now (safer)
- HTML: `no-store` (already done)
- Error responses: log full traceback server-side, return `{"error": "<safe message>"}` to client. NO raw exception detail in 500 responses.

---

## Frontend requirements

### 8. Fix canvas sizing/layout bug (the critical bug NOFI reported)

**Root cause hypothesis**: 
- `memory-graph.html` initializes `Graph` once with `document.getElementById('graph')` but doesn't set width/height explicitly
- The 3d-force-graph library uses the parent's bounding box at init time
- The polling `fetchGraph()` calls `Graph.graphData({...})` which **resets the camera position** and may also reset node positions
- The 5s polling rebuilds the data on every poll, so the graph appears to "reset" every 5s

**Fix**:
- Save camera position before each `graphData` call, restore after
- Use `ResizeObserver` to detect container resize and call `Graph.width(w).height(h)`
- For the "no node selectable" bug: ensure `onNodeClick` is bound to the right element. Some 3D libraries require a fresh binding after `graphData` is updated.

**Implementation**:
```javascript
let Graph = null;
let _lastCameraPos = { x: 0, y: 0, z: 250 };

function initGraph() {
  Graph = ForceGraph3D()(document.getElementById('graph'))
    .backgroundColor('#0a0a0a')
    .width(document.getElementById('graph').clientWidth)
    .height(document.getElementById('graph').clientHeight)
    .onNodeClick(n => { selectedNode = n; renderInspector(); });
  
  // Resize observer
  const ro = new ResizeObserver(entries => {
    for (const e of entries) {
      const w = e.contentRect.width;
      const h = e.contentRect.height;
      if (Graph) Graph.width(w).height(h);
    }
  });
  ro.observe(document.getElementById('graph'));
}

function applyFilters() {
  // ... compute filtered data ...
  if (Graph) {
    // Save camera
    try { _lastCameraPos = Graph.cameraPosition(); } catch (e) {}
    Graph.graphData({ nodes: filteredNodes, links: filteredEdges });
    // Restore camera
    try { Graph.cameraPosition(_lastCameraPos); } catch (e) {}
  }
}
```

### 9. Responsive layout

- Desktop (>= 1024px): current layout (sidebar 180px + controls 300px + graph + right 350px)
- Tablet (768-1023px): collapse right panel into a bottom drawer, controls as left rail
- Mobile (< 768px): top nav bar instead of left sidebar, controls + right panel as tabs

Use CSS `@media` queries. NO external CSS framework. Test at 390x844 (iPhone) and 768x1024 (iPad).

Ensure `body { overflow-x: hidden }` to prevent horizontal scroll.

### 10. Clean selected node inspector

The current `renderInspector()` does:
```javascript
el.innerHTML = '<pre>' + JSON.stringify(selectedNode, null, 2) + '</pre>';
```

This dumps the entire 3D object (with `__threeObj`, `x`, `y`, `z`, `vx`, `vy`, `vz`, `geometry`, `material` etc.). NOFI hates this.

**Fix**: build a clean detail view with only the user-facing fields:

```javascript
const DETAIL_KEYS = ['id', 'kind', 'label', 'summary', 'status', 'importance', 'confidence', 'tags', 'project', 'path', 'url', 'source', 'created', 'updated'];

function renderInspector() {
  const el = document.getElementById('node-details');
  if (!selectedNode) {
    el.textContent = 'Click a node to see details';
    return;
  }
  // Use DOM construction, not innerHTML
  el.innerHTML = '';
  const dl = document.createElement('dl');
  dl.className = 'node-detail';
  for (const key of DETAIL_KEYS) {
    if (selectedNode[key] != null && selectedNode[key] !== '') {
      const dt = document.createElement('dt');
      dt.textContent = key;
      const dd = document.createElement('dd');
      dd.textContent = typeof selectedNode[key] === 'object' ? JSON.stringify(selectedNode[key]) : String(selectedNode[key]);
      dl.appendChild(dt);
      dl.appendChild(dd);
    }
  }
  el.appendChild(dl);
}
```

Use `textContent` for values to prevent XSS. Use `DOM` construction to prevent innerHTML-based attacks.

### 11. Filtering UX

- Footer counts: `Nodes: <filtered> / <total>` and `Edges: <filtered> / <total>`
- Empty state: if filtered count is 0, show a message in the graph area: "No nodes match your filters"
- Clear selected node if it's filtered out (set `selectedNode = null` in `applyFilters()` if not in filtered set)
- Recent Events panel should always be visible and functional regardless of node selection

---

## Testing requirements

Add a `tests/` directory at `01_projects/mission-control/tests/` with `unittest` files:

- `test_auth.py` — POST without auth = 403, POST with auth = 200, no env var = loopback-only
- `test_redaction.py` — task IDs preserved (e.g. `task-MC-MEMORY-GRAPH-1` stays the same), real secrets like `sk-12345abcdef` get `[REDACTED]`, `Bearer xyz` gets `Bearer [REDACTED]`
- `test_graph.py` — node.upsert with valid id = 200, missing id = 400, dangling edge auto-creates placeholder, duplicate edge rejected
- `test_kanban.py` — PATCH /api/data/kanban/task/:id still works for status changes
- `test_reset.py` — reset requires auth

Run with:
```bash
cd /home/nofidofi/NofiTech-Ind/01_projects/mission-control
python -m py_compile code/*.py
python -m unittest discover tests/
```

---

## Sub-task plan (recommended)

If Forge hits 50-call limit, split into:

- **MC-MEMORY-GRAPH-3A-BACKEND**: security.py + memory_graph_store.py (SQLite) + memory_graph_api.py + kanban_service.py + serve.py split + tests
- **MC-MEMORY-GRAPH-3B-FRONTEND**: layout fix + responsive + clean inspector + filtering UX
- **MC-MEMORY-GRAPH-3C-INTEGRATION**: verify all 11 fixes, manual checks, screenshots, commit

---

## Out of scope
- DO NOT add new features
- DO NOT redesign the look
- DO NOT add a separate Node process
- DO NOT add cron
- DO NOT touch roguelike or DIY Hub
- DO NOT remove the existing JSON persistence path (only migrate, keep compatibility)

## Acceptance criteria

### Backend
- [ ] `MC_ADMIN_TOKEN` env var controls write access
- [ ] Without token: LAN writes = 403, loopback writes = 200
- [ ] With token: writes require `Authorization: Bearer <token>` or `X-MC-Admin-Token: <token>`
- [ ] Redactor preserves task IDs (`task-MC-...` unchanged)
- [ ] Redactor strips `sk-...`, `ghp_...`, `Bearer ...`, `Authorization: ...`, `api_key=...`, `password=...`, `token=...`
- [ ] Memory graph storage in SQLite with WAL
- [ ] Compatibility: first startup imports `memory-graph.json`
- [ ] Event log in SQLite (no more JSONL re-reads on every event)
- [ ] ThreadingTCPServer (not blocking)
- [ ] SSE stream disabled (410 Gone or removed)
- [ ] All 5+ sub-200ms subprocess calls have timeouts
- [ ] serve.py split into 6+ modules, each < 500 lines
- [ ] Content-Type correct for JS/CSS
- [ ] Errors return safe message, full traceback in server log
- [ ] Unittests pass

### Frontend
- [ ] Graph does NOT reset every 5s (camera + selection preserved)
- [ ] Node click works (selection updates inspector)
- [ ] Canvas sized correctly via ResizeObserver
- [ ] Mobile (390x844): no horizontal overflow, controls accessible
- [ ] Tablet (768x1024): usable layout
- [ ] Inspector shows clean fields (label, id, kind, summary, etc.) — NO __threeObj, x/y/z
- [ ] Inspector uses textContent / DOM construction (XSS safe)
- [ ] Footer shows "X / Y" counts
- [ ] Empty state shown when no matches
- [ ] Selected node cleared if filtered out
- [ ] Recent Events always visible

### Manual verification
- [ ] /memory-graph desktop 1280x720: no horizontal overflow
- [ ] /memory-graph mobile 390x844: usable
- [ ] Click a node: clean details shown
- [ ] No-match search: empty state + filtered counts
- [ ] /api/memory-graph returns same shape

## Final report format

```
MC-MEMORY-GRAPH-3 — HARDENING REPORT

STATUS: Verified / Partial / Failed

CHANGED FILES:
- list with one-line description

BACKEND:
- MC_ADMIN_TOKEN enforcement
- redaction field-aware
- SQLite WAL with import
- threading server
- SSE disabled
- modules split

FRONTEND:
- canvas resize observer
- graph no longer resets
- node selection works
- responsive layout
- clean inspector
- empty state

TESTS:
- py_compile: pass
- unittest: pass / fail with details
- manual: pass / fail

NOT INCLUDED:
- list

RISKS:
- list

GIT: commit SHA
```

## Notes for Forge
- This is the largest refactor so far. If you hit the 50-call limit, STOP and let the continuation sub-agent take over. Do NOT leave the work half-done.
- The frontend bug (graph resets + no node selectable) is the HIGHEST priority. Fix that first.
- The serve.py split is also high-priority. Plan the file boundaries clearly before editing.
- SQLite migration: keep the JSON file readable as fallback. On first run with SQLite missing + JSON present, import once. Never write to JSON after migration.
- Run `python -m py_compile code/*.py` after every backend change. Catches syntax errors fast.
- The redactor change is a security fix. Test it with real-looking secrets AND with normal task IDs. Both must work.
- If a sub-task fails or is too large, create a follow-up task file (e.g. MC-MEMORY-GRAPH-3A2-BACKEND-CONT) and move on. The umbrella task is for tracking, not for one big sub-agent.
