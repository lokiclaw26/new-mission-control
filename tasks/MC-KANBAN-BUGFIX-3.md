---
task_id: MC-KANBAN-BUGFIX-3
title: Fix lane duplication bug + clarify "running" state semantics
project: mission-control
phase: live-monitor
status: done
priority: high
created: 2026-06-17T10:50:00+04:00
created_by: thor
assigned_to: forge, argus
approval_required: true
approval_status: approved
approval_phrase: "NOFI reported: lanes repeated 3x in Running column, tasks shown as running but actually on standby"
argus_passed: false
depends_on: [MC-AUTO-PROCESS-1]
blocks: [MC-KANBAN-FREEZE-ACCEPTANCE]
tags: [mission-control, kanban, bugfix, swimlanes, dom-selector, status-semantics]
kanban_status: done
---

# MC-KANBAN-BUGFIX-3 — Lane Duplication + Running State Semantics

## NOFI's report (verbatim, 2026-06-17 ~10:48 Dubai)
*"There is a bug in kanban page ... I see tasks running which are actually not currently running and they are on stand by waiting for next updates ... and also what the fuck is this with all the names going down as attached in the image"*

## Screenshot analysis (from NOFI's image)

The Running column shows lane headers repeating 3 times:
```
ARGUS (0)
UNASSIGNED (1)
THOR (4)
FORGE (3)
ARGUS (0)
UNASSIGNED (1)
THOR (3)
FORGE (3)
ARGUS (0)
UNASSIGNED (1)
THOR (3)
FORGE (3)
ARGUS (0)
UNASSIGNED (1)
```

3 repetitions of the same 4 lanes (Argus, Unassigned, Thor, Forge).

## Root cause (found by Thor reading the code)

In `kanban.html` line 645 (smartRenderKanban), the smart diff code looks for existing lane divs to reuse:

```javascript
for (const laneEl of colEl.querySelectorAll(":scope > .kanban-lane")) {
  lanesByAssignee.set(laneEl.dataset.lane, laneEl);
}
```

**BUG:** The selector is `colEl > .kanban-lane` (direct child of column). But the actual DOM structure has lanes as direct children of `body` (the `.kanban-col-body` div), NOT direct children of `colEl`. So this querySelector returns NOTHING every poll. Then the code creates new lane divs (`tmp.innerHTML = renderKanbanLaneShell(...)`) without ever removing the old ones.

**Result:** After every 5-second poll, 4 more lane divs get added. After 1 minute (12 polls), 48 lane headers pile up. NOFI's screenshot shows 16 visible lanes (≈ 4 minutes of polls at 2-second visible intervals).

## Fix

Change line 645 from:
```javascript
for (const laneEl of colEl.querySelectorAll(":scope > .kanban-lane")) {
```
to:
```javascript
for (const laneEl of body.querySelectorAll(":scope > .kanban-lane")) {
```

Same for the orphan-removal block at line 684:
```javascript
for (const laneEl of Array.from(body.querySelectorAll(":scope > .kanban-lane"))) {
```
(This one already uses `body` — good.)

But wait, line 684 already uses `body` correctly. The bug is ONLY at line 645. Need to confirm by reading the full function.

## Secondary issue: "tasks in running that are on stand by"

NOFI's mental model: **Running = actively being worked on right now**
Reality: **Running = has `status: in_progress` (which means "I claimed this, not necessarily working on it right now")**

After MC-AUTO-PROCESS-1, the cron moves triage → in_progress. The card lands in Running. But no one is actually working on it until a sub-agent is spawned. So the column has tasks that are "queued for processing" rather than "being processed".

This is a semantic mismatch. The user expects Running to mean "active work". A "Queued" or "Pending" column would be more honest.

**Two options:**

**Option A — Rename "Running" to "In Progress" (cosmetic)**
- Just label change. The column still contains the same tasks.
- The 8 cards in Running are still "in progress" per their task files.
- Lowest-risk fix. But doesn't address the underlying issue.

**Option B — Add a new column "Queued" between Ready and Running**
- Tasks in `status: in_progress` go to Queued (not Running)
- Tasks in a new status (e.g. `status: in_work`) go to Running
- This requires a status mapping change in kanban_parser.py
- More invasive but more honest

**Option C — Update the status mapping to send `in_progress` to Ready, not Running**
- Move `in_progress` → Ready column
- Only `status: in_work` (new value) → Running
- Requires editing the parser

