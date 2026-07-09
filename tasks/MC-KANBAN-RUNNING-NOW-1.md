---
task_id: MC-KANBAN-RUNNING-NOW-1
title: Add "Running Now" column — strictly for tasks actively being worked on by an agent
project: mission-control
phase: live-monitor
status: done
priority: high
created: 2026-06-17T11:30:00+04:00
created_by: thor
assigned_to: forge, argus
approval_required: true
approval_status: approved
approval_phrase: "NOFI: add RUNNING NOW column ... ONLY AND ONLY TASKS WHICH ARE BEING PROCESSED AND WORKED ON BY ANY AGENT SHOULD BE IN THE RUNNING NOW COLUMN STRICTLY"
argus_passed: false
depends_on: [MC-KANBAN-ASSIGN-1, MC-KANBAN-UNLIMITED-TITLE-1]
blocks: [MC-KANBAN-FREEZE-ACCEPTANCE]
tags: [mission-control, kanban, running-now, semantic-split, agent-activity, column-rename]
kanban_status: done
---

# MC-KANBAN-RUNNING-NOW-1 — Strict Agent-Activity Column

## NOFI's request (verbatim, 2026-06-17 ~11:25 Dubai)
*"add a column called RUNNING NOW ... and only should show the task which is running and if the task is completed it should be moved to done ... in progress column is very confusing and the meaning is too vast... tasks which waiting for my order might stay there for days.. so it shouldnt be mixed with tasks which are MOMENTARILY being ran by the team.. if a task is pending or waiting that means its NOT RUNNING NOW ... keep that in mind ... ONLY AND ONLY TASKS WHICH ARE BEING PROCESSED AND WORKED ON BY ANY AGENT SHOULD BE IN THE RUNNING NOW COLUMN STRICTLY"*

## Current problem

The "In Progress" (id=running) column has 8 tasks:
- 6 MC-* tasks with `task_completed` events but `status: in_progress` (they should be `done`)
- 1 DIY-011 (genuine in progress)
- 1 MC-004-tasks-panel (legacy)

NOFI is right: "in progress" is too broad. A task that's "claimed but waiting for NOFI's order" is not the same as "actively being processed by Forge/Argus right now".

## Design decisions (locked by Thor)

### Column structure (NEW)

| Column id | Label | What goes here |
|---|---|---|
| `triage` | Triage | New tasks, not yet started |
| `todo` | Todo | Backlog, no agent assigned |
| `ready` | Ready | Assigned to an agent, waiting for the agent to start |
| `pending` | **In Progress** (renamed from "running") | Claimed, waiting for NOFI's order, OR sub-agent finished but NOFI hasn't reviewed |
| `running_now` | **Running Now** (NEW) | Actively being processed by an agent RIGHT NOW |
| `blocked` | Blocked | Has a blocker, can't proceed |
| `done` | Done | Complete |
| `archived` | Archived | (hidden by default) |

Wait — NOFI said "in progress column is very confusing". So the In Progress column needs a different name or it gets removed. Let me re-read.

NOFI's words:
- "in progress column is very confusing and the meaning is too vast"
- "tasks which waiting for my order might stay there for days.. so it shouldnt be mixed with tasks which are MOMENTARILY being ran by the team"
- "if a task is pending or waiting that means its NOT RUNNING NOW"
- "ONLY AND ONLY TASKS WHICH ARE BEING PROCESSED AND WORKED ON BY ANY AGENT SHOULD BE IN THE RUNNING NOW COLUMN STRICTLY"

So NOFI wants:
- **Running Now** — only currently-active tasks
- (The other "in progress" tasks need a home — likely "Ready" or "Pending" or "Waiting for you")

**Question for NOFI:** where should the "claimed, waiting for NOFI's order" tasks go? Options:
- Add a new "Pending" column
- Put them in "Ready" (already exists)
- Just leave them in "In Progress" (less strict)

**For this task, default to:** put them in the existing "Ready" column. So:

| Column | Status |
|---|---|
| Triage | `status: triage` (new) |
| Todo | `status: todo` |
| Ready | `status: ready` OR `status: in_progress` (claimed, waiting) |
| **Running Now** | `kanban_status: running_now` (NEW) |
| Blocked | `status: blocked` |
| Done | `status: complete` / `done` |

Actually, looking at the existing status mapping in `kanban_parser.py`:
```python
"in_progress": "running",
"in-progress": "running",
```

This maps `in_progress` → `running` column. I need to change this to map to `ready` instead (since Ready already has a status mapping).

**New mapping:**
- `triage` → `triage`
- `todo` → `todo`
- `ready` / `pending` → `ready`
- `in_progress` / `in-progress` → `ready` (claimed, waiting for NOFI)
- `running_now` / `in_work` → `running_now` (NEW column)
- `blocked` → `blocked`
- `complete` / `done` → `done`
- `archived` → `archived`

