---
id: MC-LIVE-MEMORY-GRAPH-1
title: Real live persistent memory graph (replaces dummy seed)
project: mission-control
created_by: thor
assigned_to: forge
status: done
priority: critical
created_at: 2026-06-19T14:40:00+04:00
updated_at: 2026-06-19T14:40:00+04:00
current_stage: ready
blocker: ""
data_source: nofi-bug-report
result: ""
description: "NOFI: 'I WANT A LIVE ACTUAL MEMORY REPRESENTATION ... LIKE IF I ADD A TASK IT SHOULD GET UPDATED AUTOMATICALLY IN THE MEMORY AND IT SHOULD BE RECORDED IN BACKEND SO IF I RESET THE GRAPH IT DOESNT LOOSE THE DATA .. ONLY RESETS THE ORIENTATION AND THE VISUALS TO ORIGINS.. THATS ALL... I WANT THE PROPER BACK END AND NOT A DUMB FUCK BULLSHIT DUMMY MEMORY GRAPH .. A FUCKIN REAL AND WORKING LIVE GOD DAMN MEMORY GRAPH .. U ARE MAKING ME VERY VERY VERY FRUSTRAITED'. Build: (1) live auto-emit from kanban/agent/event endpoints into memory-graph.sqlite3, (2) Reset button = visual-only, DB untouched, (3) real bulk-seed from filesystem walk (agents/projects/tasks/events/hardware), (4) target 100+ real nodes. Forge owns build, Argus owns verify, Thor orchestrates only. See task file for full spec."
kanban_status: done
---

# MC-LIVE-MEMORY-GRAPH-1: Real live persistent memory graph (replaces dummy seed)

**Owner:** Forge (build) + Argus (verify) — Thor orchestrates only
**Source:** NOFI chat 2026-06-19 14:40 Dubai — "I WANT A LIVE ACTUAL MEMORY REPRESENTATION... U ARE MAKING ME VERY FRUSTRATED"
**Priority:** CRITICAL — NOFI losing trust. Get this right.

## Why this exists

The current memory graph is a **dummy 17-node seed** that loads from `sample-graph.json` on every page load / reset. It's a static demo, not a live system. NOFI wants a **real, persistent, auto-updating** memory of NofiTech.

## The actual goal (NOFI's words, do not paraphrase)

1. **Live** — every task create/move/complete, every agent spawn, every project, every event, every hardware item **must auto-emit a node+edge** to the graph in real time. No manual `emit.sh` calls.
2. **Persistent backend** — graph data lives in SQLite (`00_company_os/memory/memory-graph.sqlite3`). Survives restart, survives reset, survives rebuild.
3. **Reset = visual reset ONLY** — clicking "Reset Graph" returns the 3D camera to its origin (position, zoom, rotation). It does **NOT** wipe the DB. It does **NOT** reseed from sample. Data is untouched.
4. **Real data, not a seed** — the graph reflects the actual current state of NofiTech. No 17-node dummy. Walk the filesystem, the kanban API, the events log, the agents dir, the projects dir, the hardware list, and build a real graph from real artifacts.
5. **Auto-grow** — when NOFI creates a new task, the graph grows by 1 node + N edges. When an agent dispatches, an edge appears. When a project ships, nodes collapse into it. **The graph IS the company's memory.**

## What needs to change

### Backend (`memory_graph_global.py` + `serve.py`)

1. **Auto-emit hook** — every existing API endpoint that creates/moves/completes a task, spawns an agent, registers a project, writes an event, MUST call `mg.add_node()` + `mg.add_edge()` before returning. Examples:
   - `POST /api/kanban` create → node `task-<id>` + edge to `agent-<assigned>` and `project-<topic>`
   - `PATCH /api/kanban/<id>` status change → edge update (or new edge representing the transition)
   - `POST /api/agents/spawn` → node `agent-<id>` + edge to `task-<id>`
   - Every event in `events.jsonl` → already a node candidate
2. **Initial bulk-import on first boot** — if the DB has <50 nodes, walk the filesystem once and seed from real artifacts:
   - `00_company_os/04_agents/*.md` → agent nodes
   - `00_company_os/01_projects/*` → project nodes
   - `00_company_os/02_tasks/*` (or mission-control/tasks) → task nodes
   - `00_company_os/03_events/events.jsonl` → event nodes
   - `01_projects/*` → project nodes
   - Hardware list → `hw-*` nodes
3. **Reset endpoint** — `/api/memory-graph/reset` (or whatever the button calls) must:
   - **NOT** wipe the DB
   - **NOT** reseed from sample
   - Just send a `{type: "reset_view"}` message to the frontend
   - The frontend receives it and resets the 3D camera to origin
4. **Sample JSON still exists** but is only used as the bootstrap if DB is empty AND no filesystem walk data exists. Even then it gets replaced by real data on first run.
5. **De-duplication** — don't add the same node twice (idempotency on `node.id`).
6. **Performance** — graph should still render 1000+ nodes smoothly. Use the existing 3d-force-graph.

### Frontend (`memory-graph.html` + `kanban.html` if linked)

1. **Reset button** — label changes to "Reset View" or "Center View". Tooltip: "Returns camera to origin. Does NOT delete data."
2. **Real-time updates** — poll the graph API every 5s (or use SSE if it's already set up). New nodes fade in, edges animate.
3. **Show count** — top corner: "247 nodes / 612 edges" updated live.
4. **No more empty state** — if the graph is genuinely empty (no data anywhere), show a clear message: "No data yet. Add a task or run the seed import."

### Kanban API integration

Every `kanban-save-result.sh` and `kanban-auto-*` script must emit memory nodes. Same for the dispatch log.

## Definition of Done

- [ ] Reset button only resets the camera, does NOT touch the DB
- [ ] Clicking "Reset Graph" 10 times in a row leaves the node count unchanged
- [ ] Creating a new task in the kanban adds a node to the graph within 5 seconds
- [ ] Moving a task to `done` adds an edge update
- [ ] The graph has **at least 100 nodes** representing real NofiTech artifacts (agents, projects, tasks, events, hardware)
- [ ] Argus verifies with a Playwright run: create a task, watch it appear in the graph, reset view, take screenshot
- [ ] All changes committed + pushed to GitHub
- [ ] Argus log references the commit hash
- [ ] Kanban shows this task as `done`

## Out of scope

- New visualization features (labels on edges, search, filters) — separate task
- Memory graph export/import — separate task
- 4D / time-travel view — separate task
- Anything that touches auth, billing, or the LAN binding — separate task

## File map (where to edit)

- `01_projects/mission-control/code/memory_graph_global.py` — add `add_node`, `add_edge` idempotency + bulk import
- `01_projects/mission-control/code/serve.py` — add auto-emit calls to all kanban/agent/event endpoints
- `01_projects/mission-control/code/memory-graph.html` — fix reset button label + behavior, add live count
- `01_projects/mission-control/code/kanban.html` — show memory count if relevant
- `01_projects/mission-control/code/scripts/bulk_seed.py` — NEW: walk filesystem, seed DB
- `00_company_os/memory/memory-graph.sqlite3` — start using it for real

## Org rule (re-stated for the record)

**Thor (this task's owner) DOES NOT WRITE CODE.** Forge writes. Argus verifies. Thor orchestrates via `kanban-delegate.sh` + `delegate_task`. If you see Thor opening a file with `patch` or `write_file`, that's a bug — call it out.
