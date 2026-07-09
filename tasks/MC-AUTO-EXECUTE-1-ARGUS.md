---
id: MC-AUTO-EXECUTE-1-ARGUS
title: ARGUS-VERIFY-AUTO-EXECUTE: Playwright + log inspection of the auto-execute cron
project: mission-control
created_by: forge
assigned_to: argus
status: done
priority: normal
created_at: 2026-06-18T02:34:00+04:00
updated_at: 2026-06-18T02:48:00+04:00
current_stage: verify
blocker: ""
data_source: manual
description: "Argus verify with Playwright + log file inspection. Argus runs the e2e test, confirms the log file appears with the expected content, and writes a verdict."
source: manual.argus
kanban_status: archived
---

# ARGUS-VERIFY-AUTO-EXECUTE: verify the auto-execute cron end-to-end

## Why
The previous e2e (MC-AUTO-EXECUTE-1-E2E) proved the pipeline once.
NOFI wants an independent verify: Argus inspects with Playwright + reads
the actual log files on disk to confirm the auto-execute cron actually
spawns subagents that write the right artifacts.

## What Argus should do

### 1. Log file inspection (filesystem)
- [ ] Confirm `/home/nofidofi/.hermes/scripts/kanban-auto-execute.sh` exists, executable, passes `bash -n`
- [ ] Confirm repo copy at `/home/nofidofi/NofiTech-Ind/01_projects/mission-control/scripts/kanban-auto-execute.sh` exists, identical
- [ ] Confirm `/home/nofidofi/NofiTech-Ind/01_projects/mission-control/scripts/test_auto_execute.sh` exists, executable
- [ ] Run `/home/nofidofi/NofiTech-Ind/01_projects/mission-control/scripts/test_auto_execute.sh` — all 15 assertions must PASS
- [ ] Confirm `00_company_os/04_agents/logs/auto-execute.log` has recent dispatch lines (last hour)
- [ ] Confirm `00_company_os/04_agents/logs/2026-06-18/forge-MC-AUTO-EXECUTE-1-E2E.md` exists, contains `result: success`
- [ ] Confirm `00_company_os/events.jsonl` has a `task_completed` entry for `MC-AUTO-EXECUTE-1-E2E`

### 2. Cron registration (Hermes)
- [ ] `hermes cron list` shows `kanban-auto-execute` with `Schedule: every 2m` and `[active]`

### 3. Playwright UI check (if live UI available at 127.0.0.1:8767)
- [ ] Open `http://127.0.0.1:8767/`
- [ ] Find the kanban board
- [ ] Verify `MC-AUTO-EXECUTE-1-E2E` appears in the "Done" column (or wherever the UI puts completed tasks)
- [ ] Screenshot the board, save to `00_company_os/04_agents/logs/2026-06-18/argus-MC-AUTO-EXECUTE-1-ARGUS-screenshot.png`

### 4. Verdict
- [ ] Write a verdict file at `00_company_os/04_agents/logs/2026-06-18/argus-MC-AUTO-EXECUTE-1-ARGUS-verdict.md` with:
  - PASS or FAIL per check above
  - One-line final verdict: `verdict: pass` or `verdict: fail`
- [ ] PATCH this task to `status: done` if verdict=PASS, or `status: blocked` if FAIL (with reason in body)
- [ ] Append a `task_completed` or `task_blocked` event to events.jsonl

## Notes
- Dropped manually at 2026-06-18T02:34 by forge.
- The auto-execute cron should pick this up within 2 min and spawn an argus subagent.
- If the UI is unavailable, Playwright checks become "skipped (UI offline)" — not failures.
