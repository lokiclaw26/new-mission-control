---
task_id: MC-AUTO-PROCESS-2
assigned_to: forge
title: Make auto-process cron use kanban-delegate.sh wrapper
type: bugfix
priority: high
status: done
kanban_status: done
assignee: forge
created: 2026-06-17T16:05:00+04:00
created_by: thor
completed: 2026-06-17T16:08:00+04:00
argus_passed: true
approval_required: true
depends_on: [MC-KANBAN-4-WIRE-PROTOCOL]
---

## Problem (reported by NOFI 2026-06-17 ~15:50 Dubai)

> "task is in running now .. but it shows unassigned !! why ??"

## Root cause

`/home/nofidofi/.hermes/scripts/kanban-auto-process.sh` (runs every 2 minutes via cron) moves tasks from `triage` → `in_progress` by editing the task file directly with `sed`. It does NOT:
- Call `kanban-delegate.sh` to set `assignee` properly
- Update `kanban_status` field (which is separate from `status`)
- Append a `work_started` event with proper actor

This means:
- Auto-processed tasks show "unassigned" even when an agent should be on them
- The `kanban_status` stays at whatever it was (often `triage`), not transitioning to `ready` or `running_now`
- No event log entry for the auto-processing beyond `auto_process_started`/`auto_process_completed`
- The wrapper protocol I just built (MC-KANBAN-4) is fully bypassed by this script

## Required actions

### Forge: rewrite `/home/nofidofi/.hermes/scripts/kanban-auto-process.sh`

The new version MUST:
1. For each task with `status: triage` (Format A or Format B):
   a. **Determine the intended assignee** based on a simple heuristic:
      - If task title contains "research" or starts with "Research" → assignee: thor (since Thor is the orchestrator and research is Thor's job per the org chart)
      - If task title contains "test" or "qa" or "verify" → assignee: argus
      - Otherwise → assignee: forge (default — do real work)
      - Allow override via a frontmatter field `auto_assign: <agent>` if present (use that instead)
   b. **Call the wrapper** `kanban-delegate.sh <TASK_ID> <AGENT> "auto-process: moved from triage to ready"` to set `kanban_status: running_now` + `assignee: <AGENT>` + append `work_started` event
   c. Wait, but auto-process is the cron, not Thor. The wrapper currently sets `actor: thor` in the event. We need to either:
      - Add an `actor` parameter to the wrapper, OR
      - Edit the event AFTER calling the wrapper to change `actor: thor` → `actor: cron`
   d. **Set `kanban_status: ready`** (NOT `running_now`) — auto-process just acknowledges the task is picked up, it doesn't actually start research. Then a real sub-agent delegation later moves it to `running_now`. Actually, NOFI's intent: "auto-process should not pretend to be working" — so the task should go to `ready` not `running_now`. Use a new transition: call `kanban-set-state.sh <TASK> ready "" "auto-process: moved from triage to ready"` which appends the event with `actor: cron` automatically if the script sets the actor. Check the existing `kanban-set-state.sh` signature — if it doesn't accept an actor arg, add one.
2. Update both Format A and Format B tasks
3. Keep the "Research started (auto-process)" body note for compatibility, but it should now be appended AFTER the frontmatter is correctly set
4. Log a clear `auto_process_moved_to_ready` event

### Forge: also fix the wrapper to accept an actor arg

`/home/nofidofi/.hermes/scripts/kanban-delegate.sh` currently hardcodes `actor: thor` in the `work_started` event. Extend it to accept an optional `--actor` flag:
```bash
kanban-delegate.sh <TASK_ID> <AGENT> "<note>" [--actor=thor|forge|argus|cron]
```
Default: `thor`. The cron auto-process script will pass `--actor=cron`.

### NOT in scope (per NOFI)
- DO NOT add new features
- DO NOT add cron jobs (we're only fixing the EXISTING cron)
- DO NOT add auto-demotion
- DO NOT add auto-promotion
- DO NOT change column semantics
- DO NOT change the parser
- DO NOT touch serve.py
- DO NOT touch kanban.html
- DO NOT add new heuristics beyond what's listed above (research/qa/forge-default + override)

### Argus
1. Verify auto-process script:
   - Test with a fake triage task
   - Confirm task file has `status: in_progress`, `kanban_status: ready` (NOT running_now), `assignee: <correct agent>` set
   - Confirm a `work_started` event was appended with `actor: cron` (not thor)
   - Confirm a `auto_process_moved_to_ready` event was appended
2. Verify wrapper with `--actor` flag:
   - `kanban-delegate.sh <TASK> forge "test" --actor=cron` → event has `actor: cron`
   - `kanban-delegate.sh <TASK> forge "test"` (no flag) → event has `actor: thor` (default unchanged)
3. Verify no regression: existing kanban-delegate.sh usage (without --actor) still works the same way
4. Playwright behavioral test: create a triage task, wait for auto-process, verify it lands in Ready (not Running Now) with correct assignee
5. Commit created, pushed (or auto-sync)

## Acceptance criteria

### Script
- [ ] `/home/nofidofi/.hermes/scripts/kanban-auto-process.sh` rewritten to use `kanban-set-state.sh` and/or `kanban-delegate.sh`
- [ ] Auto-process sets `kanban_status: ready` (NOT running_now)
- [ ] Auto-process sets `assignee` based on title heuristic (research→thor, qa/test/verify→argus, otherwise→forge)
- [ ] Auto-process respects `auto_assign:` frontmatter override
- [ ] Auto-process appends `auto_process_moved_to_ready` event
- [ ] Auto-process event has `actor: cron` (not thor)
- [ ] Old "Research started (auto-process)" body note still added (compatibility)
- [ ] Format A and Format B both work

### Wrapper
- [ ] `kanban-delegate.sh` accepts `--actor=<name>` flag
- [ ] Default actor is `thor` (backwards compatible)
- [ ] Event reflects the actor correctly
- [ ] Existing 3-arg form still works without --actor

### Verification
- [ ] Manual test: create a fake triage task titled "Research about X" → after cron, task in Ready with `assignee: thor`
- [ ] Manual test: create fake task titled "Test the new feature" → in Ready with `assignee: argus`
- [ ] Manual test: create fake task titled "Build a widget" → in Ready with `assignee: forge`
- [ ] Manual test: create fake task with `auto_assign: forge` in frontmatter → overrides any heuristic
- [ ] Event log shows `actor: cron` for auto-process events
- [ ] Mission Control still loads (HTTP 200 on / and /kanban)
- [ ] No cron job count change (we're only fixing the existing one)
- [ ] All 4 Open follow-ups (Ready tasks) still in their original columns

## Notes for Forge
- The wrapper currently: validates, sets `kanban_status: running_now` (NOT what we want for auto-process)
- The auto-process should call `kanban-set-state.sh <TASK> ready "" "auto-process: ..."` instead — that sets the kanban_status without the wrapper's "I'm about to delegate" semantics
- If `kanban-set-state.sh` doesn't accept an `actor` arg, add one (similar pattern to wrapper)
- Make sure existing usage of `kanban-set-state.sh` still works (3-arg form, 5-arg form, etc.)
- The current auto-process has a `.first-version.bak` — keep that as a reference, don't delete it
