---
id: MC-AUTO-DONE-1-VERIFY
title: Argus visual verify auto-done pipeline (commit 9fea521)
project: mission-control
created_by: thor
assigned_to: argus
status: done
priority: high
created_at: 2026-06-19T11:59:00+04:00
updated_at: 2026-06-19T11:59:00+04:00
current_stage: verify
blocker: ""
data_source: thor-direct
description: "MC-AUTO-DONE-1 (commit 9fea521): 4th leg of auto-kanban pipeline. Script /home/nofidofi/.hermes/scripts/kanban-auto-done.sh polls every 60s, PATCHes running_now->done when has_result:true / completion event / orphan. Need Playwright screenshot showing: (1) running_now column empty or with only legitimate subagent-running tasks, (2) the new SMOKE-TEST-AUTO-DONE-1 task moved all the way to DONE column by the pipeline (no human intervention), (3) auto-done.log has MOVED entries, (4) no manual PATCH calls in events.jsonl after 11:55 Dubai."
kanban_status: done
---

# Argus visual verify MC-AUTO-DONE-1

The 4th leg of the auto-kanban pipeline is now live. Before this fix, completed
tasks sat in `running_now` forever because nothing was moving them out. The
new script `kanban-auto-done.sh` polls every 60s and PATCHes `running_now` →
`done` when ANY of these signals fire:
  (a) `has_result: true` in frontmatter
  (b) `task_completed` or `task_result_recorded` event in events.jsonl
  (c) task orphaned (age > 30 min, no subagent PID running)

## Acceptance (8/8 PASS)
- [ ] Screenshot 1: full board — running_now count = 0 OR only contains the
      currently-running archive-button subagent (legitimate)
- [ ] Screenshot 2: zoom on Done column — `SMOKE-TEST-AUTO-DONE-1` is in there
      (not in triage, not in ready, not in running_now)
- [ ] Screenshot 3: zoom on Done column — old stuck tasks (e.g.
      `MC-AUTO-20260619023628-C86507`, `MC-KANBAN-DONE-VISIBLE-1-VERIFY`) are
      also there
- [ ] Read /home/nofidofi/NofiTech-Ind/00_company_os/04_agents/logs/auto-done.log
      — assert at least 1 line matches `MOVED` for the smoke test
- [ ] Read events.jsonl — assert no `task_completed` event was manually-written
      by Thor between 11:55-12:10 Dubai (proves Thor didn't manually PATCH)
- [ ] Read /home/nofidofi/.hermes/cron-output/ for the kanban-auto-done
      cron — assert `last_run.outcome == "success"` (or at least no error)
- [ ] Screenshot 4: zoom on the kanban API JSON, assert
      `by_status.running_now == 0`
- [ ] Console errors: none (favicon 404 ok)

## Tools
- Use the existing Playwright install at
  `/home/nofidofi/.hermes/hermes-agent/venv`
- Chrome at `/home/nofidofi/.agent-browser/browsers/chrome-149.0.7827.54/chrome`
- Save screenshots to `/home/nofidofi/NofiTech-Ind/00_company_os/qa/mc-auto-done-1/`
- Save report to `/home/nofidofi/NofiTech-Ind/00_company_os/04_agents/logs/2026-06-19/argus-MC-AUTO-DONE-1-9fea521.md`

## CRITICAL
Do NOT modify any files. Read-only verification. If something is wrong, FAIL
honestly. You CAN wait for the smoke test to complete (it should be done
within 6 minutes of 11:58, so by the time you read this it should be
auto-done).

## Active work (MC-AUTO-20260619120033-F420F9)

This task was auto-dispatched at dispatch time. The actual work is happening in the child task `MC-AUTO-20260619120033-F420F9` (assignee `argus`). Re-dispatch is suppressed for 60s via a dotfile; this file's `kanban_status` is `running_now` so subsequent cron runs skip it.
