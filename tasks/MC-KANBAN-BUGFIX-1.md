---
task_id: MC-KANBAN-BUGFIX-1
title: Fix 3 Kanban bugs — stale tasks, scroll jump, form reset
project: mission-control
phase: live-monitor
status: done
priority: high
created: 2026-06-16T21:10:00+00:00
created_by: thor
assigned_to: forge, argus
approval_required: true
approval_status: approved
approval_phrase: "NOFI reported 3 bugs: stale tasks in running, scroll jumps back up, create form disappears"
argus_passed: false
depends_on: [MC-KANBAN-MOVE-1]
blocks: [MC-KANBAN-FREEZE-ACCEPTANCE]
tags: [mission-control, kanban, bugfix, scroll, form, stale-data]
kanban_status: done
---

# MC-KANBAN-BUGFIX-1 — Fix 3 Kanban Bugs

## NOFI's bug report (verbatim, 2026-06-16 ~21:08Z)
*"THERE ARE 2 ISSUES ... FIRST there are so many tasks in RUNNING and still there saying IN PROGRESS .. since all the process has stoped this is not true .... so why we have so many tasks in running section .. second issue is that when i scroll down to the bottom of the list ... the scroll jumps back up for some wierd reason .... also if i wanna add a new task the pop up disappears and seems like the kanban section is reseted .. why is that fix it"*

(3 issues, not 2 — third is the create-form issue.)

## Goal
Fix 3 concrete bugs in the Kanban page. NO new features, NO UI redesign, just bug fixes.

## Root cause analysis (done by Thor)

### Bug 1: "So many tasks in RUNNING saying IN PROGRESS"

The 10 tasks in the running column are NOT all real "currently in progress" — most are stale task files where Thor-direct task creation marked them `status: in_progress` in the YAML frontmatter, but the work has been completed and `task_completed` events were logged. The file's `status:` was never updated to `complete`.

Breakdown of the 10 running tasks:
- `MC-KANBAN-MOVE-1` — done, status: in_progress (wrong, should be complete)
- `MC-KANBAN-2-DUAL-FORMAT-PARSER` — done, status: in_progress (wrong, should be complete)
- `MC-KANBAN-1` — done, status: in_progress (wrong, should be complete)
- `MC-AGENT-LOG-FIX-1` — done, status: in_progress (wrong, should be complete)
- `MC-GITHUB-PANEL-1` — done, status: in_progress (wrong, should be complete)
- `MC-GITHUB-REPO-SETUP-1` — done, status: in_progress (wrong, should be complete)
- `MC-004-tasks-panel` — old, status: in-progress (legacy from June 10)
- `DIY-011`, `DIY-010`, `DIY-009` — legacy from June 14, genuinely in progress per their file status

**Fix:** Update the 6 MC task files' `status:` field to `complete`. Leave the 4 truly-still-in-progress files alone (DIY-009/010/011 + MC-004).

### Bug 2: "Scroll jumps back up"

When user scrolls to the bottom of the list, the page scrolls back to the top. Root cause: there is NO global `dragover` handler on the document. When the user accidentally drags an element (e.g. text selection, a card, a file), the browser's default `dragover` behavior triggers auto-scroll to make the dragged element visible. On a long page, this can cause the page to jump to the top.

The existing per-column `dragover` handler at line 543 calls `e.preventDefault()` but only fires when the cursor is INSIDE a column body. When the cursor is in the gap between columns or above/below the board, the default browser behavior takes over.

**Fix:** Add a global `document.addEventListener('dragover', e => e.preventDefault())` near the top of the script. Also add `document.addEventListener('drop', e => e.preventDefault())` to prevent the default drop behavior (which would try to navigate to the dragged URL).

### Bug 3: "Create form disappears / section resets"

When user clicks `+` on a column header, an inline create form appears. After typing a few characters (or after 5 seconds), the form disappears and the kanban section "resets" (the form is gone, cards are in a different order or scroll position).

