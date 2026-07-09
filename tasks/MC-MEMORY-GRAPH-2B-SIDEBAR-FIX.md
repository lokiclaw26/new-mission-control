---
task_id: MC-MEMORY-GRAPH-2B-SIDEBAR-FIX
assigned_to: forge
title: Add Memory Graph tab to sidebar in mission-control.html and kanban.html
type: bugfix
priority: high
status: done
kanban_status: done
assignee: forge
argus_passed: true
completed: 2026-06-17T19:15:00+04:00
created: 2026-06-17T17:35:00+04:00
created_by: thor
approval_required: false
depends_on: [MC-MEMORY-GRAPH-2]
---

## Problem (reported by NOFI 2026-06-17 ~17:35 Dubai)

> "Why is it not added to the side navigation bar ? Its only main and kanban ,"

## Root cause (honest)

MC-MEMORY-GRAPH-2 added a 3-tab sidebar to `memory-graph.html` itself, but the OTHER two pages still have only 2 tabs:

- `01_projects/mission-control/code/mission-control.html` line 514-520: only Main + Kanban
- `01_projects/mission-control/code/kanban.html` line 578-584: only Main + Kanban

Result: when you're on the main page or kanban page, you can't navigate to Memory Graph. The link only works if you're already ON the memory graph page.

## Required fix (Forge)

For BOTH files:

1. Add a third `<a>` link to the sidebar `<nav>` block, BEFORE the closing tag:
   ```html
   <a href="/memory-graph" class="nav-tab">🧠 Memory Graph</a>
   ```

2. Set the `active` class on the right tab depending on which page it is:
   - `mission-control.html` (serves `/`): Main tab has `class="nav-tab active"`, Kanban has `class="nav-tab"`, Memory Graph has `class="nav-tab"`
   - `kanban.html` (serves `/kanban`): Main has `class="nav-tab"`, Kanban has `class="nav-tab active"`, Memory Graph has `class="nav-tab"`
   - `memory-graph.html` (serves `/memory-graph`): Main has `class="nav-tab"`, Kanban has `class="nav-tab"`, Memory Graph has `class="nav-tab active"` (also: change the `<a class="active">` for "Memory Graph")

3. Update the version string in the sidebar footer:
   - `mission-control.html` line 520: `v1.15.0+kanban` → `v1.17.0+memory`
   - `kanban.html` line 584: `v1.15.0+kanban` → `v1.17.0+memory`
   - `memory-graph.html`: already says `v1.17.0+3d` — keep that

4. Do NOT change anything else in these files. Only the sidebar nav block + version string.

## Verification (Argus)

After the fix, verify with Playwright:

- Load `/` (mission-control.html) → sidebar shows 3 links: Main (active, gold), Kanban, Memory Graph
- Load `/kanban` (kanban.html) → sidebar shows 3 links: Main, Kanban (active, gold), Memory Graph
- Load `/memory-graph` → sidebar shows 3 links: Main, Kanban, Memory Graph (active, gold)
- Click "Memory Graph" from `/` → navigates to /memory-graph
- Click "Memory Graph" from `/kanban` → navigates to /memory-graph
- Click "Main" from `/memory-graph` → navigates to /
- Click "Kanban" from `/memory-graph` → navigates to /kanban
- No console errors
- The 3D graph still loads correctly
- The kanban still works (drag/drop, inline create, etc.)

## Out of scope

- DO NOT redesign the sidebar
- DO NOT change the memory-graph.html (already correct, just verify)
- DO NOT change any other part of mission-control.html or kanban.html
- DO NOT change the server

## Git

Commit with message: `MC-MEMORY-GRAPH-2B: add Memory Graph tab to sidebar in mission-control.html + kanban.html`
