---
task_id: MC-KANBAN-UNLIMITED-TITLE-1
title: Remove maxlength="200" on the create-task title input — NOFI wants unlimited
project: mission-control
phase: live-monitor
status: done
priority: low
created: 2026-06-17T11:23:00+04:00
created_by: thor
assigned_to: forge
approval_required: false
approval_status: approved
argus_passed: false
depends_on: [MC-KANBAN-ASSIGN-1]
blocks: []
tags: [mission-control, kanban, ui, title-limit, no-argus-needed]
kanban_status: done
---

# MC-KANBAN-UNLIMITED-TITLE-1 — Remove Title Length Limit

## NOFI's request (verbatim)
*"one last thing ... when i want to add TASK ,  task title has limited words.. remove the limit please i wan it to be unlimited."*

## The change

ONE line change in `/home/nofidofi/NofiTech-Ind/01_projects/mission-control/code/kanban.html` line 1153:

```diff
-    <input type="text" name="title" placeholder="Task title…" required maxlength="200" />
+    <input type="text" name="title" placeholder="Task title…" required />
```

That's it. Remove the `maxlength="200"` attribute. The browser will then allow unlimited characters in the title input.

## Scope (Forge only, no Argus needed)

- [ ] Make the 1-line change
- [ ] Verify with curl that the page now has no maxlength on the title input
- [ ] Commit + push
- [ ] Write a tiny forge log

## Out of scope

- NO other changes
- NO behavioral test (this is trivial; a curl-grep is enough)
- NO state.json change (Thor does that)
- NO events.jsonl change (Thor does that)

## Files to touch

- `01_projects/mission-control/code/kanban.html` (1 attribute removal)
- `00_company_os/04_agents/logs/2026-06-17/forge-mc-kanban-unlimited-title-1.md` (NEW log)

## Handoff to Forge

1. Read this task spec (short)
2. Make the change with `patch`
3. Verify: `curl -s http://192.168.0.29:8767/kanban | grep -c 'maxlength="200"'` → should be 0 (the only maxlength in the file should be removed)
4. No server restart needed (kanban.html is served as static, hard-refresh in browser picks up the change)
5. Commit + push
6. Write a 1-paragraph forge log
7. Done

REPORT BACK in 2 lines:
DONE: yes/no
COMMIT: <sha>
