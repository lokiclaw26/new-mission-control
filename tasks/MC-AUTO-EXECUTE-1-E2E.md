---
id: MC-AUTO-EXECUTE-1-E2E
title: E2E-AUTO-EXECUTE: verify the kanban-auto-execute cron actually spawns a subagent and writes a log
project: mission-control
created_by: forge
assigned_to: forge
status: in_progress
priority: normal
created_at: 2026-06-18T02:30:00+04:00
updated_at: 2026-06-18T02:30:00+04:00
current_stage: build
blocker: ""
data_source: manual
description: "Drops a fresh card with assigned_to: forge. The auto-execute cron (every 2m) should pick it up and spawn a subagent within ~2 min. Subagent's job: write a hello log file and mark this task done."
source: manual.e2e
kanban_status: archived
---

# E2E-AUTO-EXECUTE: e2e verification of the auto-execute cron

## Why
The auto-execute cron (every 2 min) was built but the previous tests only
proved the safety rails in isolation. This is the live-system e2e proof:
real cron tick, real subagent, real log file, real PATCH.

## What the subagent should do
1. Write a hello log file at `00_company_os/04_agents/logs/2026-06-18/forge-MC-AUTO-EXECUTE-1-E2E.md` with `result: success`
2. PATCH this task to status=done
3. Append a `task_completed` event to `00_company_os/events.jsonl`

## Acceptance
- [ ] Log file exists at the expected path
- [ ] Log file contains `result: success`
- [ ] Task frontmatter shows `status: done` and `kanban_status: done`
- [ ] events.jsonl has a new task_completed line for this task_id

## Notes
- This task is itself dropped by an auto-execute cron subagent (forge).
- Dropped manually at 2026-06-18T02:30 by the previous forge subagent.
