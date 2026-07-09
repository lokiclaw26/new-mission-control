---
task_id: MC-MEMORY-GRAPH-1
assigned_to: forge
title: Mission Control Memory Graph — integrate lokiclaw26/Obsidian-Hermes-Agent- as new page
type: feature
priority: high
status: done
kanban_status: done
assignee: forge
argus_passed: true
completed: 2026-06-17T16:48:00+04:00
created: 2026-06-17T16:30:00+04:00
created_by: thor
approval_required: true
depends_on: [MC-KANBAN-5-RESULT-POPUP, MC-AUTO-PROCESS-2]
---

## Context (NOFI 2026-06-17 ~16:30 Dubai)

NOFI created a public GitHub repo for an "Obsidian for Agents" memory graph dashboard:
https://github.com/lokiclaw26/Obsidian-Hermes-Agent-

It has:
- Local Node server
- Dashboard UI (Canvas-based graph)
- JSONL event ingestion
- Graph persistence in JSON
- Server-Sent Events live updates
- Memory event schema
- Sample data + CLI event emitter + docs

Goal: integrate it into Mission Control as a new page called **"Memory Graph"** so we can watch Hermes' working memory structure itself over time, like Obsidian Graph View for agents.

## Mission Control's current stack (locked decisions)

Before touching code, the spec asks for technical decisions. These are LOCKED based on what already exists:

1. **Backend = Python stdlib http.server** (`serve.py` at `01_projects/mission-control/code/serve.py`, port 8767). NOT Node. Adding a second Node process would double the surface area and require another restart script.
2. **Frontend = vanilla JS + HTML in `kanban.html`** (one big file, ~80KB). NOT React/Vite. No build step.
3. **Persistence = SQLite** for some things, JSON files on disk for most. Mission Control does not have a heavy DB. JSON-on-disk is the established pattern.
4. **Real-time = 5s polling** (no SSE/WebSocket in current MC). The repo uses SSE — we will poll for simplicity. v1 doesn't need true streaming.
5. **Sidebar nav already exists** (`/kanban` and `/` routes). New page = `/memory-graph` route served by the same `serve.py`.

**Decisions are made: embed directly as a new page, reuse the EXISTING frontend stack, persistence stays JSON for v1, polling instead of SSE, no separate Node process.**

## Required actions

### Forge: build everything (split into 4 sub-phases if needed)

#### Phase A: Backend (in serve.py)