**Decision needed from NOFI.** For this task, default to Option A (cosmetic rename) — it's the safest. NOFI can request Option B or C as a follow-up.

Actually, looking at the screenshot more carefully: the "0" count for Argus lane is misleading. After my fix to the lane selector, those 0-count Argus lanes would still appear (they represent "Argus is a valid lane, just no tasks right now"). But if the duplicate is fixed, only 4 lanes show (not 12). So the "0" count for Argus is just informational, not a bug.

## Scope (2 parts)

### Part 1 — Fix lane selector (Forge)

Single line change in `/home/nofidofi/NofiTech-Ind/01_projects/mission-control/code/kanban.html`:

```diff
-      for (const laneEl of colEl.querySelectorAll(":scope > .kanban-lane")) {
+      for (const laneEl of body.querySelectorAll(":scope > .kanban-lane")) {
         lanesByAssignee.set(laneEl.dataset.lane, laneEl);
       }
```

(Or wherever the equivalent is — read the full function to find the bug.)

Also, add a forceRebuild when the kanban page loads. Currently `_kanbanForceRebuild = true` is the initial state (line 491), which means the first render does `board.innerHTML = ""` and rebuilds from scratch. So the existing duplicate lanes will be cleared on next page load. But if the user is currently looking at the page, they need to hard-refresh to see the fix.

### Part 2 — Clarify Running column header text (Forge)

The Running column header currently says "RUNNING". Change it to "IN PROGRESS" (or similar) to match the actual semantic.

In `kanban_parser.py` (or wherever the column labels are defined), change:
```python
{"id": "running", "label": "Running", ...}
```
to:
```python
{"id": "running", "label": "In Progress", ...}
```

This is cosmetic but addresses NOFI's confusion.

## Out of scope

- Adding a "Queued" column (deferred — needs NOFI approval)
- Changing the status mapping (deferred)
- Renaming any other column
- Any new features

## Acceptance criteria

- [ ] Line 645 (or equivalent) uses `body.querySelectorAll` not `colEl.querySelectorAll`
- [ ] Hard refresh the page → Running column shows exactly 4 lanes (Thor, Forge, Argus, Unassigned), each appearing ONCE
- [ ] After 5s polling, lanes do NOT duplicate (verified by waiting 30s, screenshot)
- [ ] Running column header text changed to "In Progress" (or similar)
- [ ] All 10 endpoints still 200
- [ ] No new task files modified
- [ ] Argus PASS with behavioral test (screenshot proof)

## Files to touch

- `01_projects/mission-control/code/kanban.html` (1 line change + maybe header text)
- `01_projects/mission-control/code/kanban_parser.py` (1 label change)
- Backup: `01_projects/mission-control/code/backups/pre-mc-kanban-bugfix-3-2026-06-17/`

## Handoff to Forge

1. Read this task spec
2. Read `/home/nofidofi/NofiTech-Ind/01_projects/mission-control/code/kanban.html` lines 640-700 to find the bug
3. Make backup
4. Fix the selector
5. Update the column label
6. Restart server (only needed if serve.py changed; kanban.html is served as static)
7. **Behavioral test:** open `/kanban` in headless Chrome, wait 30 seconds, take 2 screenshots 30s apart, confirm lanes don't duplicate
8. Commit + push
9. Write your log

## Handoff to Argus

1. **Behavioral test:** open the page in headless Chrome, wait 30s, take screenshots
2. Confirm: lanes appear exactly 4 times (not 12, not more)
3. Confirm: header text says "In Progress" or similar (not "Running")
4. Confirm: 5s polling doesn't cause lane duplication
5. Write argus log

## Self-criticism

The smart diff code (MC-KANBAN-BUGFIX-2) was supposed to fix scroll-reset. It shipped. But it introduced this lane-duplication bug because the lane-selector used the wrong parent. **This is the 5th behavioral bug I've shipped.** The pattern keeps repeating: I verify structurally (lines exist) but not behaviorally (does the page actually work).

For this task, I'll require a **Playwright behavioral test** as part of the acceptance criteria. No more "PASS" without screenshots.

## Open follow-ups

- "Queued" column (Option B/C) — pending NOFI decision
- Behavioral test suite for kanban — write Playwright tests for the 5 known bugs so we catch regressions
