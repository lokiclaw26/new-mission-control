---
id: MC-015-2-DATA-AUDIT
title: Stage 15.2 — Full data-source audit and backfill
project: mission-control
created_by: nofi
assigned_to: forge
status: done
priority: normal
created_at: "2026-06-11T11:30:00+00:00"
updated_at: "2026-06-11T11:50:00+00:00"
current_stage: ship
blocker: 
data_source: real
description: Backfill real task files for Stages 13/14/15/15.1, update project status.md, extend events.jsonl. Then do a full per-field data-source audit of all 6 panels + header + Action Required.
acceptance: Dashboard shows all 5 new tasks; project status reflects current reality; 33+ events; 0 silently-stale fields.
argus_result: pass
---

## Brief
Stage 15.2 backfill + audit. Forge wrote 5 task files, updated status.md, extended events.jsonl 9→33. Argus did a 32KB per-field audit: 49 LIVE, 39 COMPUTED, 14 acceptable CONSTANT, 2 process-lifetime CONSTANT, 0 silently-stale.

## Acceptance
All deliverables verified by Argus (32,816-byte report at argus-stage152-1781177700.md). Dashboard reflects all current work.


1. `01_projects/mission-control/status.md` — updated to v1.10.1-live-version
   with `phase: verify` and a `next_action` that names the audit.
2. `00_company_os/events.jsonl` — appended events for the five tasks
   (task_created, task_assigned, work_started, argus_passed for the four
   complete ones; no argus_passed for this task until Argus signs off).
3. `00_company_os/04_agents/state.json` — all three agents pointing at the
   new Stage 15.2 assignment.

## Acceptance
- Five new real task files present (MC-013..MC-015-2).
- All 14 frontmatter fields present per file.
- events.jsonl count grows by at least 13 lines (3 per task × 4 done
  + 3 for this one, plus optional `forge_reported` for the audit handoff).
- state.json reflects Stage 15.2 assignments for forge / thor / argus.
- No `sk-` / `api_key` / `password` / `secret` strings in any new file.
- Demo data still hidden by default.
- Argus issues pass/fail verdict on the full audit.

## Notes
- `status: in_progress` — this task is the work being done right now.
- `current_stage: verify` — the stage is in the audit / verification phase,
  not a new build phase.
- `argus_result: pending` — Argus has not run on this stage yet.
- Forged by Forge; verified by Argus (forthcoming).
