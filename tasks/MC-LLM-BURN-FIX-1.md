---
title: "MC-LLM-BURN-FIX-1 — Find real LLM source + add guards + audit log"
status: done
kanban_status: done
priority: urgent
assigned_to: forge
created_at: 2026-06-22T10:57+04:00
project: mission-control
---


## Research started (auto-process)

The auto-process cron picked up this task on 2026-06-22T11:00:51+04:00 Dubai. v1 auto-process does not perform real research yet — it just moves the card out of triage and sets the assignee via the title heuristic (research→thor, qa/test/verify→argus, else→forge; `auto_assign:` frontmatter overrides). For v2 (real LLM research), see MC-AUTO-PROCESS-1 follow-up.

# MC-LLM-BURN-FIX-1 — Real LLM source hunt + guards + audit

## Context (do NOT redo this discovery — Thor already did it)

NOFI complained: "There is some usage at the background ... i can see from morning 8%" and later "But we never spoke for last 2 hours, how come there was token usage". The token burn is real but the initial diagnosis (4 kanban crons are LLM-mode) was WRONG.

**Verified facts (Thor, 2026-06-22 10:55 Dubai):**

- `hermes cron list` shows all 4 kanban crons as `Mode: no-agent (script stdout delivered directly)`:
  - `kanban-auto-process` (id 42991853dbe0, every 2m)
  - `kanban-auto-dispatch` (id 51c15ca617ea, every 1m)
  - `kanban-auto-execute` (id 0ef074377dcf, every 2m)
  - `kanban-auto-done` (id ebf74937af2c, every 1m)
- The 4 scripts (`~/.hermes/scripts/kanban-auto-*.sh`) are pure bash. They PATCH kanban state via curl. `kanban-auto-execute.sh` shells out to `nohup hermes -z "<prompt>"` ONLY for real `running_now` tasks, guarded by 7 safety rails.
- `~/.hermes/logs/agent.log.1` has 9,518 lines tagged with `cron_51c15ca617ea_*` — but those are HISTORICAL, from before the cron was migrated to no-agent. Need to verify if any active cron is still producing them.
- The `morning-brief` cron (`8691521f5597`, `0 8 * * *`) IS LLM-mode (has a real prompt). It runs ONCE daily at 08:00 Dubai. NOT the burn source.
- The Hermes Agent gateway PID 197939 (3d 13h uptime, 4 active HTTPS connections to Telegram + Anthropic) is the main process. Could be doing keepalive.

## Goals (in order)

1. **Find the real LLM call source(s).** Trace every path that calls Anthropic/OpenAI. Active vs historical.
2. **Keep all 4 no-agent kanban crons running.** Do NOT touch them unless evidence shows they ARE burning tokens.
3. **Add `assertLLMAllowed()` guard** at every LLM call site in our code.
4. **Add `logs/llm-calls.jsonl` audit logging** at every LLM call site.
5. **Run the 10-minute idle verification** (proven via DB query + log line count).
6. **Run one kanban-card-active verification** (create test card, confirm LLM fires only with real card_id).
7. **Final report in the exact format NOFI specified.**

## Concrete search commands (run these — do not skip)

```bash
# LLM call sites
grep -R "anthropic.messages.create" -n . 2>/dev/null
grep -R "openai.chat.completions.create" -n . 2>/dev/null
grep -R "responses.create" -n . 2>/dev/null
grep -R "messages.create" -n . 2>/dev/null
grep -R "hermes -z" -n . 2>/dev/null

# Suspicious scheduling patterns
grep -R "cron_51c15ca617ea" -n ~/.hermes 2>/dev/null | head -20
grep -R "scheduled cron job" -n ~/.hermes 2>/dev/null | head -20
grep -R "morning-brief" -n ~/.hermes . 2>/dev/null | head -20
grep -R "keepalive" -n ~/.hermes . 2>/dev/null | head -20
grep -R "heartbeat" -n ~/.hermes . 2>/dev/null | head -20

# Inspect
hermes cron list
ls -lah ~/.hermes/cron/output/ 2>/dev/null
ls -lah ~/.hermes/logs/ 2>/dev/null
tail -n 300 ~/.hermes/logs/agent.log 2>/dev/null
tail -n 300 ~/.hermes/logs/agent.log.1 2>/dev/null

# Look at the most recent ACTUAL subagent runs (these are real LLM calls)
ls -lat ~/.hermes/scripts/auto-execute-*.out 2>/dev/null | head -10
```

## What to ship

### A. LLM Guard module (`/home/nofidofi/NofiTech-Ind/00_company_os/llm-guard.py` or `scripts/llm-guard.js` — match codebase language)

