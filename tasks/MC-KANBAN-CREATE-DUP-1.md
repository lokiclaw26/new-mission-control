---
id: MC-KANBAN-CREATE-DUP-1
title: Fix kanban-create creating 2 tasks + auto-clone stuck in running_now after parent completes
project: mission-control
created_by: thor
assigned_to: forge
status: done
priority: high
created_at: 2026-06-19T15:45:00+04:00
updated_at: 2026-06-19T15:45:00+04:00
current_stage: ready
blocker: ""
data_source: nofi-bug-report
result: ""
description: "NOFI 2026-06-19 15:45 Dubai: 'why when i creat a task in kanban ... automatically it creates 2 tasks ... and also when the actual task is completed .. 1 GET STUCK IN running now ... FIX THIS ISSUE ... when i creat a task it shouldnt make 2 TASKS .. only 1 actual task .. like now.. the actual task was done and 1 still stuck in runnning now without any action'. See task file for full DoD. Forge owns build, Argus owns verify."
kanban_status: done
has_result: true
---
## Result
**Date:** 2026-06-20T00:06:21+04:00 Dubai
**By:** forge
**Status:** complete

Fix shipped (Design A). kanban-auto-dispatch.sh no longer calls ondemand.dispatch() — the original MC-KANBAN-CREATE-* task IS the work. PATCHes ready->running_now directly via the kanban API. Live verified: FORGE-TEST-NO-CLONE-1 dispatched as 1 card (no clone created). kanban-auto-execute.sh needs no change (already matches MC-KANBAN-CREATE-*). kanban-auto-done.sh signal F is now a no-op (comment-only). New kanban-cleanup-legacy-clones.sh archives stuck MC-AUTO-* orphans (idempotent, --dry-run supported). Smoke tests + production evidence in 00_company_os/04_agents/logs/2026-06-19/forge-MC-KANBAN-CREATE-DUP-1.md. Committed (1474395) and pushed to origin/main.

---

# MC-KANBAN-CREATE-DUP-1: Stop the auto-clone + stuck-running-now leak

**Owner:** Forge (build) + Argus (verify) — Thor orchestrates only
**Source:** NOFI chat 2026-06-19 15:45 Dubai
**Priority:** HIGH — breaks the user's mental model of "1 task I created = 1 task on the board"

## Bug — repro confirmed

1. NOFI creates 1 task in the kanban UI (e.g. via the New Task button)
2. Within 60s, `kanban-auto-dispatch.sh` polls the board, sees the new `ready` task, and:
   - PATCHes it to `running_now`
   - **Creates a second task file** with id `MC-AUTO-XXXXXXXX-XXXXXX` (the "auto-clone") also at `running_now`
   - Records the clone in events.jsonl as a `task_dispatched` event
3. `kanban-auto-execute.sh` polls every 2m, sees the clone, spawns a `hermes -z` subagent on it, subagent writes a result
4. `kanban-auto-done.sh` polls every 1m, sees the clone has a result, moves **the clone** to `done`
5. The ORIGINAL task (the one NOFI actually created) is moved to `done` by the `kanban-save-result.sh` script when the result is written
6. **But if the parent's done move failed, or if the clone was created with no parent link, the clone stays in `running_now` forever with no agent attached to it**

## What I confirmed by reading code (no modifications)

- `kanban-auto-dispatch.sh` creates the auto-clone but **does not record `parent_id`** in either the original task's frontmatter or the clone's frontmatter
- `kanban-auto-done.sh` has 6 detection signals but **none of them use parent/child relationship**. Signal F (`child MC-AUTO-* is done → move parent`) exists, but it depends on body-text grep for "Active work (MC-AUTO-...)" which is fragile and only works if the parent's body text happens to contain the clone's id
- `kanban-save-result.sh` writes `has_result: true` to the parent but does NOT mark the parent `done` in the kanban PATCH (that's auto-done's job)
- The clone and the parent are TWO separate task files in the kanban — both visible in the UI, both take up a column slot

## The fix — what to do

