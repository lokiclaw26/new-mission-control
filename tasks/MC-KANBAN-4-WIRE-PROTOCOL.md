---
task_id: MC-KANBAN-4-WIRE-PROTOCOL
title: Wire the explicit-running-now protocol into Thor's actual delegation flow
type: bugfix
priority: high
status: done
kanban_status: done
assignee: forge
argus_passed: true
completed: 2026-06-17T13:15:00+04:00
created: 2026-06-17T12:50:00+04:00
created_by: thor
approval_required: true
depends_on: [MC-KANBAN-3-EXPLICIT-RUNNING-STATE, MC-KANBAN-3A-CLEANUP-READY]
---

## Problem (reported by NOFI 2026-06-17 ~12:50 Dubai)

> "when u were doing a task ... the RUNNING NOW was not showing me any task u are doing ... WHY is that"

## Root cause (honest)

MC-KANBAN-3 built the explicit protocol + helper script `kanban-set-state.sh`. But **Thor did not wire it into the actual `delegate_task` call**.

When Thor delegated MC-KANBAN-3A to Forge:
- Task created → `kanban_status: ready` (from `+` button default)
- Thor called `delegate_task(goal=..., context=...)` — NO helper script called
- Forge worked, returned
- Thor called `kanban-set-state.sh done` at the end

**`running_now` was never set.** The whole orchestration flow happens with the task in `ready`, then jumps to `done`. The `running_now` column sits empty the whole time.

## Why it happened

The protocol is documented in `~/.hermes/memory` and in the task file `MC-KANBAN-3-EXPLICIT-RUNNING-STATE.md`, and the helper script exists. But Thor's actual flow is:
1. Write task file
2. Append events to events.jsonl
3. Call `delegate_task(goal=..., context=...)`

There is no step "call `kanban-set-state.sh` first to set running_now." I documented the rule but didn't follow it.

## Required actions

### Forge
1. Create a wrapper function or script that Thor can use to delegate work AND set `running_now` in one step. Suggested:
   ```bash
   # /home/nofidofi/.hermes/scripts/kanban-delegate.sh
   # Usage: kanban-delegate.sh <TASK_ID> <SUB_AGENT> "<goal>" [context_file]
   # Steps:
   #   1. Set kanban_status to running_now, assignee to <SUB_AGENT>
   #   2. Append work_started event
   #   3. Echo "ready to delegate" so Thor knows to call delegate_task
   ```
2. Or alternatively, modify the existing `kanban-set-state.sh` to add a `delegate` subcommand that does both.
3. The wrapper should also handle the "sub-agent finished" transition. Pattern:
   - Thor (before `delegate_task`): `kanban-set-state.sh <TASK> running_now <agent> "Thor delegated to <agent>"`
   - Thor (after sub-agent returns successfully): `kanban-set-state.sh <TASK> done "" ""`
   - Thor (after sub-agent blocked): `kanban-set-state.sh <TASK> blocked "" "<reason>"`
4. Update the skill `kanban-cleanup-stale-tasks` or create a new skill `thor-delegation-protocol` that documents the new pattern.
5. Add a small CLI helper that does the typical "set running_now + log work_started" pair in one call so Thor can't forget.

### NOT IN SCOPE
- DO NOT add cron
- DO NOT add auto-state-mutation
- DO NOT change the helper script's existing semantics
- DO NOT touch the parser or serve.py
- DO NOT add new UX features
- DO NOT modify the kanban.html page

### Argus
1. Verify the wrapper script works for: forge delegation, argus delegation, completion, blocked
2. Behavioral test: load `/kanban` in Playwright, create a new task, simulate Thor delegating to Forge → verify task moves to `running_now` → wait for sub-agent to finish → verify task moves to `done`
3. Verify the existing `kanban-set-state.sh` still works the same way
4. Verify Mission Control still loads

## Acceptance criteria

- [ ] Wrapper script exists and is executable
- [ ] Wrapper sets `kanban_status: running_now` + assignee + appends `work_started` event
- [ ] All 4 transitions tested: running_now (forge), running_now (argus), done, blocked
- [ ] Existing `kanban-set-state.sh` unchanged
- [ ] Mission Control still HTTP 200
- [ ] Playwright behavioral test passes
- [ ] Commit created, pushed (or auto-sync cron flush)
