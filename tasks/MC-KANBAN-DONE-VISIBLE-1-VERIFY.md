---
id: MC-KANBAN-DONE-VISIBLE-1-VERIFY
title: Argus visual verify Done column visibility fix
project: mission-control
created_by: thor
assigned_to: argus
status: in_progress
priority: high
created_at: 2026-06-19T11:30:00+04:00
updated_at: 2026-06-19T11:30:00+04:00
current_stage: verify
blocker: ""
data_source: thor-direct
description: "MC-KANBAN-DONE-VISIBLE-1 (commit 455221f): make Done column visible. CSS opacity 0.75→1.0, border grey→green, sort done DESC by updated. Need Playwright screenshots proving: (1) Done column shows recent task at top in solid green, (2) your task MC-AUTO-20260619023628-C86507 (ESP32+TFT DIY ideas) is visible at the top of the done column, (3) no regression on the other 5 columns."
kanban_status: archived
has_result: true
---
## Result
**Date:** 2026-06-19T11:41:10+04:00 Dubai
**By:** thor
**Status:** complete

Argus visual verify PASS. 9/9 checks. Done column now visible at full opacity with green border, recent task at top. Screenshots saved to 00_company_os/qa/mc-kanban-done-visible-1/.

---

# Argus visual verify MC-KANBAN-DONE-VISIBLE-1

The Done column was rendering with opacity 0.75 + grey border, hiding 81 completed cards in a dim pile. NOFI couldn't see his freshly-completed task. Fix in commit 455221f changes:
- `.kanban-card.status-done` opacity 0.75 → 1.0
- border-left-color grey → green
- Done column sorts by updated DESC so newest is on top
- New toolbar toggle "recent done first" (default ON)

## Acceptance
- [ ] Screenshot 1: full board, Done column visible with your task at top
- [ ] Screenshot 2: zoom on Done column, cards are solid green, no dim/fade
- [ ] Screenshot 3: zoom on the topmost card in Done — it should be MC-AUTO-20260619023628-C86507 (5 ideas for ESP32+TFT DIY)
- [ ] Screenshot 4: 5 other columns unchanged (Triage/Todo/Ready/Running Now/Blocked)
- [ ] Screenshot 5: toolbar shows the new "recent done first" checkbox
- [ ] No console errors
