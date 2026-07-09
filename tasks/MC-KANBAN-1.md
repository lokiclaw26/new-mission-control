---
task_id: MC-KANBAN-1
title: Hermes Kanban tab in Mission Control — 3-agent swimlanes (Thor/Forge/Argus)
project: mission-control
phase: live-monitor
status: done
priority: high
created: 2026-06-16T18:55:00+00:00
created_by: thor
assigned_to: forge, argus
approval_required: true
approval_status: pending
argus_passed: false
depends_on: []
blocks: []
tags: [mission-control, kanban, multi-agent, tab-section, thor-forge-argus]
---

# MC-KANBAN-1 — Hermes Agent Kanban tab in Mission Control

## Goal
Add a **new tab/section** to Mission Control for the **Hermes Agent Kanban** multi-agent board, pre-configured for NofiTech Ind.'s 3-agent team: **Thor** (CEO/Orchestrator), **Forge** (Builder/Engineer), **Argus** (QA/Tester).

NOFI's exact request: *"in mission control i want you to make a new tab/Page for Hermes Agent Kanban .... now prepare and setup multi-agent via the kanban in UI... prepare it for our team setup 3 members ... Thor forge and argus"*

## Reference materials
- https://x.com/NousResearch/status/2050997692977844324/video/1 (video — not fetched, docs cover it)
- https://hermes-agent.nousresearch.com/docs/user-guide/features/kanban
- https://hermes-agent.nousresearch.com/docs/user-guide/features/kanban-tutorial
- Internal skill: `~/.hermes/skills/hermes-kanban-reference/SKILL.md` (already saved by Thor)

## Scope (this task)

### Part A — New endpoint: GET /api/data/kanban (Forge)

Returns the full kanban board state, formatted for the 3-agent team:

```json
{
  "columns": [
    {"id": "triage",  "label": "Triage",  "count": N, "tasks": [...]},
    {"id": "todo",    "label": "Todo",    "count": N, "tasks": [...]},
    {"id": "ready",   "label": "Ready",   "count": N, "tasks": [...]},
    {"id": "running", "label": "Running", "count": N, "tasks": [...], "lanes": [
       {"assignee": "thor",  "tasks": [...]},
       {"assignee": "forge", "tasks": [...]},
       {"assignee": "argus", "tasks": [...]}
    ]},
    {"id": "blocked", "label": "Blocked", "count": N, "tasks": [...]},
    {"id": "done",    "label": "Done",    "count": N, "tasks": [...]}
  ],
  "agents": [
    {"id": "thor",  "name": "Thor",  "emoji": "⚡", "role": "CEO / Orchestrator", "color": "var(--thor-color)"},
    {"id": "forge", "name": "Forge", "emoji": "🔨", "role": "Builder / Engineer",  "color": "var(--forge-color)"},
    {"id": "argus", "name": "Argus", "emoji": "👁️", "role": "QA / Tester",         "color": "var(--argus-color)"}
  ],
  "summary": {
    "total": N, "by_status": {...}, "by_assignee": {"thor": N, "forge": N, "argus": N}
  },
  "last_updated": "2026-06-16T..."
}
```

Source of truth: read task files from `01_projects/*/tasks/*.md` (the existing project task files), parse their frontmatter for `task_id`, `title`, `status`, `assigned_to`, `priority`, `created`, `current_assignment`, `approval_status`, then group by status. This avoids creating a new DB — we already have the data on disk.

Status mapping (project task file status → kanban status):
- `triage` → triage
- `in_progress` → running
- `complete` / `done` → done
- `blocked` → blocked
- `pending` / `approved` → ready
- `archived` → archived (default hidden)

**Do NOT** attempt to call external `hermes kanban` CLI or read `~/.hermes/kanban.db` — that DB may not exist on this machine (we run Hermes differently here). Stay self-contained using our own project task files.

### Part B — New endpoint: PATCH /api/data/kanban/task/:id (Forge)

Allow moving a card between columns. Updates the source task file's frontmatter `status` field. Returns 200 with the new board state. Restricted to status changes only (don't allow editing other fields via UI for now).

### Part C — New tab/section in mission-control.html (Forge)

Add **Section 10: Kanban** between Section 9 (GitHub) and the footer. Layout:

