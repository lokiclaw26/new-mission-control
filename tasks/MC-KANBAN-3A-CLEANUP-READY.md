---
task_id: MC-KANBAN-3A-CLEANUP-READY
title: Cleanup Ready column — move 7 stale tasks to Done
type: chore
priority: high
status: done
kanban_status: done
assignee: forge
argus_passed: true
completed: 2026-06-17T12:45:00+04:00
created: 2026-06-17T12:30:00+04:00
created_by: thor
approval_required: false
tags: [kanban, cleanup, ready-column]
---

## Background

NOFI observed Ready column has 11 cards, 7 of them stale. NOFI's question:
> "check the ready column and if any task has no action to process can be moved to DONE"

## Thor's analysis (2026-06-17 12:30 Dubai)

After inspecting all 11 Ready cards:

### ✅ Move to Done (7 tasks) — clearly shipped, no action pending

All 7 have:
- `task_completed` event appended (Argus verified pass)
- Task is shipped and live in production
- File `status: in_progress` is a leftover from before the explicit-state protocol

| # | Task ID | Last event | Note |
|---|---------|------------|------|
| 1 | MC-KANBAN-1 | task_completed | Kanban board shipped |
| 2 | MC-KANBAN-2 | task_completed | Dual-format parser shipped |
| 3 | MC-KANBAN-MOVE-1 | task_completed | New page + sidebar nav shipped |
| 4 | MC-KANBAN-BUGFIX-1 | task_completed | 3 Kanban bugs fixed |
| 5 | MC-KANBAN-BUGFIX-2 | task_completed | Real scroll/poll bug fixed (Playwright verified) |
| 6 | MC-KANBAN-BUGFIX-3 | task_completed | Lane duplication fixed (Playwright verified) |
| 7 | MC-KANBAN-ASSIGN-1 | task_completed | Click-to-assign shipped (Argus PASS) |

**Wait** — let me recount. The Ready column I just inspected had 11 cards. Let me list all of them and mark which to move:

Looking at the API dump from 12:30 Dubai:
1. **MC-KANBAN-3-EXPLICIT-RUNNING-STATE** → KEEP (this is the current task being orchestrated by Thor)
2. **MC-KANBAN-RUNNING-NOW-1** → ✅ MOVE TO DONE
3. **MC-KANBAN-UNLIMITED-TITLE-1** → ✅ MOVE TO DONE
4. **MC-KANBAN-ASSIGN-1** → ✅ MOVE TO DONE
5. **MC-KANBAN-BUGFIX-3** → ✅ MOVE TO DONE
6. **MC-AUTO-PROCESS-1** → ✅ MOVE TO DONE
7. **MC-KANBAN-BUGFIX-2** → ✅ MOVE TO DONE
8. **MC-KANBAN-BUGFIX-1** → ✅ MOVE TO DONE
9. **MC-022-ON-DEMAND-1** → ⚠ DO NOT MOVE (Thor will ask NOFI)
10. **DIY-011** → ⚠ DO NOT MOVE (Thor will ask NOFI)
11. **MC-004-tasks-panel** → ⚠ DO NOT MOVE (Thor will ask NOFI)

### ⚠ Leave in Ready (4 tasks) — Thor will ask NOFI
- **MC-KANBAN-3-EXPLICIT-RUNNING-STATE** (current task — do not touch)
- **MC-022-ON-DEMAND-1** — `status: assigned`, no `task_completed` event. Was scheduled, never finished. NOFI's call.
- **DIY-011** — Format B file, `task_completed` event exists BUT DIY project is paused. May still be valid work.
- **MC-004-tasks-panel** — Stage 6, 0 events, never started. Still valid work.

## Required actions

### Forge
1. For each of the 7 tasks above, update both:
   - Task file frontmatter: `status: complete`
   - Use the helper script to move kanban to done:
     ```
     bash /home/nofidofi/.hermes/scripts/kanban-set-state.sh <TASK_ID> done "" ""
     ```
2. For each move, the script auto-appends a `task_completed` event (safe to have duplicate, idempotent)
3. After all 7 are moved, verify with:
   ```
   curl -s http://192.168.0.29:8767/api/data/kanban | python3 -c "import json,sys; d=json.load(sys.stdin); ready=[c for c in d['columns'] if c['id']=='ready'][0]; print('Ready count:', ready['count']); [print(' -', t['task_id']) for t in ready['tasks']]"
   ```
4. Expected Ready count after: 4 (MC-KANBAN-3, MC-022-ON-DEMAND-1, DIY-011, MC-004-tasks-panel)
5. Expected Done count after: 39 + 7 = 46

### Argus
1. Verify all 7 task files have `status: complete` on disk
2. Verify `/api/data/kanban` shows ready=4, done=46
3. Verify the 4 untouched tasks are still in Ready with original status
4. Verify no new commits broke anything
5. Verify drag/drop and inline create still work
6. Behavioral test: load `/kanban` in Playwright, screenshot Ready column — should show 4 cards

## Acceptance criteria

- [ ] 7 task files have `status: complete` in frontmatter (use grep)
- [ ] `/api/data/kanban` reports ready=4, done=46
- [ ] The 4 untouched tasks still have original status and kanban_status
- [ ] Kanban page still loads (HTTP 200)
- [ ] Drag/drop still works (Playwright)
- [ ] Inline create still works (Playwright)
- [ ] Commit created with descriptive message
- [ ] All Argus checks PASS

## Out of scope (do NOT do)

- DO NOT move MC-022-ON-DEMAND-1 (NOFI decision pending)
- DO NOT move DIY-011 (NOFI decision pending)
- DO NOT move MC-004-tasks-panel (NOFI decision pending)
- DO NOT move MC-KANBAN-3-EXPLICIT-RUNNING-STATE (current task)
- DO NOT touch any other columns
- DO NOT add new features
- DO NOT touch the parser or serve.py
- DO NOT add cron
