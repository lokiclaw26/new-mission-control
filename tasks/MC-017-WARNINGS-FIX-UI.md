---
id: MC-017-WARNINGS-FIX-UI
title: Stage 17 — Warnings panel with fix-order buttons + remove Provider/Model
project: mission-control
created_by: nofi
assigned_to: forge
status: done
priority: high
created_at: "2026-06-11T12:00:00+00:00"
updated_at: "2026-06-11T12:36:01+00:00"
current_stage: ship
blocker: ""
data_source: real
description: "NOFI observed 3 real UI/UX/data issues on the live dashboard: (1) Projects 'Next action' field is stale — shows Stage 15.2 audit text even though that stage is closed; (2) Provider/Model panel is not needed — NOFI wants it removed from the dashboard; (3) App health shows 'degraded' with 1 warning, but there is no dedicated warnings panel and no way to order a fix. Fix: update project status.md next_action to current reality, hide/remove the Provider/Model panel from the HTML, add a new Warnings panel that lists every active warning from /api/data/logs and /api/data/overview with a 'Send fix order to Thor' button per warning that triggers a structured event appended to events.jsonl."
acceptance: "Projects panel 'Next action' reflects CURRENT reality (not the closed Stage 15.2 text). Provider/Model panel is removed from the HTML. New Warnings panel exists and lists all real warnings from logs/overview. Each warning has a clickable 'Send fix order to Thor' button. Clicking the button: appends a 'system_event' (FIX ORDER) to events.jsonl. Dashboard still loads, refresh works, no console errors, no secrets exposed, demo data still hidden, start-mc.sh still works, all real/live."
argus_result: pass
---

## Brief
Three real issues from NOFI's screenshot, all visual/UX:
1. Projects.next_action is stale (Stage 15.2 audit closed; next action must reflect current step).
2. Provider/Model panel is dead weight (2 red rows, no action) — remove.
3. Warnings are not first-class — there is no dedicated place to see them and no way to order a fix.

## Acceptance details
- /api/data/projects returns a fresh `next_action` value that matches status.md on disk.
- /api/version or new endpoint exposes whether Provider/Model panel is enabled (default: disabled).
- mission-control.html: Provider/Model panel div is removed (or hidden via a class+flag, NOFI picks).
- New "Warnings" panel rendered in the body, between Action Required and Tasks (or wherever the existing Action Required panel sits). Each warning = one row: icon, text, source file link, "Send fix order to Thor" button.
- Click handler: appends a structured event to events.jsonl with event_type=`nofi_approval_required` (or new event_type `fix_order_issued`), task_id is empty (it's a system-level warning), message contains the warning text + a clear "ACT NOW" directive.
- The HTML must read warnings from /api/data/logs (which has the `warnings` count and the recent events array) AND from /api/data/overview (warnings.breakdown). It must NOT hardcode any warning text.
- All existing functionality preserved: refresh, last-refreshed, auto-refresh, no console errors, no secrets, no demo leakage, start-mc.sh still works.