Root cause: `loadKanban()` is called every 5 seconds via `setInterval(loadKanban, 5000)`. It does `board.innerHTML = columns.map(...).join("")` which REPLACES the entire board including any open inline-create forms. After 5s of typing, the polling fires, the board is re-rendered, and the form is wiped out.

**Fix:** Two options:
- **Option A (preferred):** Pause the polling while any inline create form is open. Add a flag `_kanbanCreateFormOpen = false` and skip the re-render if true. The first 5s after page load, the form is closed, so normal polling works. If the user opens a form, polling pauses. When form closes (submit, cancel, or click outside), polling resumes.
- **Option B:** Smarter re-render — only update cards that changed, don't replace the whole board. This is more invasive and not requested by NOFI.

## Scope (3 parts)

### Part 1 — Fix stale task statuses (Forge)

Update the `status:` field in the YAML frontmatter of these 6 task files:
1. `01_projects/mission-control/tasks/MC-KANBAN-MOVE-1.md` — `status: in_progress` → `status: complete`
2. `01_projects/mission-control/tasks/MC-KANBAN-2-DUAL-FORMAT-PARSER.md` — `status: in_progress` → `status: complete`
3. `01_projects/mission-control/tasks/MC-KANBAN-1.md` — `status: in_progress` → `status: complete`
4. `01_projects/mission-control/tasks/MC-AGENT-LOG-FIX-1.md` — `status: in_progress` → `status: complete`
5. `01_projects/mission-control/tasks/MC-GITHUB-PANEL-1.md` — `status: in_progress` → `status: complete`
6. `01_projects/mission-control/tasks/MC-GITHUB-REPO-SETUP-1.md` — `status: in_progress` → `status: complete`

**Do NOT touch:**
- `01_projects/diy-hub-v1/tasks/DIY-009.md`, `DIY-010.md`, `DIY-011.md` — genuinely in progress
- `01_projects/mission-control/tasks/MC-004-tasks-panel.md` — status in-progress, legacy from June 10 (ask NOFI if this should be cleaned up too — out of scope for this task)

After updating, the kanban parser will re-classify these 6 tasks to the `done` column (since `complete` maps to `done`).

The 6 files all have YAML frontmatter (Format A). Use `patch` for each. **CRITICAL:** preserve all other frontmatter fields and the body content. Only change the `status:` line.

### Part 2 — Fix scroll jump (Forge)

In `kanban.html`, add a global dragover/drop handler at the TOP of the script block (before `async function loadKanban()`):

```javascript
// MC-KANBAN-BUGFIX-1: suppress browser default drag behavior (was causing page
// to scroll to top when user accidentally dragged text/cards over a non-column area)
document.addEventListener('dragover', e => e.preventDefault());
document.addEventListener('drop', e => e.preventDefault());
```

These two lines are the minimal fix. Place them in the existing `<script>` block near the top.

### Part 3 — Fix create form reset (Forge)

In `kanban.html`, modify the `setInterval` polling so it skips re-render when an inline create form is open.

Find the polling line (around line 785): `_kanbanPollTimer = setInterval(loadKanban, 5000);`

Replace with logic that pauses polling while a create form is open. Recommended approach:

1. Add a state flag: `let _kanbanCreateFormOpen = false;`
2. In `toggleCreateForm(colId)` (line 707), set `_kanbanCreateFormOpen = true` when opening, `_kanbanCreateFormOpen = false` when closing.
3. Wrap the `loadKanban()` re-render in a check: if `_kanbanCreateFormOpen`, skip the board re-render but still update the timestamp.
4. Also clear the form when polling resumes (to avoid stale state).

