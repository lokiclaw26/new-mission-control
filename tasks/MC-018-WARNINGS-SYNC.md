---
id: MC-018-WARNINGS-SYNC
title: Stage 18 — Single source of truth for warnings (data_logs sync with count)
project: mission-control
created_by: nofi
assigned_to: forge
status: done
priority: high
created_at: "2026-06-11T12:50:00+00:00"
updated_at: "2026-06-11T13:30:00+00:00"
current_stage: ship
blocker: ""
data_source: real
description: "Bug: data_overview() shows 'Warnings: 1' (counted from all .md files in 04_agents/logs/ with level=warn) but data_logs() events array has no warn-level rows (the 20-event cap pushes warn files out of view). The Stage 17 Warnings panel reads only from logs.events, so it shows '0 warn · 1 log · 0 task' + 'all systems nominal' even though app_health=degraded. Fix: change data_logs() so the warnings count and events list come from a SINGLE scan, and the events list always includes ALL warn-level entries (with the 20-cap applying only to info-level events). Add a separate `warnings_list` array to /api/data/logs response that lists every warn-level entry, then make renderWarnings() read from BOTH that array AND logs.events AND overview.warnings.breakdown so the panel always matches the count."
acceptance: "data_logs() returns a top-level 'warnings_list' array with ALL warn-level log entries (no cap). The events array may cap at 20 info-level entries but must include all warn entries too. Overview 'Warnings: 1' + Logs/Health 'Warnings: 1' + new Warnings panel '1 warn · 0 log' must all match. Dashboard shows the 1 actual warn entry (test-warn-argus.md smoke test from Stage 4) with a 'Send fix order to Thor' button. The header 'app_health: degraded' reason now matches the panel content. No console errors. No secrets exposed. start-mc.sh still works. All existing endpoints unchanged in shape (new field added, none removed)."
argus_result: pass
---

## Brief
The data flows are: Overview count = scan all .md files for level=warn. Logs count = scan all .md files for level=warn. UI events = top 20 by mtime (filters out warn because it's older than the 20 most recent). New Warnings panel = reads events array only. Mismatch.

## Acceptance details
- serve.py: in data_logs(), change the scan to: collect ALL warn-level entries into a `warnings_list` array (no cap, no time filter), collect ALL error-level entries into an `errors_list` array, collect the most-recent-20 info-level entries into the `events` array. Top-level `warnings: N` and `errors: N` counts derive from warnings_list and errors_list lengths.
- serve.py: response now includes `warnings_list: [...]` and `errors_list: [...]` keys
- mission-control.html renderWarnings: read from logs.warnings_list, logs.errors_list, AND overview.warnings.breakdown. Always show every entry in warnings_list + errors_list as a row.
- mission-control.html Logs/Health section: also display the warnings_list (no more "0 warn" in the count column when 1 actually exists)
- Mission Control app_health reason must now read "1 warning(s) in log" AND the panel must show that 1 warning

## Constraints
- Stdlib Python only. No new imports if avoidable.
- No breaking changes to existing /api/* GET response shapes (only ADD new keys `warnings_list` and `errors_list`)
- No changes to POST /api/data/order
- No changes to any other panel
- No auth, no token usage, no public internet
- No demo data, no fake data
- Server restart required (serve.py change)
