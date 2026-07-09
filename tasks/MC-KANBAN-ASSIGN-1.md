---
task_id: MC-KANBAN-ASSIGN-1
title: Per-card assign action — click a card to assign it to Thor, Forge, or Argus
project: mission-control
phase: live-monitor
status: done
priority: high
created: 2026-06-17T10:58:00+04:00
created_by: thor
assigned_to: forge, argus
approval_required: true
approval_status: approved
approval_phrase: "NOFI: there are tasks that are unassigned... i want to add an option when i click on the card to allow me to assign it to an agent"
argus_passed: false
depends_on: [MC-KANBAN-BUGFIX-3]
blocks: [MC-KANBAN-FREEZE-ACCEPTANCE]
tags: [mission-control, kanban, assign, click, agent, new-feature]
kanban_status: done
---

# MC-KANBAN-ASSIGN-1 — Per-Card Assign Action

## NOFI's request (verbatim, 2026-06-17 ~10:56 Dubai)
*"there are tasks that are unassigned... i want to add an option when i click on the card to allow me to assign it to an agent"*

## Current state

- 7 of 49 tasks have `assigned_to = None`:
  - Triage: MC-007-token-budget
  - Running: MC-004-tasks-panel
  - Blocked: MC-005-blocked-no-key, MC-006-failed-test
  - Done: MC-001-overview-panel, MC-002-agents-panel, MC-003-lan-access
- The card UI currently shows the assignee as a chip (if assigned) but has no way to CHANGE the assignee via click
- The data model has `assigned_to` as a field in the task frontmatter (Format A) or `| **owner** | thor |` row in the table (Format B)

## Goal

When NOFI clicks a card:
1. Card expands (existing behavior — toggle body)
2. **NEW:** Expanded body shows an "Assign to:" row with 3 buttons: ⚡ Thor, 🔨 Forge, 👁️ Argus
3. Clicking a button calls the new PATCH endpoint
4. The task file's `assigned_to` (Format A) or `owner` (Format B) field is updated
5. The card re-renders with the new assignee chip color
6. The page state is fresh on next poll (no need to wait 5s)

## Scope (3 parts)

### Part 1 — Backend: PATCH endpoint (Forge)

Add a new endpoint to `serve.py`:

```python
@app.patch("/api/data/kanban/task/{task_id}/assign")
def assign_kanban_task(task_id: str, payload: dict) -> tuple[int, dict]:
    """Assign a kanban task to an agent (thor/forge/argus)."""
    new_assignee = (payload.get("assignee") or "").strip().lower()
    if new_assignee not in {"thor", "forge", "argus", ""}:
        return 400, {"error": f"unknown assignee: {new_assignee!r}; must be thor, forge, argus, or empty (unassign)"}
    # Find the task file
    task_file = find_task_file(task_id)  # use existing kanban_parser
    if not task_file:
        return 404, {"error": f"task not found: {task_id}"}
    # Update the assigned_to (or owner for Format B) field
    update_task_assignee(task_file, new_assignee)
    # Return updated board
    board = data_kanban(include_archived=False)
    return 200, {"ok": True, "task_id": task_id, "assignee": new_assignee, "board": board}
```

The `update_task_assignee(task_file, new_assignee)` helper:
- Detect format (A or B)
- Format A: parse YAML, set `assigned_to: <new>` (or remove the key if empty), preserve everything else
- Format B: find `| **owner** | ... |` row, replace the value (or insert if missing)
- If empty/unassign, set the field to empty or remove the row

Use `PATCH` (not `POST`) because it's an update. Reuse the existing `update_task_status` pattern from MC-KANBAN-2.

### Part 2 — Frontend: Click-to-assign UI (Forge)

Modify `kanban.html`:

1. In the card body template (around line 690+ where `renderKanbanCard` is defined), add a "Assign to:" row:
   ```html
   <div class="card-assign-actions">
     <span class="assign-label">Assign to:</span>
     <button class="assign-btn" data-agent="thor">⚡ Thor</button>
     <button class="assign-btn" data-agent="forge">🔨 Forge</button>
     <button class="assign-btn" data-agent="argus">👁️ Argus</button>
     <button class="assign-btn" data-agent="">✕ Unassign</button>
   </div>
   ```

2. CSS for the assign buttons (highlight the currently-assigned agent):
   ```css
   .card-assign-actions {
     display: flex; gap: 4px; margin-top: 6px; align-items: center;
     flex-wrap: wrap;
   }
   .card-assign-actions .assign-label {
     font-size: 10px; color: var(--text3); margin-right: 2px;
   }
   .card-assign-actions .assign-btn {
     font-size: 10px; padding: 2px 6px; border: 1px solid var(--line);
     background: var(--bg); color: var(--text2); border-radius: 3px;
     cursor: pointer;
   }
   .card-assign-actions .assign-btn:hover {
     color: var(--text); border-color: var(--cyan);
   }
   .card-assign-actions .assign-btn.active {
     color: var(--green); border-color: var(--green); background: rgba(0,255,0,0.08);
   }
   .card-assign-actions .assign-btn[data-agent="thor"].active { color: var(--thor-color); border-color: var(--thor-color); }
   .card-assign-actions .assign-btn[data-agent="forge"].active { color: var(--forge-color); border-color: var(--forge-color); }
   .card-assign-actions .assign-btn[data-agent="argus"].active { color: var(--argus-color); border-color: var(--argus-color); }
   ```

