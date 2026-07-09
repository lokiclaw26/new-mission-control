---
name: thor-delegation-protocol
description: Use when Thor (or any agent) is about to call delegate_task to hand a kanban task to a sub-agent (forge, argus, or another thor). The state transition to running_now MUST happen in the same atomic operation as the delegation — not as a separate step that can be forgotten.
---

# Thor Delegation Protocol (MC-KANBAN-4)

## The rule

**Normal delegation = one atomic call, not two.**

When you are about to call `delegate_task` to send a kanban task to a sub-agent, you MUST first call the wrapper:

```bash
bash /home/nofidofi/.hermes/scripts/kanban-delegate.sh <TASK_ID> <assignee> "[optional note]"
```

Then — and only after the wrapper prints `Now safe to call delegate_task for this task.` — you call `delegate_task`.

Do **NOT** call `kanban-set-state.sh` and `delegate_task` as two separate steps. That is exactly the bug that broke the RUNNING NOW column.

## Why this exists

NOFI (2026-06-17 ~12:50 Dubai) reported:

> "when u were doing a task ... the RUNNING NOW was not showing me any task u are doing ... WHY is that"

Root cause: Thor had to remember TWO actions — set `kanban_status=running_now` AND call `delegate_task`. Thor was forgetting the first one, so tasks sat in `ready` the whole time, then jumped to `done`. The `running_now` column was empty for the duration of real work.

The wrapper makes the two a single atomic op. If the wrapper fails, the delegation must not happen. If the wrapper succeeds, delegation is sanctioned.

## Canonical delegation sequence

```bash
# 1. ATOMIC: set state + log event (the wrapper)
bash /home/nofidofi/.hermes/scripts/kanban-delegate.sh MC-FOO-1 forge "brief goal"

# 2. ONLY after wrapper prints "Now safe to call delegate_task"
delegate_task(goal="...", context="...")
```

## Completion / blocked sequence (sub-agent returns)

The sub-agent does NOT touch the kanban. The agent that called `delegate_task` (typically Thor) is responsible for the next transition.

```bash
# Success
bash /home/nofidofi/.hermes/scripts/kanban-set-state.sh MC-FOO-1 done "" ""

# Sub-agent blocked
bash /home/nofidofi/.hermes/scripts/kanban-set-state.sh MC-FOO-1 blocked "" "<reason>"
```

`kanban-set-state.sh` is fine to use directly for these terminal states. The wrapper is ONLY for the "I'm about to delegate" case.

## What the wrapper guarantees

- Validates the task file exists under `01_projects/*/tasks/<TASK_ID>.md`
- Validates assignee is one of: `thor`, `forge`, `argus`
- PATCHes the running Mission Control server (`http://192.168.0.29:8767`) with `kanban_status=running_now` + `assignee=<agent>`
- Updates the task file frontmatter (`kanban_status` and `assignee` lines)
- Appends a `work_started` event to `00_company_os/04_agents/events.jsonl`
- Prints a clear "Now safe to call delegate_task" line on success
- Exits non-zero on any validation or HTTP failure — no silent half-state

## What NOT to do

- ❌ Call `kanban-set-state.sh` + `delegate_task` as two separate steps
- ❌ Call `delegate_task` first and then try to "fix" the state after
- ❌ Skip the wrapper because the task is "small" or "obvious"
- ❌ Mutate `kanban_status=running_now` by hand-editing the task file without going through the wrapper (you'd skip the server PATCH and the event log)
- ❌ Use the wrapper for terminal states (done, blocked) — use `kanban-set-state.sh` directly for those

## Failure recovery

If the wrapper fails:
1. Read the error. The exit code tells you why:
   - `2` = bad arguments
   - `3` = invalid assignee
   - `4` = task file not found
   - `5` = server PATCH failed
2. Do **NOT** proceed with `delegate_task` until the wrapper succeeds. A task in `ready` with a running sub-agent is the exact bug we are fixing.
3. If the server is down (HTTP 000), fix the server first. Do not bypass the wrapper.

## Related

- `kanban-cleanup-stale-tasks` skill — for batch migrations of stale cards
- Spec: `01_projects/mission-control/tasks/MC-KANBAN-4-WIRE-PROTOCOL.md`
- Helper: `/home/nofidofi/.hermes/scripts/kanban-set-state.sh` (terminal states only)
- Helper: `/home/nofidofi/.hermes/scripts/kanban-delegate.sh` (delegation only)
