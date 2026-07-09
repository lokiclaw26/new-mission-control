---
id: MC-019-PENDING-ORDERS
title: Stage 19 — Pending Orders panel (order-receipt, no auto-fix)
project: mission-control
created_by: nofi
assigned_to: forge
status: done
priority: high
created_at: "2026-06-11T13:35:00+00:00"
updated_at: "2026-06-11T14:00:00+00:00"
current_stage: ship
blocker: ""
data_source: real
description: "Current fix-order button only appends a generic system_event to events.jsonl. NOFI approved: button must log a STRUCTURED order with order_id, recommended_fix, requires_chat_confirmation=true, status=pending, requested_by=nofi. Add a Pending Orders panel that shows every pending order. NO auto-fix. NO auto-delete. NO file modification from the button. Thor only acts on explicit chat confirmation 'Thor, do it' or 'Thor, execute pending order [order_id]'."
acceptance: "(1) Click 'Send fix order to Thor' on any warning → POST /api/data/order returns {ok: true, order_id, status: pending, requires_chat_confirmation: true, recommended_fix}. (2) Event appended to events.jsonl with event_type='fix_order' (extended schema, 14 allowed values), title='FIX ORDER: <text>', message includes 'requires_chat_confirmation: true', and order_id in a new field. (3) New /api/data/orders endpoint returns all pending orders. (4) New 'Pending Orders' panel in dashboard shows: order_id, timestamp, source warning, recommended fix, status, requested_by. (5) Button click does NOT delete any file, close any task, hide any warning, or execute code. (6) Status flow: pending → only changed by Thor in chat on explicit 'Thor, do it' command. (7) No auto-resolve. (8) No secrets. (9) No console errors. (10) start-mc.sh works. (11) demo hidden."
argus_result: pass
---

## Brief
Add real order-receipt semantics. The button creates a structured order, the dashboard surfaces it in a Pending Orders panel, and Thor only acts when NOFI says so in chat. No hero mode, no auto-fix, no auto-delete.

## Acceptance details
- serve.py: change `_append_fix_order_event` to use event_type=`fix_order` (extend event-schema.md with this new allowed value), include `order_id: <uuid8>`, `recommended_fix: <auto-derived from warning text>`, `requires_chat_confirmation: true`, `status: pending`, `requested_by: nofi`, `chat_confirmation_phrase: "Thor, do it"` (or "Thor, execute pending order <order_id>"), `execution_locked_reason: "NOFI directive 2026-06-11: no auto-fix from dashboard buttons"`. Add new endpoint GET /api/data/orders returning all events.jsonl rows where event_type=fix_order AND status in (pending, in_progress).
- mission-control.html: add a new §8 "Pending Orders" panel that reads from /api/data/orders. Each row shows: order_id, timestamp, source warning text, recommended fix, status pill, requested_by. Include a clear "⚠ Requires chat confirmation: 'Thor, do it' or 'Thor, execute pending order [id]'" note. Empty state: "✓ No pending orders — waiting for NOFI input."
- memory entry 010: honored. This task file, the task_created + task_assigned events, and the state.json update are all on disk BEFORE Forge edits any code.

## Constraints
- Stdlib Python only. No new imports (uuid module is stdlib if needed).
- No breaking changes to existing GET endpoints. The /api/data/order POST still returns the same fields PLUS the new order_id.
- No changes to the Warnings panel logic (Stage 18).
- No changes to the existing /api/data/order endpoint contract for the button — only ADD new response fields.
- No auth, no token usage, no public internet.
- The event-schema.md must be updated to add `fix_order` as an allowed event_type.

## Execution rule (LOCKED)
Thor only acts on:
- "Thor, do it" (executes the most recent pending order)
- "Thor, execute pending order <order_id>" (executes a specific order)
- Any other phrase → no execution
