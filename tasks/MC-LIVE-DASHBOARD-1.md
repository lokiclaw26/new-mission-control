---
task_id: MC-LIVE-DASHBOARD-1
title: Make overview + agents panels reflect LIVE state from the kanban
project: mission-control
status: done
priority: critical
created: 2026-06-18
created_by: thor
assigned_to: forge
approval_required: true
approval_status: approved
approval_phrase: "NOFI: I WANT EVERYTHING LIVE ... FIX THE FUCKIN CODE"
kanban_status: done
depends_on: [MC-022-ON-DEMAND-1]
blocks: [MC-LIVE-DASHBOARD-2]
tags: [mission-control, live-data, overview, agents, kanban, source-of-truth]
---

# MC-LIVE-DASHBOARD-1 — Overview + Agents panels must be LIVE

## NOFI's directive (verbatim)
*"WHy dont u understand LIVE ... how is this possible ... the last time active for 3 agents are wrong ... last checked is wrong ... active projects wrong .. EVERYTHING IS FUCKIN WRONG ... WHY THEY ARE NOT LIVE AND CURRENT ... why do i have to ask you all the time ... FIX THE FUCKIN CODE"*

## The bug (concrete, observed)
Screenshot shows 3 things wrong simultaneously:

1. **CURRENT PROJECT: diy-hub-v1** — but the actual active project is `mission-control`
   (we are dispatching auto-kanban work to mission-control RIGHT NOW).
   Cause: `current_project` is computed as `list_subdirs(01_projects)[0]`
   (alphabetical first). It should be derived from real activity.

2. **LAST CHECK: 2h ago** — but we are running this very moment.
   Cause: `last_check` reads the most recent `### NNN.` entry in
   `00_company_os/memory-log.md`, which is a historical record. The
   user-facing "last check" should mean "last live poll succeeded", not
   "last human wrote a memory-log entry".

3. **All 3 agents show current_assignment = MC-KANBAN-3-EXPLICIT-RUNNING-STATE**
   (the task I just closed in this session). Last activity 8h/2h/9h ago.
   Cause: agent state is read from `state.json` which is updated only
   on rare explicit events. The kanban is the source of truth for
   "what is each agent working on right now".

4. **ACTIVE TASKS: 1** — but the kanban shows 0 in running_now. The
   `active_tasks` counter reads `data_source: real` task files with
   status in {assigned, in_progress, ...} but NOT kanban_status=running_now.

5. **WARNINGS: 0, FAILED: 0** — but the kanban has **3 blocked**
   (real blockers: MC-005 paid LLM key, MC-006 Firefox test, DIY-011
   diy-hub scope). Blocked count must be live.

## The fix (per-derive-from-kanban)

### Source of truth hierarchy (locked)
For every overview/agent field, prefer the **most live** source:
1. The kanban board (most live — updates on every PATCH)
2. `state.json` (less live — written on explicit transitions)
3. Task file frontmatter (least live — written on task create/update)
4. Agent log mtime (historical — only useful for "last touched something")

### Specific derivations

**Overview panel:**
- `current_project` ← the project that owns the most-recent kanban state
  change in the last 24h. Tie-breaker: project of any running_now task.
  If no kanban activity in 24h: "—" (not alphabetical first subdir).
