---
task_id: MC-KANBAN-MOVE-1
title: Move Kanban to a separate page with sidebar nav (Main + Kanban tabs)
project: mission-control
phase: live-monitor
status: done
priority: high
created: 2026-06-16T20:10:00+00:00
created_by: thor
assigned_to: forge, argus
approval_required: true
approval_status: approved
approval_phrase: "NOFI: MOVE THE KANBAN TO A NEW PAGE COMPLETELY.. A NEW page ... you can create a side navigation bar with 2 tabs .. Main page and Kanban"
argus_passed: false
depends_on: [MC-KANBAN-2-DUAL-FORMAT-PARSER]
blocks: [MC-KANBAN-FREEZE-ACCEPTANCE]
tags: [mission-control, kanban, navigation, sidebar, page-split, new-feature]
kanban_status: done
---

# MC-KANBAN-MOVE-1 — Move Kanban to a Separate Page with Sidebar Nav

## NOFI's directive (verbatim, 2026-06-16 ~20:08Z)
*"First ... MOVE THE KANBAN TO A NEW PAGE COMPLETELY.. A NEW page ... you can create a side navigation bar with 2 tabs .. Main page and Kanban"*

**Important:** This supersedes the previously-pending MC-KANBAN-FREEZE-ACCEPTANCE. The freeze will be done AFTER this move is verified (the freeze has to come last anyway — you freeze what you shipped).

## Goal
The Mission Control page currently shows everything in a single long page (Sections 1-10 stacked). NOFI wants:
- A **sidebar navigation** with 2 tabs: **Main page** + **Kanban**
- **Main page** keeps Sections 1-9 (Overview, Agents, Tasks, Projects, Action Required, Warnings, Pending Orders, Logs/Health, GitHub Connection)
- **Kanban** is its own page (Section 10 moved out)
- Sidebar is always visible (or accessible via a hamburger on mobile)

## Scope (4 parts)

### Part A — Create `kanban.html` (Forge)

A new file at `01_projects/mission-control/code/kanban.html` that contains the full Kanban board (everything currently in Section 10 of mission-control.html).

Requirements:
- Standalone HTML document (full `<!DOCTYPE html>`, `<html>`, `<head>`, `<body>`)
- Loads the same dark theme CSS vars as mission-control.html (extract shared CSS to a common file or duplicate with a comment "keep in sync with mission-control.html")
- Includes the **sidebar** (see Part B)
- Has the same 6 columns, 3 swimlanes, drag-drop, inline create, search, polling as the current Section 10
- Loads its data from `/api/data/kanban` (same endpoint, no API change needed)
- POST/PATCH to `/api/data/kanban/task*` (same endpoints, no API change needed)
- Includes a "← Back to Main" link in the header
- Title: "Kanban — Multi-Agent Board"
- Page meta: description, favicon, etc. (match mission-control.html)

### Part B — Sidebar navigation component (Forge)

A reusable sidebar with 2 tabs that appears on BOTH pages (main + kanban).

Structure:
```
┌──────────────┬────────────────────────────────────┐
│  NofiTech    │  Main Page or Kanban Page          │
│              │                                     │
│  ⚡ Main     │                                     │
│  🗂 Kanban   │                                     │
│              │                                     │
│  (optional   │                                     │
│   future     │                                     │
│   tabs)      │                                     │
└──────────────┴────────────────────────────────────┘
```

Requirements:
- Fixed left sidebar, ~180px wide
- Dark theme matching the rest of the dashboard
- Each tab is a link/anchor with an icon and label
- Active tab is highlighted (different background, accent color)
- "Main" → links to `/` (the existing main page)
- "Kanban" → links to `/kanban.html` (or `/kanban` if we add a route)
- Top of sidebar: NofiTech logo/name (use a simple text or emoji, no asset)
- Bottom of sidebar: small "v1.15.0+kanban" version label
- On mobile (<768px): collapse to a hamburger menu that opens a drawer