**But wait** — the running column already has a label. NOFI said "in progress column is very confusing". The label is currently "In Progress". I should:
- Keep the column id as `running` for backward compat OR rename it
- Change the LABEL to something clearer

Actually, simpler: **rename the existing `running` column to "Pending"** and add a new "Running Now" column.

OR: keep `running` as "In Progress" and add new "Running Now".

NOFI said "in progress column is very confusing". The cleanest interpretation: remove the "In Progress" confusion entirely. So:

**Final column structure:**

| id | label | meaning |
|---|---|---|
| `triage` | Triage | New |
| `todo` | Todo | Backlog |
| `ready` | Ready | Ready to start (includes claimed-but-waiting) |
| `running_now` | **Running Now** | Actively being worked on |
| `blocked` | Blocked | |
| `done` | Done | |

The old `running` column is **replaced** by `running_now`. Status mapping changes:
- Old: `in_progress` → `running` (column id)
- New: `in_progress` → `ready`, `running_now` → `running_now` (column id)

This means the 6 stale MC-* tasks with `status: in_progress` will move to "Ready" (correctly — they're not currently being worked on, they're done but their status field is stale).

**Fix for the 6 stale tasks:** NO additional work needed. Once the parser mapping changes, they'll naturally move to Ready. NOFI can then either:
- Leave them in Ready (queued for review)
- Or I can spawn a cleanup task to flip them to status: complete (one-line sed per file)

**Decision: spawn a cleanup sub-task** as part of this work. It's a one-liner: `sed -i 's/^status: in_progress$/status: complete/' <files>`. Or do it via the existing PATCH /api/data/kanban/task/:id endpoint.

OK let me just decide. For this task:

### Thor decisions (final)

1. **Rename** the existing `running` column to `ready` (id stays `running` internally for now... actually let me just rename the id too). Wait, that's a breaking change. Let me think.

**Cleanest plan:**
- Add a NEW column `running_now` to the data
- RENAME the existing `running` column to `ready` (id becomes `ready` — but this breaks all existing tasks that have `kanban_status: running`)
- OR keep `running` as-is and just add a second "running" column

Actually, **simplest plan that respects NOFI's intent:**
- Keep the existing `running` column id but **change the label from "In Progress" to "Ready"** (it now means "ready / waiting")
- Add a NEW column `running_now` with label "Running Now"
- Status mapping:
  - `triage` → `triage`
  - `todo` → `todo`
  - `ready` / `in_progress` / `in-progress` → `running` (column id, label = "Ready")
  - `running_now` → `running_now` (column id, label = "Running Now")
  - `blocked` → `blocked`
  - `complete` / `done` → `done`

This way:
- 7 stale in_progress tasks move from "In Progress" to "Ready" (less confusing label)
- New "Running Now" column is empty initially (or has any tasks with kanban_status: running_now)
- NOFI sees a clear semantic split: "Ready" = waiting, "Running Now" = active

**But NOFI said "in progress column is very confusing". The column with label "Ready" is NOT confusing.** So this works.

**Issue with this plan:** the old `running` column id is now used for "Ready", which is semantically weird in the code. The PATCH /api/data/kanban/task/:id endpoint accepts status values that match column ids. So someone could PATCH a task to "running" and it'd go to the Ready column. That's confusing too.

**Final decision:** rename the column ID too. The breaking change is acceptable because:
- All existing tasks with `kanban_status: running` will just show in Ready (not catastrophic)
- New tasks created via the UI go to triage (no ID issue)
- The code becomes clean

## Scope (4 parts)

### Part 1 — Parser changes (Forge)

In `/home/nofidofi/NofiTech-Ind/01_projects/mission-control/code/kanban_parser.py`:

1. Update `STATUS_MAP` (line 51-67 area):
```python
STATUS_MAP = {
    "triage": "triage",
    "todo": "todo",
    "ready": "ready",
    "in_progress": "ready",       # CHANGED: was "running"
    "in-progress": "ready",       # CHANGED: was "running"
    "running_now": "running_now", # NEW
    "in_work": "running_now",     # NEW alias
    "active": "running_now",      # NEW alias
    "blocked": "blocked",
    "complete": "done",            # already was
    "done": "done",
    "archived": "archived",
}
```

2. Update the column definitions (line 465-518 area):
```python
COLUMNS = [
    {"id": "triage", "label": "Triage"},
    {"id": "todo", "label": "Todo"},
    {"id": "ready", "label": "Ready"},
    {"id": "running_now", "label": "Running Now"},  # NEW
    {"id": "blocked", "label": "Blocked"},
    {"id": "done", "label": "Done"},
    # "running" removed
]
```

3. Update the `running` lane logic in the response builder (around line 531-544):
   - The "swimlanes inside the running column" code currently looks at `col.id === "running"`. Change to `col.id === "running_now"`.
   - Lanes show by assignee (Thor/Forge/Argus) for the running_now column.