- `active_tasks` ← count of kanban tasks with `kanban_status=running_now`
  (NOT data_source real + status=in_progress — that's stale).
- `failed_tasks` ← count of kanban tasks with `kanban_status=blocked`
  AND no `blocker_reason` (i.e. genuinely failed, not waiting on a
  known blocker). For now: count of blocked with empty blocker field.
- `warnings` ← sum of (kanban blocked count) + (log warns count).
  If the kanban has 3 blocked, warnings = 3 + log_warns.
- `last_check` ← `now` (every poll = "just polled"). Add a `polled_at_iso`
  field set to current server time. Display "just now" or Xs ago relative
  to the polled time, not memory-log.

**Agents panel:**
- `current_assignment` ← for each agent, the most-recently-moved-to-running_now
  task with `assigned_to=<this agent>`. If no such task, "" (not stale
  state.json value).
- `status` ← derived from kanban:
  - has running_now task assigned → "in_progress"
  - has no running task but logs touched in last 24h → "idle"
  - never touched → "never-active"
- `last_activity` ← now (since the agent is reading the live board right
  now), or last log mtime if you want history. Display "live" for active
  agents, last mtime for idle.
- `stale` ← true if `running_now > 0` but no log file mtime in 30 min
  (current behavior — keep).

**No more "2h ago" if the page is being read right now.**

### Implementation
Two files to edit:

1. `code/serve.py` — `data_overview()` and `data_agents()` functions.
   Replace their current data sources with `data_kanban()` calls +
   derived computations. Keep the function signatures + return shapes
   the same so `mission-control.html` doesn't need to change.

2. `code/mission-control.html` — small JS tweak: change "last check"
   label to "live" and display `polled_at_iso` relative time. Add a tiny
   "live" pulse indicator next to values that come from the kanban.

### Tests
- `tests/test_overview_live.py` (new) — seed a fake kanban, call
  `data_overview()`, assert active_tasks == running_now count, etc.
- `tests/test_agents_live.py` (new) — seed fake state.json + fake
  kanban, call `data_agents()`, assert current_assignment matches
  running_now for that agent.

## Acceptance criteria
- [ ] `current_project` reflects the project with the most recent
      kanban activity (NOT alphabetical first subdir)
- [ ] `active_tasks` = number of kanban tasks in running_now
- [ ] `failed_tasks` = kanban blocked-with-no-reason count
- [ ] `warnings` = kanban blocked count + log warns count
- [ ] `last_check` reflects actual poll time, not memory-log entry
- [ ] Each agent's `current_assignment` = the running_now task
      assigned to that agent (not stale state.json)
- [ ] Each agent's `status` derived from kanban (in_progress / idle / never-active)
- [ ] `last_activity` = "live" for agents with running tasks
- [ ] Reload the page — fields update without manual refresh
- [ ] All existing 109/109 tests still pass + 2 new test files pass
- [ ] No regressions in other panels (tasks, projects, kanban)
- [ ] Argus behavioral test PASS (refresh the page 3 times, observe
      values change to reflect current kanban state)

## Out of scope
- Changing the kanban's `data_kanban()` itself (already live)
- Adding new panels or chart widgets
- Polling interval changes (keep 5s)
- The memory-graph page (separate fix later if needed)

## Files to touch
- `code/serve.py` — `data_overview()` + `data_agents()` (~100 LOC edit)
- `code/mission-control.html` — small JS tweak (~20 LOC)
- `tests/test_overview_live.py` (new, ~80 LOC)
- `tests/test_agents_live.py` (new, ~80 LOC)
- `tasks/MC-LIVE-DASHBOARD-1.md` (this file)
- `00_company_os/04_agents/logs/2026-06-18/forge-mc-live-dashboard-1.md` (your log)

## Handoff to Forge
1. Read this spec.
2. Read `code/serve.py` `data_overview()` and `data_agents()` to see current code.
3. Refactor both to derive from `data_kanban()` (which is the live source).
4. Update `mission-control.html` to display `polled_at_iso` as "live" pulse.
5. Add 2 test files.
6. Run all 111+ tests, verify 0 regressions.
7. Commit + push.
8. Write your log.

## Handoff to Argus
1. Refresh the dashboard 3 times in 10 seconds.
2. Verify CURRENT PROJECT = mission-control (we are working on it).
3. Verify ACTIVE TASKS = 0 (kanban is clean, no running).
4. Verify WARNINGS = 3 (the 3 blocked items).
5. Verify all 3 agents show no current assignment (none has running task).
6. Verify LAST CHECK = "just now" or Xs ago < 10s.
7. Write your log.

## Self-criticism
- This is a 100-LOC refactor with a clear input/output contract. Low risk.
- Watch out for the "data_source: real" trap: many real tasks don't have
  that field set, and even if they do, the kanban_status is the truth.
- The "blocked vs failed" distinction matters: "blocked" with a real
  reason (paid LLM key) is NOT a failure, it's a known wait. Don't lump
  them together.
- Don't introduce new fields the frontend can't render.

NOFI wants it LIVE. Build it LIVE.