```python
# LLM Guard — pure helper, stdlib only
import json, os, time
from pathlib import Path

LOG_DIR = Path("/home/nofidofi/NofiTech-Ind/00_company_os/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "llm-calls.jsonl"

BLOCKED_REASONS = {"tick", "heartbeat", "idle_check", "keepalive", "scheduled_noop"}

def assert_llm_allowed(context: dict) -> bool:
    """Raises ValueError if the LLM call should be blocked."""
    if not context:
        raise ValueError("LLM call blocked: missing context.")
    reason = context.get("reason")
    trigger = context.get("trigger")
    if reason in BLOCKED_REASONS:
        raise ValueError(f"LLM call blocked: invalid idle reason: {reason}")
    if not (context.get("card_id") or context.get("job_id") or context.get("user_message_id")):
        raise ValueError("LLM call blocked: no real work item attached.")
    if trigger == "cron" and not (context.get("card_id") or context.get("job_id")):
        raise ValueError("LLM call blocked: cron without real job/card.")
    return True

def log_llm_call(entry: dict) -> None:
    """Append one JSONL row to logs/llm-calls.jsonl"""
    row = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+04:00", time.gmtime(time.time() + 4*3600)), **entry}
    with LOG_FILE.open("a") as f:
        f.write(json.dumps(row) + "\n")
```

### B. Wrap every LLM call site found

For each `messages.create` / `chat.completions.create` / `hermes -z` site, insert:
1. `assert_llm_allowed({trigger, reason, card_id, job_id, user_message_id})` immediately before the call
2. After the call returns (success or fail), `log_llm_call({agent, provider, model, trigger, reason, card_id, job_id, user_message_id, input_tokens, output_tokens, status})`

### C. Idle verification (10 min)

```bash
echo "BEFORE $(date)"
wc -l /home/nofidofi/NofiTech-Ind/00_company_os/logs/llm-calls.jsonl 2>/dev/null || echo 0
sqlite3 ~/.hermes/state.db "select count(*) from messages where content like '%scheduled cron job%';" 2>/dev/null
# wait 10 minutes, ensure NO actionable kanban card exists
sleep 600
echo "AFTER $(date)"
wc -l /home/nofidofi/NofiTech-Ind/00_company_os/logs/llm-calls.jsonl 2>/dev/null
sqlite3 ~/.hermes/state.db "select count(*) from messages where content like '%scheduled cron job%';" 2>/dev/null
```

Pass criteria: BOTH line counts unchanged, 0 new Anthropic/OpenAI calls.

### D. Active-card verification (1 kanban card test)

1. Create a kanban task with title `"LLM-BURN-FIX-TEST-1 — verify single LLM call per card"` via the kanban API
2. Wait 3 minutes for `kanban-auto-process` → `kanban-auto-dispatch` → `kanban-auto-execute` chain
3. Confirm: exactly 1 new row in `llm-calls.jsonl` with the card_id
4. Confirm: kanban card reached `done`
5. Confirm: 0 new `scheduled cron job` messages in state.db

## Out of scope (do NOT do)

- Don't disable or rewrite the 4 no-agent kanban crons.
- Don't redesign the kanban pipeline.
- Don't change the daily morning-brief cron (only fires 1x/day, not the burn source).
- Don't delete old logs — they're evidence.

## Final report format

Return EXACTLY this JSON:

```json
{
  "status": "completed | blocked | failed",
  "summary": "...",
  "kanban_crons_status": {
    "kanban-auto-process": "kept_running | changed | disabled",
    "kanban-auto-dispatch": "kept_running | changed | disabled",
    "kanban-auto-execute": "kept_running | changed | disabled",
    "kanban-auto-done": "kept_running | changed | disabled"
  },
  "real_token_sources_found": [],
  "historical_only_sources": [],
  "active_llm_sources": [],
  "files_changed": [],
  "guards_added": [],
  "audit_logging_added": true,
  "commands_run": [],
  "idle_verification": {
    "duration_minutes": 10,
    "llm_calls_before": 0,
    "llm_calls_after": 0,
    "scheduled_cron_messages_before": 0,
    "scheduled_cron_messages_after": 0,
    "result": "pass | fail"
  },
  "kanban_card_test": {
    "card_id": "...",
    "result": "pass | fail",
    "llm_calls_created": 0,
    "notes": "..."
  },
  "recommendation": "..."
}
```

## Acceptance criteria

- [ ] `assertLLMAllowed()` defined in source-of-truth language, stdlib only
- [ ] `log_llm_call()` writes to `00_company_os/logs/llm-calls.jsonl` with all required fields
- [ ] Every LLM call site in the repo is wrapped (search returned 0 unwrapped sites)
- [ ] All 4 kanban crons confirmed still active via `hermes cron list` BEFORE and AFTER
- [ ] Idle test: `llm-calls.jsonl` line count UNCHANGED, `scheduled cron job` DB count UNCHANGED
- [ ] Active test: exactly 1 new llm-calls.jsonl row with the test card_id
- [ ] Forge log written to `00_company_os/04_agents/logs/2026-06-22/forge-MC-LLM-BURN-FIX-1-<hash>.md`
- [ ] Task `MC-LLM-BURN-FIX-1` PATCHed to `done` via kanban API
- [ ] Push to origin/main

## Scope budget

This task is medium-large. If you're running out of time, ship in this order:
1. Discovery (search commands) — mandatory
2. `llm-guard.py` module — mandatory
3. Wrap call sites — mandatory (most LLM calls likely come from subagent spawn, not us; document that)
4. Audit logging — mandatory
5. Idle verification — mandatory (10 min is fine, run in parallel with writing the report)
6. Active card test — if time, otherwise document deferred
