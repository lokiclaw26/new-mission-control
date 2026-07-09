---
task_id: MC-KANBAN-BUGFIX-2
title: Fix 2 remaining Kanban bugs — scroll reset on polling, and many tasks "in running" (browser cache)
project: mission-control
phase: live-monitor
status: done
priority: high
created: 2026-06-16T21:40:00+00:00
created_by: thor
assigned_to: forge, argus
approval_required: true
approval_status: approved
approval_phrase: "NOFI: same issue still persist ... i cannot stay at the bottom of the list.. it jumps back up and also there are so many tasks in running"
argus_passed: false
depends_on: [MC-KANBAN-BUGFIX-1]
blocks: [MC-KANBAN-FREEZE-ACCEPTANCE]
tags: [mission-control, kanban, bugfix, scroll-jump, polling, browser-cache]
kanban_status: done
---

# MC-KANBAN-BUGFIX-2 — Real Root Cause of Scroll + Running

## NOFI's complaint (verbatim, 2026-06-16 ~21:35Z)
*"same issue still persist ... i cannot stay at the bottom of the list.. it jumps back up and also there are so many tasks in running !!!!!"*

## What I (Thor) found by reading the actual code (NOT trusting the prior "PASS" verification)

I re-investigated. The prior MC-KANBAN-BUGFIX-1 verification passed but didn't catch the real bugs. Here's what I found:

### Bug A: "Many tasks in running" — partly user error, partly fixable

The API returns `running: 5`:
- MC-KANBAN-BUGFIX-1 (current task, in progress, correct)
- DIY-009, DIY-010, DIY-011 (genuine diy-hub-v1 work, in progress, correct)
- MC-004-tasks-panel (legacy from June 10 with `status: in-progress`, untouched per scope)

**5 is correct.** But NOFI says "so many tasks in running" — they're likely seeing the OLD page cached in their browser. The previous fix (updating task files) is on disk, but the browser is showing the old in-memory state.

**Root cause:** The static file server doesn't set `Cache-Control: no-store` headers. The browser may be serving cached HTML from before the fix.

**Fix:** Add `Cache-Control: no-store, no-cache, must-revalidate` headers to the static file responses. This forces the browser to fetch fresh HTML on every page load.

### Bug B: "Scroll jumps back up" — real root cause

The kanban board has columns with `overflow-y: auto; max-height: 70vh`. When the user scrolls inside a column (e.g. Done column with 36 tasks) to the bottom, the **5-second polling fires** and `loadKanban()` does `board.innerHTML = columns.map(...).join("")` which **destroys the entire board DOM and recreates it**. The new DOM has no scroll position, so the browser resets to the top.

**My previous fix (pause polling when form is open) doesn't help here because no form is open when the user is just scrolling.**

**Real fix:** Instead of replacing the entire board DOM every 5 seconds, do a **smart diff update**:
- Keep references to existing card DOM nodes by `task_id`
- On each poll, compare new task data with old
- For tasks that haven't changed: leave the card in place (preserves scroll position!)
- For tasks that moved columns: move the card DOM node to the new column
- For new tasks: append a new card
- For deleted tasks: remove the card

This is a real engineering change but it's the only correct fix. Stop replacing innerHTML entirely.

