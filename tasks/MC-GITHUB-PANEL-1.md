---
id: MC-GITHUB-PANEL-1
title: "Add GitHub Connection panel to Mission Control (Section 9)"
project: mission-control
created_by: thor
assigned_to: forge,argus
status: done
priority: high
created: 2026-06-16
updated: 2026-06-16T11:56:58Z
current_stage: "sprint-1-add-panel"
blocker: ""
description: |
  NOFI directive 2026-06-16 15:50 local. Add a new panel (Section 9) to
  Mission Control that shows the GitHub connection status, the cron job
  state, the last run outcome, and whether the last push succeeded.

  SCOPE (explicit, no hero mode):
  - New endpoint /api/data/github in serve.py
  - New Section 9 in mission-control.html
  - Update ~/.hermes/scripts/github-push-nofitech.sh to write a status
    JSON file to ~/.hermes/cron-output/github-push-nofitech/last_run.json
  - DO NOT modify any other endpoint or section
  - DO NOT touch DIY/RGV1 code
  - DO NOT change the existing 8 panels
  - Backups of serve.py and mission-control.html are at:
    01_projects/mission-control/code/backups/pre-github-panel-2026-06-16/

acceptance: |
  1. GET /api/data/github returns 200 with JSON containing:
     - repo.url, repo.last_push_at, repo.total_commits_on_main
     - local.branch, local.last_commit_sha, local.unpushed_commits
     - cron.job_id, cron.name, cron.schedule, cron.next_run
     - cron.last_run, cron.last_outcome (one of: success, no_changes, failed)
     - cron.last_message
     - status: ok | behind | failed
  2. Section 9 in mission-control.html renders without JS errors
  3. Running the auto-push script updates last_run.json
  4. The page shows this panel in < 2s after load
  5. Existing 10 endpoints still return 200 (no regression)
  6. The 8 existing panels still render correctly
  7. Backups are in place (pre-github-panel-2026-06-16/)

evidence: ""
argus_result: pending
data_source: real
---

# MC-GITHUB-PANEL-1: GitHub Connection panel

## What NOFI asked for
- A new section in Mission Control showing GitHub connection status
- Status of the cron job (next run, last run, outcome)
- What was the state at the end of last run
- Was the push successful or failed

## Why
The cron job runs unattended every 6h. NOFI needs visibility into whether
it is working without having to ssh in and check cron logs.

## Implementation outline

### 1. Auto-push script change
File: `~/.hermes/scripts/github-push-nofitech.sh`
- After the existing push logic, write a status JSON to:
  `~/.hermes/cron-output/github-push-nofitech/last_run.json`
- The JSON has: ts, outcome (success|no_changes|failed), duration_ms,
  files_changed, commit_sha, message, error

### 2. New endpoint in serve.py
- `def data_github():` reads from:
  - git remote URL (origin)
  - GitHub API for repo last push + total commits
  - git log for unpushed commits (commits on local main not on origin/main)
  - `~/.hermes/cron-output/github-push-nofitech/last_run.json` for cron state
  - `hermes cron list` (parsed) for next run
- Return JSON (see acceptance criteria)

### 3. New Section 9 in mission-control.html
- After Section 8 (Logs/Health), add a new `<section>` block
- Has a fetch to /api/data/github
- Renders: repo URL, last push, unpushed count, cron state, last outcome
- Uses existing color tokens: green=ok, amber=behind, red=failed

## RULES (no hero mode, no scope creep)
- DO NOT modify any other section/endpoint
- DO NOT touch DIY or RGV1 code
- DO NOT remove any existing functionality
- DO write the new code as ADDITIVE only
- DO use the existing color tokens and styles
- Backups are in place — restore from them if anything breaks

## VERIFICATION

curl http://localhost:8767/api/data/github should return valid JSON.

For regression: all 10 existing endpoints should still return HTTP 200.

## RETURN TO PARENT

Summary with:
- New endpoint: /api/data/github (200, fields returned)
- New section: 9 GitHub Connection (rendered OK, shows what)
- Script change: writes last_run.json (what outcome)
- Regression: all 10 existing endpoints still 200
- Any blockers

<!-- Stage 20 complete: GitHub panel shipped -->
