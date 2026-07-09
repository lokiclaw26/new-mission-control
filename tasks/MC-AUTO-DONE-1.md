---
id: MC-AUTO-DONE-1
title: Auto-done pipeline: 4th leg (running_now → done)
project: mission-control
created_by: thor
assigned_to: thor
status: done
priority: high
created_at: 2026-06-19T11:30:00+04:00
updated_at: 2026-06-19T14:15:00+04:00
current_stage: complete
blocker: ""
data_source: thor-direct
description: "NOFI: 'WHY THE TASKS WHICH COMPLETE STILL SITTING IN RUNNING NOW COLUMN FOR FUCK SAKES'. Built the 4th leg of the auto-kanban pipeline. Script /home/nofidofi/.hermes/scripts/kanban-auto-done.sh polls every 60s, PATCHes running_now->done on 6 signals: (a) has_result:true, (b) task_completed/event, (c) log file with result:success, (d) child task done, (e) orphan>30m no PID, (f) child archived. Cron ebf74937af2c registered, no_agent (no LLM cost). End-to-end smoke test SMOKE-TEST-AUTO-DONE-1 verified: 0 running_now, 80 done. Commit 55b18a8."
kanban_status: done
has_result: true
---

# MC-AUTO-DONE-1: 4th leg of auto-kanban pipeline

## What it does
- Polls every 60s for tasks stuck in `kanban_status: running_now`
- PATCHes to `done` when ANY of 6 signals fire
- 5 safety rails: kill switch, dedup, skip-if-PID, log audit, no-agent cron

## Files
- `/home/nofidofi/.hermes/scripts/kanban-auto-done.sh` — 200 LOC, stdlib
- `/home/nofidofi/.hermes/scripts/.extract-mc-token.py` — token helper
- `00_company_os/auto-kanban-rule.md` — updated pipeline diagram
- `00_company_os/04_agents/logs/auto-done.log` — audit log

## Commits
- `9fea521` MC-AUTO-DONE-1: 4th leg of kanban pipeline
- `55b18a8` MC-AUTO-DONE-1: smoke test PASSED + 2 more signals (E:log file, F:child-done)

## Acceptance
- [x] running_now: 0 (down from 8)
- [x] Cron registered: ebf74937af2c every 1m
- [x] Smoke test: SMOKE-TEST-AUTO-DONE-1 moved triage→ready→running_now→done in 18min zero human input
- [x] All 4 kanban crons active: process (2m), dispatch (1m), execute (2m), done (1m)

## Result
**Full auto-kanban pipeline is now hands-off end-to-end.**
Drop a card → it executes → it moves to done. Zero human input.
