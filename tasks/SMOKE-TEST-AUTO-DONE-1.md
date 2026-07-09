---
id: SMOKE-TEST-AUTO-DONE-1
title: SMOKE TEST: auto-done pipeline (drop + auto-move)
project: mission-control
created_by: thor
assigned_to: argus
status: done
priority: low
created_at: 2026-06-19T11:58:00+04:00
updated_at: 2026-06-19T11:58:00+04:00
current_stage: build
blocker: ""
data_source: thor-smoke-test
description: "Smoke test for the new MC-AUTO-DONE-1 pipeline. This task sits in triage. After 2m auto-process moves it to ready. After 60s auto-dispatch fires and creates a child in running_now. Auto-execute spawns a forge subagent. The subagent writes has_result:true. Auto-done should then move it to done within 60s of has_result being set."
kanban_status: done
---


## Research started (auto-process)

The auto-process cron picked up this task on 2026-06-19T12:07:49+04:00 Dubai. v1 auto-process does not perform real research yet — it just moves the card out of triage and sets the assignee via the title heuristic (research→thor, qa/test/verify→argus, else→forge; `auto_assign:` frontmatter overrides). For v2 (real LLM research), see MC-AUTO-PROCESS-1 follow-up.

# SMOKE TEST: auto-done pipeline

This task verifies the 4th leg of the auto-kanban pipeline (MC-AUTO-DONE-1).

## Expected timeline
- 0s:    drop in triage
- 2m:    auto-process moves triage→ready
- 2m60s: auto-dispatch creates child, moves parent+child to running_now
- 4m:    auto-execute spawns subagent
- 5m:    subagent writes log + has_result:true
- 6m:    auto-done moves to done  ← NEW

## Acceptance
- [ ] ends in `kanban_status: done` (NOT running_now)
- [ ] auto-done log line exists
- [ ] no Thor manual PATCH

## Active work (MC-AUTO-20260619120811-E2BCC8)

This task was auto-dispatched at dispatch time. The actual work is happening in the child task `MC-AUTO-20260619120811-E2BCC8` (assignee `argus`). Re-dispatch is suppressed for 60s via a dotfile; this file's `kanban_status` is `running_now` so subsequent cron runs skip it.