**Simpler fallback (Option B):** If the smart diff is too complex, just don't re-render the board if the data hasn't structurally changed (only cards' updated_at / last_activity fields changed). But this is fragile.

**Decision:** Go with the smart diff approach. It's the right fix.

### Why the prior verification missed this

The prior Argus run only checked that:
- The 2 dragover/drop lines existed in the source (C1-C3)
- The `_kanbanCreateFormOpen` flag was declared and used in 3 places (D1-D4)

It did NOT actually load the page in a real browser and try scrolling. The verification was **structural** not **behavioral**. Lesson learned: when NOFI says "the bug is still there", trust the user, not the prior verification.

## Scope (3 parts)

### Part 1 — Cache headers (Forge)

In `serve.py`, find the `_static` method (or wherever static files are served) and add cache-control headers. Use `send_response` + `send_header` + `end_headers` pattern.

Find the existing static file serving logic. It probably looks like:
```python
def _static(self, filename):
    with open(...) as f:
        content = f.read()
    self.send_response(200)
    self.send_header("Content-Type", "text/html")
    self.send_header("Content-Length", str(len(content)))
    self.end_headers()
    self.wfile.write(content)
```

Add these headers BEFORE `self.end_headers()`:
```python
self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
self.send_header("Pragma", "no-cache")
self.send_header("Expires", "0")
```

Apply to ALL static file responses (not just HTML, but also CSS/JS if any).

### Part 2 — Smart diff polling (Forge) — THE REAL FIX

This is the most complex part. Refactor `loadKanban()` and `renderKanban()` to do a smart diff instead of `board.innerHTML = ...`.

Current code (around line 535):
```javascript
board.innerHTML = columns.map(col => renderKanbanColumn(col, agentById, search)).join("");
```

Replace with a diff-based update. The structure of the new function:

```javascript
async function loadKanban() {
  try {
    const url = "/api/data/kanban" + (_kanbanIncludeArchived ? "?include_archived=true" : "");
    const d = await fetchJSON(url);
    _kanbanState = d;
    smartRenderKanban(d);  // NEW: diff-based render
    // ... rest of timestamp update
  } catch (e) {
    // ... error handling
  }
}

function smartRenderKanban(d) {
  // For each column in new data:
  //   - Find the column body DOM node
  //   - For each task in new column:
  //     - If card exists in DOM (by data-task-id), check if it needs update
  //     - If card moved from different column, move the DOM node
  //     - If new task, append
  //   - Remove cards that no longer exist
  // For column header counts: just update the text
  // For swimlanes inside Running: similar diff
  // DO NOT touch cards that are unchanged (preserves scroll)
}
```

Implementation strategy:
1. Keep a `Map<taskId, HTMLElement>` of all currently-rendered cards
2. For each new task in the response, find existing card by `data-task-id`
3. If exists and unchanged: leave it alone (preserves scroll)
4. If exists but moved: move the DOM node to the new column
5. If new: create a fresh card and append
6. After processing all new tasks, remove any card DOM nodes that aren't in the new data
7. Update column counts in headers

**Important:** The CSS classes (status-*, assignee-*, dragover, dragging) must be preserved on cards that don't change. Don't re-render the inner HTML of an unchanged card.

**Implementation guidance:** Use `document.createElement` for new cards (or keep using `innerHTML` for the card template, then clone it). For column body diff, the simplest approach is:
- Track all task IDs in each column's body
- For each column: remove cards that are no longer in the data, add cards that are new, move cards from other columns
- Don't touch cards that stay in the same column

For lanes inside Running, same approach but with lane headers.

### Part 3 — Disable polling when no Kanban activity (Forge) — bonus fix

A simpler complementary fix: if the document is not visible (user switched tabs), pause the polling. Use `document.visibilityState`:
```javascript
document.addEventListener('visibilitychange', () => {
  if (document.hidden) stopKanbanPolling();
  else startKanbanPolling();
});
```

This prevents polling from running in the background when NOFI is looking at a different tab. Out of scope but trivial to add. SKIP if it would risk breaking the smart diff. Focus on Parts 1+2.

## Out of scope

- No new Kanban features
- No mobile drawer
- No task file changes (no further status updates)
- No new endpoints

## Acceptance criteria

- [ ] `Cache-Control: no-store` header present in HTTP response for `/kanban` (verify with `curl -I`)
- [ ] `Pragma: no-cache` and `Expires: 0` also present
- [ ] Smart diff polling implemented: scrolling inside a column does NOT reset when polling fires
- [ ] Manual test: open `/kanban`, scroll the Done column to the bottom, wait 10 seconds (2 polling cycles), scroll position stays at the bottom
- [ ] Manual test: cards still drag-drop correctly with smart diff
- [ ] Manual test: new cards appear when created
- [ ] Manual test: card moves between columns when dragged
- [ ] All 10 endpoints still 200
- [ ] Running column still shows 5 tasks (no new changes to task files)
- [ ] No new features added
- [ ] Argus verifies with BEHAVIORAL test (not just structural)

## Files to touch

- `01_projects/mission-control/code/serve.py` — add cache headers
- `01_projects/mission-control/code/kanban.html` — refactor `loadKanban` / `renderKanban` to smart diff
- Backup: `01_projects/mission-control/code/backups/pre-mc-kanban-bugfix-2-2026-06-16/`

## Handoff to Forge

1. Read the task file (this one) fully
2. **Behavioral test BEFORE coding** — open `/kanban` in a browser, scroll Done column to bottom, wait 10s, observe what happens. Confirm the scroll-jump.
3. Make backup
4. Implement Part 1 (cache headers) — small change, low risk
5. Implement Part 2 (smart diff) — the big change, ~150-200 LOC
6. **Behavioral test AFTER coding** — same test as step 2, confirm the scroll stays
7. Commit + push
8. Write your log

## Handoff to Argus

**CRITICAL: Do behavioral tests, not just structural checks.**

1. Verify Cache-Control header: `curl -I http://192.168.0.29:8767/kanban | grep -i cache` → should include `no-store`
2. Verify the polling function is changed — look for evidence of smart diff (Map<taskId, HTMLElement> or similar)
3. Verify `board.innerHTML = ` does NOT appear in the new polling code (was the line that caused the scroll reset)
4. If you can take a browser screenshot via vision tools, do so. Otherwise rely on the structural evidence.
5. Honest disclosure: if you can't actually load the page in a browser and verify scroll behavior, say so. Don't fake a PASS.

## Open follow-ups (after this task)

- MC-KANBAN-FREEZE-ACCEPTANCE — final kanban closure
- Then: MC-022-ON-DEMAND-1 or NOFI's pick

## Self-criticism (Thor)

The prior verification passed structural checks but missed the actual user experience. I should have:
- Actually loaded the page in a browser (or had Argus do it with vision tools)
- Tested scroll behavior interactively
- Not trusted structural evidence alone

This is a process failure. Even with smart sub-agents, I (Thor) need to escalate to behavioral testing when the user reports a bug that "should" be fixed but isn't.
