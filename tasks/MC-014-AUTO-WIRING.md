---
id: MC-014-AUTO-WIRING
title: "Stage 14 — Automatic task and event wiring"
project: mission-control
created_by: nofi
assigned_to: forge
status: done
priority: normal
created_at: "2026-06-11T11:22:38+00:00"
updated_at: "2026-06-11T11:22:38+00:00"
current_stage: ship
blocker: ""
data_source: real
description: Stage 14 wired the task file frontmatter and events.jsonl log into the live Mission Control dashboard so that new real task files appear in the Tasks panel and new events surface in the Logs/Activity panel without code changes, plus shipped the mc_event.py stdlib helper and the task-schema.md / event-schema.md contracts.
acceptance: New real task file appears in the Tasks panel on next refresh; status/assignment changes visible; events.jsonl entries visible in the Logs panel; mc_event.py CLI works; no demo data shown by default; Argus 18432-byte verification report confirms pass.
argus_result: pass
---

## Brief
Stage 14 made Mission Control a real data surface. Forge wrote the
`mc_event.py` stdlib helper, the two schema docs (task-schema.md,
event-schema.md), and the wiring in `serve.py` so that:

1. Adding a task file under `01_projects/<project>/tasks/*.md` makes it
   appear in the Tasks panel on the next refresh.
2. Appending a JSON-Lines line to `00_company_os/events.jsonl` makes it
   surface in the Logs/Activity panel.
3. The `MC-LIVE-TEST-001` end-to-end smoke test passes.

## Acceptance
- New real task file appears in the Tasks panel on next refresh.
- Status / assignment changes visible.
- events.jsonl entries visible in the Logs panel.
- `mc_event.py` CLI works (create-task, assign, status, event, list-tasks).
- No demo data shown by default.
- Argus 18432-byte verification report confirms pass.

## Notes
- Backfilled task file: records work already shipped.
- `argus_result: pass` reflects the 18432-byte Argus report
  (`00_company_os/04_agents/logs/2026-06-11/argus-stage14-1781129814.md`).
- Forged by Forge.
