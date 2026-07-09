---
task_id: MC-KANBAN-5-RESULT-POPUP
title: Add "View Result" button on Done cards + show inline result on cards with results
type: feature
priority: high
status: done
kanban_status: done
assignee: forge
argus_passed: true
completed: 2026-06-17T15:58:00+04:00
created: 2026-06-17T15:45:00+04:00
created_by: thor
approval_required: true
depends_on: [MC-KANBAN-4-WIRE-PROTOCOL]
---

## Problem (reported by NOFI 2026-06-17 ~15:40 Dubai)

> "the card with quick health check .. i asked for the reply ... why the card moved to done has no reply or explination ... how can i find my results ... either it should be there or there should be a result button to click and see a pop up with the results .... FIX THIS"

## Root cause

When Thor/Forge/Argus completes a task, the result is:
- Emitted to chat (visible at the moment)
- Sometimes appended to events.jsonl (not user-friendly)
- Sometimes written to the task file body (inconsistent)
- **NEVER surfaced back to the kanban card**

The user has to dig through task files or event logs to find the answer. For a card that says "do a health check and reply", the reply is the most important thing — and it's invisible.

## Required fix

### Part A: Store results in a structured way
When a task is moved to `done`, the result should be saved as a `## Result` section in the task file (above the original body), with a marker like:

```markdown
## Result
**Date:** 2026-06-17T15:38:00+04:00 Dubai
**By:** thor
**Status:** ALL GOOD (or specific findings)

[actual result text — markdown supported]

---
[original body below]
```

Forge should:
- Create a helper script `/home/nofidofi/.hermes/scripts/kanban-save-result.sh` that:
  - Takes `<TASK_ID> "<result_text>" [status]`
  - Inserts a `## Result` section right after the frontmatter `---` block
  - Appends a `task_result_recorded` event
  - Updates the task file to mark `has_result: true`
- Update `/home/nofidofi/.hermes/scripts/kanban-set-state.sh` to optionally accept a result string:
  - `kanban-set-state.sh <TASK> done "" ""` — no result (current behavior)
  - `kanban-set-state.sh <TASK> done "" "" "<result_text>"` — saves result before moving to done

### Part B: Kanban UI — show results
Two UI changes, both required:

1. **On the card itself:** If the task has a `## Result` section, show the first 1-2 lines as a teaser at the bottom of the card (truncated, with `...` if longer).

2. **View Result button:** If the task has a result, show a small `📋 Result` button at the bottom of the card. Clicking it opens a modal popup with:
   - The full result text (rendered as markdown)
   - Date and actor info
   - Close button
   - The popup should be styled to match the existing dark theme + gold accents

3. **No-result state:** If the task has no `## Result` section, do NOT show the button. Card just looks normal.

### Part C: Migration for existing Done cards
For the health check task (MC-KANBAN-CREATE-20260617112048-7836CE) and any other Done cards missing results:
- The current health check result is in Thor's chat reply. Forge should write the `## Result` section into the task file with the actual health check output from this conversation:
  - HTTP / = 200, /kanban = 200
  - Server PID 230215, CPU 0.3%, MEM 0.2%, uptime 3h 48min
  - 6 endpoints all 200: /api/data/agents, /tasks, /projects, /logs, /kanban, /github
  - 3 endpoints 404 (state, warnings, kanban/columns) — pre-existing, not bugs
  - No errors in /tmp/mc-serve.log
  - Disk: 4.2M, git HEAD: 4d51823
  - Verdict: ALL GOOD

This backfill must be one-shot. Do NOT touch other Done cards unless they are missing results from this conversation.

## NOT in scope
- DO NOT add new columns
- DO NOT change the column semantics
- DO NOT redesign the kanban
- DO NOT touch the parser
- DO NOT touch serve.py endpoints that are working
- DO NOT add cron
- DO NOT change existing kanban-set-state.sh semantics (only ADD a result parameter, don't break the existing 3-arg form)

## Acceptance criteria

### Helper script
- [ ] `kanban-save-result.sh` exists and is executable
- [ ] `kanban-save-result.sh <TASK_ID> "<result>" [status]` inserts `## Result` section after frontmatter
- [ ] If task already has a `## Result`, append a new dated section (don't lose the old one)
- [ ] `task_result_recorded` event appended
- [ ] `has_result: true` set in frontmatter
- [ ] Extended `kanban-set-state.sh` accepts an optional 5th argument as result text

### Kanban UI
- [ ] Done cards with results show a "📋 Result" button at the bottom
- [ ] Clicking the button opens a modal with full result, date, actor
- [ ] Done cards with results show a 1-2 line teaser on the card itself
- [ ] Cards without results look normal (no button, no teaser)
- [ ] Modal can be closed with X button, Escape key, or click outside
- [ ] Modal is styled consistently with the existing dark theme
- [ ] Modal renders markdown (lists, code, bold, etc.)

### Migration
- [ ] MC-KANBAN-CREATE-20260617112048-7836CE has a `## Result` section with the actual health check findings
- [ ] Card shows the teaser + View Result button
- [ ] Clicking the button shows the full result

### Regression
- [ ] All other cards still render normally
- [ ] Drag/drop still works
- [ ] Inline create still works
- [ ] Polling still works
- [ ] All existing endpoints still return 200
- [ ] Mission Control loads on / and /kanban

## Argus checks
- [ ] Helper script works (save result, append result, no-result case)
- [ ] UI shows button only for cards with results
- [ ] Modal opens, shows result, closes cleanly
- [ ] Teaser is shown on the card body
- [ ] No regression on cards without results
- [ ] Mission Control still loads
- [ ] Playwright behavioral test: click a Done card with result → modal appears → contains the result text → close button works
- [ ] Commit created, pushed (or auto-sync)

## Out of scope
- DO NOT add new columns
- DO NOT change column semantics
- DO NOT redesign kanban
- DO NOT touch parser
- DO NOT touch serve.py working endpoints
- DO NOT add cron
- DO NOT change existing kanban-set-state.sh semantics

## Notes for Forge
- The kanban page is `/home/nofidofi/NofiTech-Ind/01_projects/mission-control/code/kanban.html`
- Existing modal patterns may already exist (e.g. inline create, assign popup) — match their style
- The result text can be markdown — render it in the modal
- Don't break the existing 3-arg form of `kanban-set-state.sh` — only ADD an optional 5th arg
