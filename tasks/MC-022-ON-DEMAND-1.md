---
id: MC-022-ON-DEMAND-1
title: On-demand command interpreter ("thor, work on X")
project: mission-control
created_by: thor
assigned_to: forge
status: done
priority: high
created_at: 2026-06-16T16:35:00+00:00
updated_at: 2026-06-16T16:35:00+00:00
current_stage: build
blocker: ""
data_source: real
description: Stage 2 of value-pipeline. The morning-brief cron (MC-021) handles the SCHEDULE side of "produces value 24/7". This task handles the DEMAND side: when the user says "thor, work on X" in chat, parse X into a real task file + subagent dispatch. Closes the "as I demand" half of the standing goal. Scope: a single Python module + a Mission Control panel button + an event-driven auto-spawn. NOT a general chatbot — only literal "thor, work on <topic>" / "thor, execute pending order <id>" patterns.
acceptance:
  - New file: /home/nofidofi/NofiTech-Ind/01_projects/mission-control/code/ondemand.py (or similar). Self-contained stdlib-only.
  - It exposes a function that takes a topic string and: (a) creates a task file under tasks/ with id MC-AUTO-<timestamp>, (b) appends task_assigned + work_started events, (c) returns the task_id.
  - Mission Control "Pending Orders" panel gets a new button "Execute" per row. **Button behavior = RECEIPT ONLY (locked rule 006).** Click appends a `order_receipt` event with the order id and topic, marks the order as `receipt_pending=true`, and shows a tooltip "Confirmation required: type 'thor, execute pending order <id>' in chat". Dispatch fires only when the chat message arrives. This is interpretation (A) — safe / matches existing rule. Reversible to interpretation (B) by flipping a single flag in ondemand.py if nofi overrides.
  - The chat-side path: when nofi's chat message matches `^thor,?\s+(?:work on|execute pending order)\s+(.+)$`, the ondemand module parses the topic, creates the task, dispatches forge.
  - events.jsonl gets a `ondemand_dispatched` event with task_id, source (chat/button/cron), topic.
  - Forge subagent is dispatched via delegate_task with a self-contained prompt that includes the topic, task file path, and the locked rules.
  - End-to-end test: trigger via the panel button OR via a CLI test (e.g. `python3 -c "import ondemand; print(ondemand.dispatch('test topic'))"`), confirm task file appears, events appended, no crashes.
  - Backward-compat: existing serve.py endpoints unchanged. New endpoint is additive.
  - Idempotency: dispatching the same topic twice in 60s creates 1 task, not 2 (deduplication).
kanban_status: done
---

# MC-022 — On-Demand Command Interpreter

## Why
The standing goal is "autonomous org producing value 24/7 **as I demand**". Stage 1 (MC-021) proved the schedule side. This stage proves the demand side. Without it, the org is a metronome, not a worker.

## Trigger surface (in priority order)
1. **Chat literal**: "thor, work on <topic>" or "thor, execute pending order <id>"
2. **Mission Control "Pending Orders" panel** — new "Execute" button per row
3. **CLI**: `python3 -m ondemand dispatch "topic here"` (for testing + cron-to-demand chaining)

## Scope (tight)
- 1 new Python module: `code/ondemand.py`
- 1 new endpoint in serve.py: `POST /api/orders/execute`
- 1 new column in the Pending Orders HTML table: "Execute" button
- Event type: `ondemand_dispatched` in events.jsonl
- 60-second dedup window per topic string

## Out of scope (later)
- Natural-language intent parsing (use literal patterns only)
- Multi-step plans ("thor, build X then Y then Z")
- Cost approval flow (existing rule: nofi is sole spending authority, so any task that implies spend needs explicit gate — out of scope for this stage)
- Telegram/discord triggers (CLI/chat/MC only)

## Reference
- Existing pattern: `mc_event.py` (in 00_company_os/) handles event creation. Reuse it.
- Locked rule from memory: "NO auto-fix from dashboard buttons — button = order-receipt only, requires 'Thor, do it' or 'Thor, execute pending order [id]' in chat." → The button-click path must append an order-receipt event and then the on-demand module either dispatches immediately OR writes a pending dispatch token that chat can confirm. For this stage, the simpler path: button = direct dispatch (the user clicking the button IS the demand). Confirm with NOFI before shipping if there's ambiguity.
- Task schema: /home/nofidofi/NofiTech-Ind/00_company_os/task-schema.md (14 fields, must follow exactly)
- Mission Control serve.py is currently 1217 LOC. New endpoint should be <30 LOC.

## Verification (Argus)
1. Module imports cleanly: `python3 -c "import ondemand"` from the project dir.
2. `ondemand.dispatch("test topic")` creates a task file with valid frontmatter (id, all 14 fields, status=in_progress).
3. The task file appears in the Mission Control "Tasks" panel after refresh.
4. events.jsonl gets the right event chain: ondemand_dispatched → task_assigned → work_started.
5. Dispatching the same topic twice within 60s returns the EXISTING task_id, not a new one.
6. The new HTML button is visible in the Pending Orders panel and POSTs to /api/orders/execute.
7. The new endpoint does NOT crash on missing/malformed input (returns 400 with a clear error).
8. Existing serve.py endpoints still respond (no regression).