Add a new route group `/api/memory-graph/*` and a page route `/memory-graph`:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/memory-graph` | Serve the new HTML page |
| GET | `/api/memory-graph` | Get current graph (nodes + edges + metadata) |
| POST | `/api/memory-graph/events` | Ingest one or many events (node.upsert, edge.upsert, memory.snapshot) |
| GET | `/api/memory-graph/stream` | Server-Sent Events stream of updates (used only as enhancement; primary UI uses polling) |
| POST | `/api/memory-graph/reset` | Reset/reseed the graph (admin) |
| GET | `/api/memory-graph/events/recent` | Get the last N memory events from the append-only log |

**Persistence file:** `01_projects/mission-control/data/memory-graph.json`
- Top-level structure: `{ "nodes": {...by-id...}, "edges": [...], "metadata": {...} }`
- Nodes keyed by stable id so upserts work
- Edges stored as array (each edge has a stable id like `edge-<source>-<target>-<kind>`)
- Atomic writes: write to `.tmp` then rename

**Append-only event log:** `01_projects/mission-control/data/memory-graph-events.jsonl`
- Each line is one event (node.upsert, edge.upsert, memory.snapshot)
- Bounded retention: keep last 10,000 lines (auto-trim)

**Reuse the event contract from the repo verbatim** (NOFI specified it in section 4 of the request).

#### Phase B: Event bridge (in serve.py)

Add a helper `ingest_memory_event(event_dict)` that:
- Validates event type ∈ {`node.upsert`, `edge.upsert`, `memory.snapshot`, `edge.delete`, `node.delete`}
- For `node.upsert`: looks up node by id, merges metadata + status + importance, persists
- For `edge.upsert`: same for edges (use stable id `edge-<source>-<target>-<kind>`)
- For `memory.snapshot`: replaces the entire graph (admin only — requires confirmation header)
- For `node.delete` / `edge.delete`: removes the node/edge
- Appends to event log
- Updates an in-memory `last_updated` timestamp
- **Redacts secrets** before storing (see safety section below)

Expose this as a function that the existing `PATCH /api/data/kanban/task/:id` and other endpoints can call as a SIDE EFFECT when significant things happen.

#### Phase C: Frontend (new file: `memory-graph.html`)

The repo's dashboard is a Canvas-based graph with controls. We are **NOT** going to copy the Node server. Instead, Forge will:

1. Re-implement the core graph behaviors in vanilla JS, drawing on the repo's source for inspiration (zoom, pan, search, filters, click-to-inspect, hover labels, importance filter, live update)
2. Use HTML5 Canvas for rendering (or SVG if Canvas is too complex — choose whatever ships fastest and looks right)
3. Use a graph layout algorithm: **force-directed** (simple, ships fast) — implement in JS, not a library
4. Match Mission Control's visual system: dark theme + gold accents + monospace for data
5. Layout:
   - Top header: page title + live connection status (green dot = polling, red = error)
   - Left panel (300px): controls — search input, node-kind filter checkboxes, importance slider, "reset" button
   - Center: full-bleed canvas/graph
   - Right panel (350px): event feed (last 20 events) + selected-node inspector (when a node is clicked)
   - Footer: node count + edge count + last updated timestamp

Match the existing kanban.html structure (sidebar nav with Main / Kanban / Memory Graph tabs).

#### Phase D: Real Hermes event integration

Hook the existing MC endpoints so they emit memory graph events. At MINIMUM:

- `POST /api/data/kanban/task` → emit `node.upsert` for the new task
- `PATCH /api/data/kanban/task/:id` → emit `node.upsert` (status change) AND `edge.upsert` (e.g. `task_blocked_by` decision)
- `POST /api/data/memory-graph/events` → public endpoint for external emitters (the future Hermes agent bridge)

Emit ONLY meaningful events (not every PATCH — only status changes, assignments, results).

#### Phase E: Sample data

Ship a `sample-graph.json` so the page is alive on first load. Nodes: a handful of tasks, decisions, files, errors, concepts. Edges: the obvious relationships.

#### Phase F: Safety / Privacy

In the `ingest_memory_event` helper, before persisting:
- Strip API keys (regex: `sk-...`, `ghp_...`, `xox[bp]-...`, etc.)
- Strip passwords (`password=...`, `Bearer ...`, etc.)
- Strip auth headers (`Authorization: ...`)
- Truncate large payloads to first 500 chars + "..."
- Recursively walk the metadata dict

The redactor can be a small function in serve.py. NO third-party lib.

#### Phase G: Documentation

Create `01_projects/mission-control/docs/MEMORY_GRAPH.md` with:
- Architecture diagram (ASCII)
- Event contract (verbatim from NOFI's spec section 4)
- Endpoint reference
- Stable ID strategy
- Safety/redaction rules
- How to emit events from a sub-agent
- Examples in bash and python

Update the repo's docs to point to MC: edit `docs/HERMES_INTEGRATION.md` to reference the MC integration as the canonical deployment.

#### Phase H: CLI emitter helper

Create `/home/nofidofi/.hermes/scripts/memory-graph-emit.sh` so any agent can do:
```bash
bash /home/nofidofi/.hermes/scripts/memory-graph-emit.sh node.upsert '{"id":"...","kind":"...","label":"..."}'
bash /home/nofidofi/.hermes/scripts/memory-graph-emit.sh edge.upsert '{"source":"...","target":"...","kind":"..."}'
```

This is a wrapper so sub-agents don't have to remember the curl syntax.

### Out of scope (per NOFI's "make the simplest robust decision")

- DO NOT add a separate Node server
- DO NOT use React/Vite/build tooling
- DO NOT migrate to SQLite for v1 (JSON is fine)
- DO NOT add WebSockets (polling is fine)
- DO NOT redesign Mission Control's look
- DO NOT add cron
- DO NOT add new columns to the kanban
- DO NOT touch roguelike game code
- DO NOT touch DIY Hub code
- DO NOT make this touch the main `/` page — it's a NEW page `/memory-graph`

### Argus: verify

- [ ] `/memory-graph` page loads (HTTP 200)
- [ ] `/` page still loads (HTTP 200) — no regression
- [ ] `/kanban` still loads (HTTP 200) — no regression
- [ ] Sidebar nav shows 3 tabs: Main / Kanban / Memory Graph
- [ ] Sample graph renders: at least 5 nodes, 5 edges visible
- [ ] Clicking a node opens the inspector on the right
- [ ] Search input filters nodes by label
- [ ] Node-kind filter checkboxes hide/show categories
- [ ] Importance slider filters out nodes below threshold
- [ ] Reset button (with confirmation) clears the graph
- [ ] `POST /api/memory-graph/events` with a `node.upsert` adds the node
- [ ] `POST /api/memory-graph/events` with an `edge.upsert` adds the edge
- [ ] `GET /api/memory-graph` returns the updated graph
- [ ] Event log appends correctly (`/api/memory-graph/events/recent`)
- [ ] No secrets appear in any node's metadata (test with a fake event containing `sk-12345`)
- [ ] Playwright behavioral test: load page → wait 5s → screenshot → verify graph canvas has rendered pixels
- [ ] Live update: emit an event via the API → poll again → verify the new node appears
- [ ] Git commit created, pushed (or auto-sync)

## Acceptance criteria summary

✅ New `/memory-graph` page accessible from sidebar nav
✅ Backend: 5 new endpoints + persistence file + event log
✅ Frontend: Canvas-based graph with all 9 features (zoom/pan/search/filters/inspector/hover/importance/live/metrics)
✅ Event contract matches the spec verbatim
✅ Real event integration: kanban PATCHes emit memory graph events
✅ Sample data ships with 5+ nodes and 5+ edges
✅ Safety: secrets redacted before persistence
✅ Documentation: MEMORY_GRAPH.md in MC docs
✅ CLI helper: `memory-graph-emit.sh`
✅ All existing MC routes still work (no regression)
✅ Playwright behavioral test passes

## Final report format (required)

```
MC-MEMORY-GRAPH-1 — INTEGRATION REPORT