3. Wire up the click handler in the smart diff code (around line 670-700 where card click handlers are attached):
   ```javascript
   for (const btn of cardEl.querySelectorAll(".assign-btn")) {
     btn.addEventListener("click", async (e) => {
       e.stopPropagation();
       const agent = btn.dataset.agent;
       const tid = cardEl.dataset.taskId;
       await assignTask(tid, agent);
     });
   }
   ```

4. New function `assignTask(task_id, agent)`:
   ```javascript
   async function assignTask(taskId, agent) {
     try {
       const r = await fetch(`/api/data/kanban/task/${encodeURIComponent(taskId)}/assign`, {
         method: "PATCH",
         headers: { "Content-Type": "application/json" },
         body: JSON.stringify({ assignee: agent })
       });
       if (!r.ok) {
         const j = await r.json().catch(() => ({}));
         throw new Error(j.error || `HTTP ${r.status}`);
       }
       const j = await r.json();
       _kanbanState = j.board;
       smartRenderKanban(j.board, true);  // force rebuild to reflect new assignee
     } catch (e) {
       alert(`Assign failed: ${e.message}`);
     }
   }
   ```

5. When the card body is expanded (toggled), the assign buttons should be visible. The smart diff should preserve the open-card state across re-renders if the user just changed an assignee. Use the existing `_kanbanOpenCards` Set.

### Part 3 — Behavioral verification (Argus, mandatory)

Argus must run a Playwright test:

1. Open `/kanban` in headless Chrome
2. Find an unassigned task (e.g. MC-007-token-budget in Triage)
3. Click the card to expand it
4. Verify the 4 assign buttons appear (Thor, Forge, Argus, Unassign)
5. Click "Forge" button
6. Wait 1 second for the PATCH
7. Verify the card now shows the Forge assignee chip (with color)
8. Take screenshot
9. Verify the task file on disk now has `assigned_to: forge` in the frontmatter
10. Reload the page
11. Verify the assignee is still Forge (persisted)
12. Click "Unassign" button
13. Verify the assignee chip is gone
14. Verify the task file's `assigned_to:` is removed (Format A) or `| **owner** | |` is set to empty (Format B)

ALL 14 steps must pass. If any fail, the task is not done.

## Out of scope

- Bulk assign (assigning multiple cards at once)
- Notification when a task is assigned
- Re-assigning to a different agent in a workflow sense (e.g. "passed to Forge for implementation")
- The "auto-process" cron doesn't need to assign — that's a different task

## Acceptance criteria

- [ ] PATCH endpoint exists and works for both Format A and Format B tasks
- [ ] Card body shows 4 assign buttons when expanded
- [ ] Clicking Thor/Forge/Argus updates the task file and re-renders the card
- [ ] Clicking Unassign removes the assignee
- [ ] New tasks created via the existing "+" button can be assigned via this UI
- [ ] The currently-assigned agent's button is highlighted
- [ ] All 10 existing endpoints still 200
- [ ] All 7 currently-unassigned tasks can be assigned via this UI
- [ ] No regressions in the 5 known fixed bugs (smart diff, scroll, lanes, format, etc.)
- [ ] Argus behavioral test PASS (14 steps)

## Files to touch

- `01_projects/mission-control/code/serve.py` — new PATCH endpoint
- `01_projects/mission-control/code/kanban.html` — UI for assign buttons + click handler
- Backup: `01_projects/mission-control/code/backups/pre-mc-kanban-assign-1-2026-06-17/`

## Handoff to Forge

1. Read this task spec
2. Read `/home/nofidofi/NofiTech-Ind/01_projects/mission-control/code/kanban.html` lines 660-720 to find where card click handlers are wired
3. Read `/home/nofidofi/NofiTech-Ind/01_projects/mission-control/code/serve.py` `update_task_status` function (from MC-KANBAN-2) — reuse the pattern
4. Make backup
5. Implement the PATCH endpoint in serve.py
6. Implement the UI in kanban.html
7. Restart server (serve.py changed)
8. Quick smoke test: `curl -X PATCH http://192.168.0.29:8767/api/data/kanban/task/MC-007-token-budget -H "Content-Type: application/json" -d '{"assignee":"forge"}'`
9. Verify the file on disk changed
10. Revert the test (assign back to empty)
11. Commit + push
12. Write your log

## Handoff to Argus

1. **MANDATORY:** Run the 14-step Playwright behavioral test
2. If any step fails, document the failure and report FAIL
3. If all pass, write argus log with PASS
4. Update state.json, commit, push

## Self-criticism (Thor)

This is a small, focused feature. The risk:
1. The smart diff might not re-render the card correctly after assignment — could leave the old assignee chip visible
2. The PATCH endpoint might not handle Format B (markdown table) correctly
3. The behavioral test is the only way to catch these

**Don't trust structural verification for this one.** Behavioral test is mandatory in the acceptance criteria.

## Open follow-ups

- Bulk assign — NOFI didn't ask
- "Queued" column — still pending
- MC-KANBAN-FREEZE-ACCEPTANCE — after this