There are TWO valid designs. Pick one and ship it. NOFI's words: "when i creat a task it shouldnt make 2 TASKS .. only 1 actual task". So the chosen design must result in 1 visible task per user action.

### Design A (recommended): don't create a clone at all

The original `MC-KANBAN-CREATE-*` task IS the one the pipeline operates on. `kanban-auto-dispatch.sh` should:
- PATCH the original from `ready` → `running_now`
- Record `dispatched_via: kanban-auto-dispatch` in events.jsonl
- That's it. No second file. No clone.

`kanban-auto-execute.sh` should:
- Find the `running_now` task
- Read its body for the work spec
- Spawn `hermes -z` with the work spec inline
- Write the result back to the SAME task

`kanban-auto-done.sh` already does the right thing once the result lands on the original task.

**Why this is right:** the auto-clone was a workaround from when the auto-process pipeline couldn't dispatch the original task. Now that the pipeline can, the clone is just cruft.

**Implementation:**
1. `kanban-auto-dispatch.sh`: remove the "create MC-AUTO-* child" branch entirely. Just PATCH the original to `running_now` and append the event. Add a `discovered_via: kanban-auto-dispatch` field to the event.
2. `kanban-auto-execute.sh`: instead of reading the `MC-AUTO-*` clone, read the original `running_now` task. Spawn the subagent with its body. Write the result back.
3. `kanban-auto-done.sh`: signal F (child done → move parent) becomes dead code. Remove or keep as a no-op. Signals A/B/C/D/E handle the rest.
4. **Backfill:** for any existing `MC-AUTO-*` clones with no result and no agent, mark them `archived` with reason "legacy auto-clone, no longer needed" and stop processing them.

### Design B (alternative, NOT recommended): keep the clone but link it properly

If the auto-clone must stay (e.g. for audit trail), then:
1. `kanban-auto-dispatch.sh` records `parent_id: <original-task-id>` in the clone's frontmatter
2. `kanban-auto-done.sh` signal F uses `parent_id` lookup, not body-text grep
3. `kanban-save-result.sh` is updated to mark the parent done when result is written
4. The clone is moved to `done` automatically when the parent is

**Why this is wrong:** it adds complexity, doesn't fix the "2 tasks visible" problem, and leaks clones if the parent-done move fails.

## Definition of Done (verify each before reporting back)

- [ ] After this fix, creating 1 task in the kanban UI results in **exactly 1** task visible on the board, in `running_now`, then `done`
- [ ] No `MC-AUTO-*` task is created by the dispatch path
- [ ] All existing `MC-AUTO-*` clones with no result are archived with reason "legacy auto-clone"
- [ ] The 4-stage pipeline (process → dispatch → execute → done) still works end-to-end: drop a card → executes → done
- [ ] Existing `kanban-save-result.sh` behavior unchanged (writes `has_result: true`, kanban-done picks it up)
- [ ] All changes committed + pushed (`git push origin main`)
- [ ] Argus verifies with 1 manual repro: create a task in UI, screenshot the board shows exactly 1 card, let it complete, screenshot shows 1 card in done and zero cards in running_now

## Files to edit

- `~/.hermes/scripts/kanban-auto-dispatch.sh` — remove clone-creation branch
- `~/.hermes/scripts/kanban-auto-execute.sh` — dispatch the original `running_now` task, not a clone
- `~/.hermes/scripts/kanban-auto-done.sh` — remove or no-op signal F (parent-from-child); keep A/B/C/D/E
- `~/.hermes/scripts/kanban-cleanup-legacy-clones.sh` — NEW: one-shot script to archive existing `MC-AUTO-*` orphans

## DO NOT

- Do NOT change the PATCH API surface
- Do NOT change the events.jsonl schema in a breaking way (add fields, don't rename)
- Do NOT touch the MC server code
- Do NOT touch auth/billing/LAN code
- Do NOT add new dependencies

## Org rule reminder

You are Forge. You ship. If something breaks, you debug it. Thor (me) does NOT touch code. If you need a design decision (A vs B), pick Design A — NOFI said "only 1 actual task" and that aligns with A.