- **Header:** "Kanban — Multi-Agent Board" + summary chips (total tasks, by-status counts, by-assignee counts)
- **Toolbar:** "Show archived" toggle, "Lanes by profile" toggle, search input
- **6 columns** rendered horizontally with vertical scroll
- **Running column has 3 swimlanes** (Thor/Forge/Argus) when "lanes by profile" is ON
- **Cards** show: task_id (small mono), title, priority badge, assignee chip, status dot, "created N ago"
- **Click card** → expand inline (no drawer modal — keep it simple for v1)
- **Drag-drop** between columns → PATCH the task status
- **+ button** in column header → inline create (title + assignee dropdown of 3 agents + priority)
- **No auto-decompose** for v1 (manual mode — we orchestrate via delegate_task)
- **No WebSocket** for v1 — poll every 5s via setInterval
- **Use existing dark theme CSS vars** (--color-*, --radius, --font-mono) so it matches the page

### Part D — Multi-agent assignment wiring (Forge)

For the 3 assignees, the dropdown should offer: thor, forge, argus. When a new task is created from the UI, the task file gets written to `00_company_os/04_agents/tasks/<TASK_ID>.md` (new convention) with proper frontmatter. Or simpler: write to `01_projects/mission-control/tasks/<TASK_ID>.md` (existing convention). Pick whichever is easier to wire into the existing filesystem conventions.

### Part E — Argus verification (Argus)

After Part A-D:
1. Curl `/api/data/kanban` — confirm 6 columns, 3 agents in summary, status counts match
2. Curl `PATCH /api/data/kanban/task/MC-GITHUB-PANEL-1` with new status — confirm 200 + updated
3. Reload page, check Section 10 renders (use curl + grep for "section-kanban" + "renderKanban" markers)
4. Verify drag-drop CSS classes exist
5. Verify inline create button exists
6. Verify lanes-by-profile toggle exists
7. Write argus log with PASS/FAIL counts

## Out of scope
- External `hermes kanban` CLI integration (we don't have it on this machine, may break)
- WebSocket live updates (use polling for v1)
- Auto-decompose (we orchestrate manually)
- Mobile/touch drag-drop (desktop-first)
- Multi-tenancy (we only have 1 tenant: "nofitech")

## Acceptance criteria
- [ ] `GET /api/data/kanban` returns 200 with 6 columns + 3-agent summary
- [ ] `PATCH /api/data/kanban/task/:id` updates task file on disk + returns 200
- [ ] Section 10 renders in page, contains 6 columns + 3 agent chips
- [ ] Running column has 3 swimlanes when toggle is ON
- [ ] Drag-drop between columns works (HTML5 native + ondrop handler)
- [ ] Inline create works (title + assignee + priority, writes new task file)
- [ ] Cards show task_id, title, priority, assignee, status, "created N ago"
- [ ] Search input filters cards by title
- [ ] Show-archived toggle shows/hides archived tasks
- [ ] Polls /api/data/kanban every 5s
- [ ] No regressions on existing 11 endpoints
- [ ] All commits auto-pushed to GitHub
- [ ] Argus PASS in argus log file

## Files to touch
- `01_projects/mission-control/code/serve.py` — add `data_kanban()` and `patch_kanban_task()` endpoints
- `01_projects/mission-control/code/mission-control.html` — add Section 10 + renderKanban() + drag-drop handlers
- `01_projects/mission-control/code/kanban_parser.py` (NEW) — parse project task frontmatter into kanban dict
- Backup: `01_projects/mission-control/code/backups/pre-mc-kanban-1-2026-06-16/`

## Handoff to Forge

1. Read the reference skill: `~/.hermes/skills/hermes-kanban-reference/SKILL.md` (saved by Thor)
2. Read the live docs once for the data model: `curl -sL "https://hermes-agent.nousresearch.com/docs/user-guide/features/kanban" | head -500` (use --max-time 10)
3. Read existing mission-control.html to understand the section pattern (Sections 1-9 follow a clear pattern)
4. Implement Parts A-D
5. Use the same dark theme CSS vars as existing sections
6. Test with curl + grep before declaring done
7. Commit + push

## Handoff to Argus

1. Curl `/api/data/kanban` and verify the JSON shape matches the spec
2. Curl `PATCH` with a test task, verify the file on disk changed
3. Curl the page, grep for "section-kanban" and "renderKanban" — must be ≥ 3 matches
4. Check that the other 11 endpoints still return 200
5. Write argus log with full PASS/FAIL report
6. Honest disclosure if anything is missing