STATUS: Verified / Partial / Failed

TECHNICAL DECISIONS:
- backend: Python stdlib (existing serve.py) | not Node
- frontend: vanilla JS in new memory-graph.html | not React
- persistence: JSON on disk | not SQLite for v1
- realtime: 5s polling | not SSE/WebSocket
- layout: force-directed JS, no library

CHANGED FILES:
- list

BACKEND:
- endpoint /api/memory-graph
- endpoint /api/memory-graph/events
- endpoint /api/memory-graph/stream
- endpoint /api/memory-graph/reset
- endpoint /api/memory-graph/events/recent
- persistence: data/memory-graph.json
- event log: data/memory-graph-events.jsonl
- redactor: location + behavior

FRONTEND:
- file: memory-graph.html
- render: Canvas | SVG
- layout: force-directed JS
- features list (all 9)

EVENT BRIDGE:
- POST /api/data/kanban/task → node.upsert
- PATCH /api/data/kanban/task/:id → node.upsert + edge.upsert
- POST /api/memory-graph/events → direct ingest

SAMPLE DATA:
- nodes: count
- edges: count

SAFETY:
- secrets redacted: yes
- test with fake sk-... key: yes, no leak

NOT INCLUDED (per NOFI):
- Node server: not added
- React/Vite: not added
- SQLite migration: not done
- WebSockets: not added
- cron: not added

REGRESSION:
- /: 200
- /kanban: 200
- sidebar nav: 3 tabs
- /memory-graph: 200

ARGUS: Pass / Fail + reason
GIT: commit SHA

LOCAL RUN:
- start-mc.sh
- visit http://192.168.0.29:8767/memory-graph
```

## Notes for Forge

- READ THE REPO FIRST: https://github.com/lokiclaw26/Obsidian-Hermes-Agent- (you'll have access via git or via curl for the raw files). The repo has working code you can study. Don't blindly copy — adapt to MC's stack.
- The repo's `src/server/schema.js` and `src/server/store.js` are useful references for the event contract and persistence model.
- The repo's `src/dashboard/app.js` is the reference for graph layout. The "force-directed" approach there is solid.
- DO NOT install npm packages. MC has no Node dependencies. Use vanilla JS.
- If the repo's API differs from the spec NOFI gave, follow NOFI's spec, not the repo.
- The live update polling interval should be 5s (matching the kanban's existing pattern).
- The redactor should be a recursive function that walks the metadata dict, not a regex on the whole JSON (which would break structure).