Implementation:
- Extract the sidebar into a shared component (either a JS include or copy-paste with a comment)
- Each page embeds the sidebar at the top of `<body>`
- Active state determined by URL: `window.location.pathname === '/'` → Main active, `'kanban'` → Kanban active

### Part C — Update `mission-control.html` (Main page) (Forge)

Changes:
1. Add the sidebar at the top of `<body>` (above all sections)
2. Adjust section widths/content to fit next to the sidebar (main content area gets `margin-left: 180px` or similar)
3. **Remove Section 10** (Kanban) entirely
4. **Add a small "Kanban" link/card** at the top of the main page (in the header or just below the title) that says "🗂 Open Kanban Board →" and links to `/kanban.html`
5. Or alternatively, in the sidebar's Kanban tab, show a small count badge with the number of active tasks (using the existing `/api/data/kanban` endpoint)

### Part D — Server routing (Forge)

Two options:
- **Option 1: Static files.** Just put `kanban.html` in the same directory as `mission-control.html`. The existing `serve.py` should serve static files by default. NO new endpoint needed. URL: `http://192.168.0.29:8767/kanban.html`
- **Option 2: New route.** Add a FastAPI route `@app.get("/kanban")` that returns the kanban.html file. URL: `http://192.168.0.29:8767/kanban`

**Recommendation: Option 2** (cleaner URLs, no `.html` suffix). Implementation:
```python
@app.get("/kanban")
def kanban_page():
    return FileResponse(KANBAN_HTML_PATH, media_type="text/html")
```

Test with: `curl -s -o /dev/null -w "%{http_code}\n" http://192.168.0.29:8767/kanban` → 200

### Part E — Argus verification (Argus)

A. Task-first proof:
- Task file exists before code changes: yes
- Events exist before code changes: yes

B. Both pages load:
- `curl -s -o /dev/null -w "%{http_code}\n" http://192.168.0.29:8767/` → 200
- `curl -s -o /dev/null -w "%{http_code}\n" http://192.168.0.29:8767/kanban` → 200 (Option 2) OR `/kanban.html` → 200 (Option 1)

C. Main page no longer has Section 10:
- `curl -s http://192.168.0.29:8767/ | grep -c "section-kanban"` → 0 (no more Section 10 in main)
- `curl -s http://192.168.0.29:8767/kanban | grep -c "section-kanban"` → ≥ 1 (Kanban page has it)

D. Sidebar present on both pages:
- `curl -s http://192.168.0.29:8767/ | grep -c "sidebar\|side-nav\|kanban-sidebar"` → ≥ 1
- `curl -s http://192.168.0.29:8767/kanban | grep -c "sidebar\|side-nav\|kanban-sidebar"` → ≥ 1

E. Sidebar has 2 tabs:
- Both pages should have links to `/` (Main) and `/kanban` (Kanban)
- `curl -s http://192.168.0.29:8767/ | grep -E "href=[\"']/[\"']|href=[\"']/kanban[\"']" | head -3` → both URLs present
- Same for `/kanban`

F. Active state works:
- Main page (`/`) — Main tab should have an "active" class
- Kanban page (`/kanban`) — Kanban tab should have an "active" class
- This can be hardcoded per page (since we have 2 separate HTML files) or done via JS that reads `window.location.pathname`

G. Kanban functionality preserved on /kanban:
- 43 tasks still visible: `curl -s http://192.168.0.29:8767/api/data/kanban | python3 -c "import json,sys; print(sum(c['count'] for c in json.load(sys.stdin)['columns']))"` → 43
- Drag-drop present: `grep -c "draggable\|dragstart\|drop" kanban.html` → ≥ 4
- Inline create: `grep -c "add-btn" kanban.html` → ≥ 1
- Search: `grep -c "kanban-search\|search-input" kanban.html` → ≥ 1
- Polling: `grep -c "setInterval.*kanban" kanban.html` → ≥ 1
- Lanes: `grep -c "lanes-by-profile\|lane_by_profile" kanban.html` → ≥ 1

