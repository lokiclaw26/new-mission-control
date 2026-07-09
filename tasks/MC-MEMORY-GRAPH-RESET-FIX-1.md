---
id: MC-MEMORY-GRAPH-RESET-FIX-1
title: Fix memory graph reset button leaving page blank
project: mission-control
created_by: thor
assigned_to: forge
status: done
priority: urgent
created_at: 2026-06-19T14:15:00+04:00
updated_at: 2026-06-19T14:22:30+04:00
current_stage: done
blocker: ""
data_source: nofi-bug-report
result: success
description: "NOFI clicked 'Reset Graph' on the memory-graph page. The page went blank (0 nodes, 0 edges). Button label LIES: says 'Reset to clean sample data' but actually hard-wipes. Root cause: GlobalMemoryGraphStore.reset() has no reseed logic, unlike the legacy MemoryGraphStore.reset(reseed=True) which DOES reseed from sample-graph.json. The fix is to port the legacy reseed contract to the global store. Forge: you own this. Thor already wrote a draft fix (see 'Previous attempt' below) but it was a violation of the org rule — you are the Builder. Take the draft, review it, replace it with your own if you want, and ship it under your name. Argus will verify the result."
kanban_status: done
---

# MC-MEMORY-GRAPH-RESET-FIX-1

## Bug
NOFI clicked "↻ Reset Graph" → page went blank.
- API returned `node_count: 0, edge_count: 0`
- Button label said "Reset to clean sample data" but actually hard-wiped
- Legacy `MemoryGraphStore.reset(reseed=True)` had a wipe+reseed path
- Global `GlobalMemoryGraphStore.reset()` was a no-reseed hard wipe

## Fix
Port the legacy store's `reset(reseed=True)` contract to the global store.

### Required
1. Add `reseed: bool = True` parameter (default True; False for tests)
2. After DELETE FROM nodes/edges/events, look for `sample-graph.json` in 4 well-known locations
3. Upsert each node + edge row using the existing schema
4. Append a `graph_reset` event for audit
5. Return the post-reset graph shape (not None)

### Sample file location
`/home/nofidofi/NofiTech-Ind/01_projects/mission-control/data/sample-graph.json` (12KB, 17 nodes, 25 edges)

### Schema reference
Look at `memory_graph_store.py:660-700` (legacy reset) and `memory_graph_global.py:264-355` (upsert_node/upsert_edge) for the exact row schema.

## Previous attempt (Thor-direct draft, IGNORE if you want to redo)
`/home/nofidofi/NofiTech-Ind/01_projects/mission-control/code/memory_graph_global.py` already has a draft reset() at line 672 that:
- Wipes tables
- Loads sample via `_load_sample_for_migration()` (4 locations)
- Upserts nodes via `_upsert_node_row()` + edges via `_upsert_edge_row()`
- Appends `graph_reset` event
- Returns `self.load_scoped()`

It works (rebuild from /api/memory-graph/rebuild returned 1265 nodes earlier) but the **table schema in `_upsert_node_row` may not match the actual table columns**. You MUST check the CREATE TABLE statement in `__init__` / `_migrate` of `GlobalMemoryGraphStore` and verify the INSERT column list is correct. If wrong, fix it. Argus will catch any schema mismatch.

## Files
- `code/memory_graph_global.py` — reset(), _load_sample_for_migration(), _upsert_node_row(), _upsert_edge_row()

## Acceptance (8/8)
- [ ] Click "Reset Graph" on /memory-graph page → graph renders with 17 nodes / 25 edges
- [ ] Recent Events panel shows `graph_reset` event with note
- [ ] Reset is idempotent (clicking 3 times still leaves a valid graph)
- [ ] After reset, `/api/memory-graph` returns the sample data, not empty
- [ ] /api/memory-graph/rebuild still works (regression check)
- [ ] Console: no errors
- [ ] Argus Playwright screenshot proves the page shows nodes
- [ ] Argus log: /home/nofidofi/NofiTech-Ind/00_company_os/04_agents/logs/2026-06-19/argus-MC-MEMORY-GRAPH-RESET-FIX-1.md

## NOFI's standing rule
"If I add a task in kanban will it AUTOMATICALLY run? I dont want to come here and tell you to do something which I have added there." — This task is now in the pipeline. It should go triage→ready→running_now→done automatically, with YOU doing the build, Argus doing the verify, and NO human input from Thor.