Implementation:
```javascript
// At the top of the script:
let _kanbanCreateFormOpen = false;

// In toggleCreateForm(colId) — set the flag:
function toggleCreateForm(colId) {
  // ...existing code that shows/hides the form...
  _kanbanCreateFormOpen = true;   // when opening
  _kanbanCreateFormOpen = false;  // when closing
}

// In submitCreateTask — set the flag when form is submitted:
async function submitCreateTask(...) {
  // ...existing submit code...
  _kanbanCreateFormOpen = false;  // after successful submit
}

// In the polling — pause re-render while form is open:
_kanbanPollTimer = setInterval(async () => {
  if (_kanbanCreateFormOpen) return;  // skip re-render, keep form intact
  await loadKanban();
}, 5000);
```

ALSO: the `+` button click handler at line 563 calls `toggleCreateForm(col.id)`. Make sure clicking the button while a form is open in ANOTHER column closes the first form first. This is a UX nicety but NOFI didn't explicitly ask for it. Skip for now unless trivial.

ALSO: the existing 5s polling should NOT lose data when paused. The 5s tick will fire while the form is open, do nothing, then fire again 5s later after the form closes. No data loss — just no re-render. Once form closes, next tick re-renders.

## Out of scope
- No new Kanban features (filters, search, colors, archive UI)
- No mobile drawer
- No websocket live updates
- No task format changes
- No parser changes
- No mass-conversion of any task files
- DO NOT clean up the 4 truly-in-progress tasks (DIY-009/010/011 + MC-004) — those are real

## Acceptance criteria
- [ ] 6 task files have `status: complete` (replacing `in_progress`)
- [ ] Kanban parser re-classifies them to `done` column
- [ ] Running column count drops from 10 to 4 (or close to it)
- [ ] 2 new lines added to kanban.html: `document.addEventListener('dragover', e => e.preventDefault())` and same for `drop`
- [ ] Polling pauses while a create form is open
- [ ] User can open the create form, type a full title + assignee + priority, and the form stays open for 30+ seconds without disappearing
- [ ] After the form is submitted or cancelled, polling resumes
- [ ] All existing endpoints still 200
- [ ] No regressions: drag-drop, lanes by profile, search, 5s polling (when not in a form), 44 tasks still visible
- [ ] No new tasks created (the 44 should stay at 44)
- [ ] Argus PASS

## Files to touch
- 6 task files: `01_projects/mission-control/tasks/{MC-KANBAN-MOVE-1, MC-KANBAN-2-DUAL-FORMAT-PARSER, MC-KANBAN-1, MC-AGENT-LOG-FIX-1, MC-GITHUB-PANEL-1, MC-GITHUB-REPO-SETUP-1}.md`
- `01_projects/mission-control/code/kanban.html` (2 lines for scroll fix + ~10 lines for form pause)
- `01_projects/mission-control/code/kanban_parser.py` — NO change (status field already parsed correctly)
- Backup: `01_projects/mission-control/code/backups/pre-mc-kanban-bugfix-1-2026-06-16/`

## Handoff to Forge

1. Read the task file (this one) fully
2. Make backup of kanban.html first
3. Update the 6 task files' `status:` field (preserve everything else, use `patch` with `replace_all=False` since the line must be unique)
4. Edit kanban.html: add 2 lines for scroll fix, add ~10 lines for form pause polling
5. Restart server (only needed if serve.py changed — kanban.html is served as static, so a hard browser refresh will pick up the changes)
6. Verify with curl: `/api/data/kanban` running column count should drop to 4
7. Commit + push
8. Write your own log

## Handoff to Argus

After Forge is done:
1. Verify running column count is ≤ 5 (or whatever the actual count of truly-in-progress tasks is)
2. Verify the 6 task files now have `status: complete`
3. Verify the 4 in-progress files were NOT touched
4. Verify the 2 lines exist in kanban.html
5. Verify the form-pause logic exists
6. Write argus log with PASS/FAIL counts
7. Update state.json, commit, push

## Open follow-ups (after this task)
- MC-004-tasks-panel — old task from June 10, may or may not be done. Ask NOFI.
- MC-KANBAN-FREEZE-ACCEPTANCE — final closure (small task, no new work)
- After freeze: MC-022-ON-DEMAND-1 or whatever NOFI picks next
