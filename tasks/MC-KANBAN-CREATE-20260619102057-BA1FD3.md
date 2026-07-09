---
task_id: MC-KANBAN-CREATE-20260619102057-BA1FD3
title: a fix for DONE column in kanban .. if the task already dne and moved to the column DONE, the status still shows in progress.. this is wrong .. IT SHOULD STATE DONE and even in green color or something highlighted ... DONE ... FIX IT
project: mission-control
status: done
kanban_status: done
priority: high
created: 2026-06-19T10:20:57+00:00
created_by: thor
assigned_to: forge
current_assignment: MC-KANBAN-CREATE-20260619102057-BA1FD3
approval_required: true
approval_status: pending
---


## Research started (auto-process)

The auto-process cron picked up this task on 2026-06-19T14:23:32+04:00 Dubai. v1 auto-process does not perform real research yet — it just moves the card out of triage and sets the assignee via the title heuristic (research→thor, qa/test/verify→argus, else→forge; `auto_assign:` frontmatter overrides). For v2 (real LLM research), see MC-AUTO-PROCESS-1 follow-up.

# a fix for DONE column in kanban .. if the task already dne and moved to the column DONE, the status still shows in progress.. this is wrong .. IT SHOULD STATE DONE and even in green color or something highlighted ... DONE ... FIX IT

(Body TBD — created via Mission Control Kanban UI on 2026-06-19T10:20:57+00:00.)

## Active work (MC-AUTO-20260619142437-98B735)

This task was auto-dispatched at dispatch time. The actual work is happening in the child task `MC-AUTO-20260619142437-98B735` (assignee `forge`). Re-dispatch is suppressed for 60s via a dotfile; this file's `kanban_status` is `running_now` so subsequent cron runs skip it.