4. Update the PATCH endpoint validation in `serve.py`:
   - The `patch_kanban_task` function validates `new_status` against allowed values
   - Allowed values: `triage, todo, ready, running_now, blocked, done, archived` (no more "running")

### Part 2 — Cleanup the 6 stale tasks (Forge)

These 6 tasks have `status: in_progress` but should be `status: complete`:

1. `01_projects/mission-control/tasks/MC-KANBAN-MOVE-1.md` → `complete`
2. `01_projects/mission-control/tasks/MC-KANBAN-2-DUAL-FORMAT-PARSER.md` → `complete` (also has `kanban_status: done`)
3. `01_projects/mission-control/tasks/MC-KANBAN-1.md` → `complete`
4. `01_projects/mission-control/tasks/MC-AGENT-LOG-FIX-1.md` → `complete`
5. `01_projects/mission-control/tasks/MC-GITHUB-PANEL-1.md` → `complete`
6. `01_projects/mission-control/tasks/MC-GITHUB-REPO-SETUP-1.md` → `complete`

Use `patch` for each. Verify each ends with `status: complete` in YAML frontmatter.

After cleanup, all 6 will land in the "Done" column.

### Part 3 — HTML changes (Forge)

In `/home/nofidofi/NofiTech-Ind/01_projects/mission-control/code/kanban.html`:

1. The page already has 6 columns dynamically rendered from the API. Adding a 7th column is automatic.
2. Update CSS for the new "Running Now" column if needed (probably inherit existing styles).
3. Update the swimlane logic to look for `running_now` column id (not `running`).
4. Update the summary chips: `running` chip is now `running_now`.

### Part 4 — Behavioral verification (Argus, mandatory)

Argus must run a 10-step Playwright test:

1. Open `/kanban` in headless Chrome
2. Verify: 7 columns visible (triage, todo, ready, running_now, blocked, done, + maybe archived)
3. Verify: 0 tasks in "Running Now" column initially (or only tasks genuinely being worked on)
4. Verify: 6 stale MC tasks are in "Done" column
5. Verify: 1-2 genuine tasks (DIY-011, MC-004) are in "Ready" column
6. Verify: 3 swimlanes inside "Running Now" column (Thor/Forge/Argus)
7. **Live test:** Use the PATCH endpoint to set a task to `running_now`, verify it appears in the column
8. **Live test:** PATCH another task to `complete`, verify it moves to "Done"
9. **Live test:** PATCH a task to `in_progress`, verify it lands in "Ready" (not Running Now)
10. Take screenshot of the final state

Revert the test PATCHes (set back to original values).

## Out of scope

- No new UI features beyond the new column
- No "is currently being worked on" auto-detection (that's a future cron job; for now, `kanban_status: running_now` is set explicitly)
- No removal of existing 6 tasks (they get auto-moved to Done via Part 2)

## Acceptance criteria

- [ ] Parser STATUS_MAP updated
- [ ] New "Running Now" column in the data
- [ ] Old `running` column removed from API output (its tasks redistribute to Ready)
- [ ] HTML renders 7 columns (or 6 + 1 hidden archived)
- [ ] Swimlanes appear inside "Running Now" column
- [ ] 6 stale MC-* tasks moved to Done
- [ ] PATCH endpoint validates new statuses (running_now is allowed, running is NOT)
- [ ] Argus behavioral test PASS
- [ ] All 10 existing endpoints still 200
- [ ] NOFI's actual workflow is improved: NOFI can clearly see what's being worked on RIGHT NOW

## Files to touch

- `01_projects/mission-control/code/kanban_parser.py` (status map + column definitions)
- `01_projects/mission-control/code/serve.py` (PATCH endpoint validation)
- `01_projects/mission-control/code/kanban.html` (any UI tweaks)
- 6 task files in `01_projects/mission-control/tasks/` (status: in_progress → complete)
- Backup: `01_projects/mission-control/code/backups/pre-mc-kanban-running-now-1-2026-06-17/`

## Handoff to Forge

1. Read this task spec (long but thorough)
2. Make backup
3. Update parser (Part 1)
4. Update serve.py validation (Part 1 step 4)
5. Update HTML if needed (Part 3)
6. Update 6 task files (Part 2)
7. Restart server
8. Smoke test: `curl -s http://192.168.0.29:8767/api/data/kanban | python3 -c "..."` — verify new column exists, no `running` column
9. Commit + push
10. Write your log

## Handoff to Argus

Run the 10-step behavioral test. Take screenshots. Report PASS/FAIL.

## Self-criticism

This is a structural change. The "In Progress" → "Ready" rename is a deliberate semantic change. NOFI's wording suggests this is what they want ("in progress is very confusing"). If I'm wrong about the rename, NOFI can correct.

## Open follow-ups

- After this: MC-KANBAN-FREEZE-ACCEPTANCE
- Future: auto-detect "actively being worked on" via cron checking recent work_started events
