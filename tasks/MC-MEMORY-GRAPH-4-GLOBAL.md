---
task_id: MC-MEMORY-GRAPH-4-GLOBAL
title: Memory Graph — promote from MC-only to full Hermes Agent memory
status: done
priority: p1
project: mission-control
created: 2026-06-17
created_by: nofi
assigned_to: forge
kanban_status: done
depends_on: []
tags: [memory-graph, global, importer, scope, hermes, hardening]
---

# Memory Graph — Global Hermes Agent Memory

## Goal
Promote the Mission Control Memory Graph to a **global Hermes Agent memory graph**
that reflects the entire NofiTech/Hermes activity (events, tasks, agents, projects,
files, sessions, decisions, tools), with Mission Control as a viewer/client.

## Scope
1. New global storage path: `00_company_os/memory/memory-graph.sqlite3` (canonical),
   with project-local `data/memory-graph.sqlite3` kept as a thin cache for the MC UI
   (no double-writes; import + serve is single-source).
2. Backward-compatible API surface at `/api/memory-graph` with new query params:
   `scope`, `project`, `agent`, `kind`, `since`, `until`, `importance`.
3. New importer module `code/memory_graph_import.py` with `--full-rebuild` and
   `--incremental` modes, ingesting:
   - `00_company_os/events.jsonl`
   - `00_company_os/memory-log.md` + `memory-log-*.md`
   - `00_company_os/04_agents/state.json`
   - `00_company_os/04_agents/logs/**/*.md`
   - `00_company_os/04_agents/events.jsonl` (agent events)
   - `01_projects/*/status.md`
   - `01_projects/*/tasks/*.md`
   - `01_projects/mission-control/data/memory-graph.json` (legacy)
   - mission-control `kanban` data
4. Namespaced stable IDs:
   `company:nofitech`, `project:<id>`, `task:<id>`, `agent:<name>`,
   `event:<event_id>`, `file:<repo_rel_path>`, `decision:<hash>`,
   `error:<hash>`, `session:<id>`, `tool:<name>`.
5. Edge kinds: `contains`, `assigned_to`, `created_by`, `updated_by`,
   `emitted_event`, `references_file`, `depends_on`, `blocked_by`,
   `resolved_by`, `caused_by`, `uses_tool`, `produced_artifact`,
   `belongs_to_project`, `happened_in_session`.
6. Safety: keep `MC_ADMIN_TOKEN` write protection, keep redactor,
   skip secrets, only ingest known Hermes/NofiTech paths.
7. UI: scope selector (Full Hermes / Mission Control / Project / Agent /
   Recent Session) + filters (node kind, edge kind, agent, project, time,
   importance). Clear banner showing current scope.
8. Tests for: global path resolution, importer (tasks/events/logs/state),
   no duplicates on re-import, no dangling edges, scoped API filtering,
   redaction still preserves task IDs.
9. Deliverables: code + tests + commit + push + verify.

## Non-Goals
- Live cross-process ingestion of arbitrary home-dir files.
- Web search / external API ingestion.
- Breaking changes to existing kanban / mission-control APIs.

## Plan (in order)
1. **Recon** (done by Thor). Identify current `memory_graph_store.py` and
   `memory_graph_api.py` shape and DB schema.
2. **Spec this task file** (done).
3. Build new global store module `code/memory_graph_global.py` (SQLite WAL,
   same schema, namespaced IDs, scoped queries, redactor preserved).
4. Build importer `code/memory_graph_import.py` with the 5 known sources +
   --full-rebuild / --incremental + safety allowlist + dedup.
5. Wire importer into `serve.py` startup hook (incremental on boot).
6. Update `memory_graph_api.py` to read from global DB + new query params +
   backwards-compatible response shape.
7. Update `memory-graph.html`:
   - Scope selector + filter bar
   - Banner: "Mission Control Memory" vs "Full Hermes Memory"
   - Filters: kind, edge, agent, project, time, importance
   - Show node counts per kind in scope
8. Tests:
   - `tests/test_global_store.py` — path resolution + scoped queries
   - `tests/test_import.py` — parse tasks/events/logs/state
   - `tests/test_import_idempotent.py` — repeated import == no dup
   - `tests/test_import_no_dangling.py` — edges always have both endpoints
   - `tests/test_scoped_api.py` — API filter correctness
   - `tests/test_redaction_preserves_ids.py` — redaction keeps task IDs
9. Run `py_compile` + `unittest`. Verify with `curl /api/memory-graph?scope=all`.
10. Commit + push.

## Files (expected)
- `01_projects/mission-control/code/memory_graph_global.py` (new)
- `01_projects/mission-control/code/memory_graph_import.py` (new)
- `01_projects/mission-control/code/memory_graph_api.py` (edit)
- `01_projects/mission-control/code/serve.py` (edit — start hook)
- `01_projects/mission-control/code/memory-graph.html` (edit — scope UI)
- `01_projects/mission-control/tests/test_global_store.py` (new)
- `01_projects/mission-control/tests/test_import.py` (new)
- `01_projects/mission-control/tests/test_import_idempotent.py` (new)
- `01_projects/mission-control/tests/test_import_no_dangling.py` (new)
- `01_projects/mission-control/tests/test_scoped_api.py` (new)
- `01_projects/mission-control/tests/test_redaction_preserves_ids.py` (new)
- `00_company_os/memory/.gitkeep` (new dir, not committed data)

## Verification checklist
- [ ] `py_compile` clean on all edited files
- [ ] All new unit tests pass
- [ ] All previous 65/65 tests still pass
- [ ] `python3 memory_graph_import.py --full-rebuild` exits 0
- [ ] `curl /api/memory-graph?scope=all` returns non-empty
- [ ] `curl /api/memory-graph?scope=project&project=mission-control` works
- [ ] `curl /api/memory-graph?agent=forge` works
- [ ] No secrets in any log/output
- [ ] Banner shows correct scope label in browser

## Done definition
- [ ] Code on disk
- [ ] Tests pass
- [ ] API responds with global data
- [ ] UI shows scope selector + banner
- [ ] Git committed + pushed
- [ ] Report written: STATUS / CHANGED / TESTED / ARGUS / BLOCKERS / NEXT