H. No regressions on main page:
- All 9 remaining sections still served: `curl -s http://192.168.0.29:8767/ | grep -c "section-overview\|section-agents\|section-tasks\|section-projects\|section-action\|section-warnings\|section-orders\|section-logs\|section-github"` → ≥ 9
- All API endpoints still 200: /api/health, /api/version, /api/data/overview, /api/data/agents, /api/data/projects, /api/data/tasks, /api/data/logs, /api/data/orders, /api/data/github, /api/data/kanban
- No new features added to Kanban (just the move)

I. Git state:
- New commit(s) on main
- Optionally a tag (NOFI didn't request one for this, so just commit)

J. Visual / UX smoke test (Argus can take a screenshot if browser tools available, otherwise just verify HTML structure):
- Page loads without JS errors (check the HTML is well-formed)
- Sidebar doesn't overlap with main content
- Active tab is visually distinct

## Out of scope
- Adding more tabs (NOFI explicitly said 2 tabs only)
- Mobile hamburger drawer (desktop-first; mention as follow-up if needed)
- New Kanban features (filters, search, colors, archive UI)
- WebSocket live updates
- Authentication / user management
- Internationalization

## Acceptance criteria
- [ ] `/kanban` (or `/kanban.html`) returns 200
- [ ] Main page (`/`) no longer contains Section 10
- [ ] Sidebar with 2 tabs (Main, Kanban) present on BOTH pages
- [ ] Active tab is visually distinct on each page
- [ ] All 9 remaining sections still served on main page
- [ ] Kanban page has all 43 tasks, drag-drop, inline create, search, polling
- [ ] All 12 API endpoints still return 200
- [ ] No new Kanban features added
- [ ] No mass task file conversion
- [ ] All commits pushed to remote
- [ ] Argus PASS in argus log file
- [ ] mc-kanban-1 tag still exists (we don't break the old one)

## Files to touch
- `01_projects/mission-control/code/kanban.html` (NEW)
- `01_projects/mission-control/code/mission-control.html` (remove Section 10, add sidebar)
- `01_projects/mission-control/code/serve.py` (add /kanban route, optional shared CSS endpoint)
- `01_projects/mission-control/code/kanban_parser.py` (NO change expected)
- Backup: `01_projects/mission-control/code/backups/pre-mc-kanban-move-1-2026-06-16/`

## Handoff to Forge

1. Read the task file (this one) fully
2. Read `/home/nofidofi/NofiTech-Ind/00_company_os/04_agents/logs/2026-06-16/forge-mc-kanban-2.md` for context on the existing Section 10 implementation
3. Make backup first
4. Create kanban.html (copy the Section 10 portion of mission-control.html into a new file, wrap it with full HTML structure, add sidebar)
5. Update mission-control.html (remove Section 10, add sidebar at top, adjust main content layout)
6. Add /kanban route in serve.py (or just use static file serving)
7. Test both URLs load 200
8. Verify Section 10 markers are ONLY in kanban.html, NOT in mission-control.html
9. Commit + push (2 commits likely: one for kanban.html, one for the main page update, or one combined)
10. Write your log at `00_company_os/04_agents/logs/2026-06-16/forge-mc-kanban-move-1.md`
11. Set mtime to NOW (don't backdate)

## Handoff to Argus

After Forge is done:
1. Run all A-J checks above
2. Write `00_company_os/04_agents/logs/2026-06-16/argus-mc-kanban-move-1.md` with PASS/FAIL counts
3. Update state.json (argus=complete)
4. Commit + push
5. mtime: now

## Post-move follow-up (not in this task)
- MC-KANBAN-FREEZE-ACCEPTANCE — small closure once this move is verified
- Then move on to whatever NOFI picks next (MC-022-ON-DEMAND-1 or other ready tasks)
