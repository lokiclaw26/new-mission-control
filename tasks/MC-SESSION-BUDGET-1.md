---
title: "MC-SESSION-BUDGET-1 — per-session token budget + compression audit"
status: done
kanban_status: done
priority: high
assigned_to: forge
created_at: 2026-06-22T13:35+04:00
project: mission-control
---


## Research started (auto-process)

The auto-process cron picked up this task on 2026-06-22T13:42:55+04:00 Dubai. v1 auto-process does not perform real research yet — it just moves the card out of triage and sets the assignee via the title heuristic (research→thor, qa/test/verify→argus, else→forge; `auto_assign:` frontmatter overrides). For v2 (real LLM research), see MC-AUTO-PROCESS-1 follow-up.

# MC-SESSION-BUDGET-1 — Reduce interactive Telegram token burn via per-session budget + compression audit

## Context (do NOT redo this discovery — Thor already did it)

From `MC-SESSION-INVESTIGATE-1` (commit `aa5b479`):
- Session `20260613_181010_978a77` is NOFI's live Telegram DM session.
- Burn: ~3.8M tokens/hour active, 19M tokens today. Cause: every API call re-sends ~140K-180K cumulative context.
- Compression IS already configured (gateway auto-compresses when context hits threshold).

**Current config (`~/.hermes/config.yaml` lines 145-153):**
```yaml
compression:
  enabled: true
  threshold: 0.5         # 50% of model context window
  target_ratio: 0.2      # compress down to 20% of original
  protect_last_n: 20     # never touch last 20 messages
  hygiene_hard_message_limit: 400
  protect_first_n: 3     # keep first 3 (system prompt anchors)
  abort_on_summary_failure: false
  codex_gpt55_autoraise: true
```

**Compression runner exists:** `/home/nofidofi/.hermes/hermes-agent/hermes_cli/partial_compress.py` (and `hermes_cli/commands.py` references it).

**Test files (read these to understand semantics):**
- `tests/test_trajectory_compressor.py`
- `tests/cli/test_compress_focus.py`, `test_compress_here.py`, `test_partial_compress.py`, `test_manual_compress.py`

## Why this task exists

- 0.5 threshold means we compress when context is HALF full — too late. We want earlier, cheaper compression.
- No audit log of when compression actually fires.
- No per-session token budget (only model-wide).
- No `/new` or `/compact` slash command (verify).

## Scope (NON-NEGOTIABLE — DO NOT exceed)

1. **DO NOT kill the active Telegram session** `20260613_181010_978a77`.
2. **DO NOT touch kanban crons** (jobs.json, kanban-auto-*.sh).
3. **DO NOT change MC-LLM-BURN-FIX-1 deliverables** (`00_company_os/llm_guard.py` and the audit hook in `kanban-auto-execute.sh`).
4. **Add or configure per-session token budget in the gateway.**
5. **Audit log when compression fires.**
6. **Verify with a long-session simulation.**

## Concrete changes to make

### 1. Add per-session token budget config (extend `~/.hermes/config.yaml`)

Add these new keys under the existing `compression:` section (don't replace — extend):

```yaml
compression:
  enabled: true
  threshold: 0.5              # existing — keep
  target_ratio: 0.2            # existing — keep
  protect_last_n: 20           # existing — keep
  hygiene_hard_message_limit: 400  # existing — keep
  protect_first_n: 3           # existing — keep
  abort_on_summary_failure: false  # existing — keep
  codex_gpt55_autoraise: true  # existing — keep

  # NEW: per-session token budget (MC-SESSION-BUDGET-1)
  per_session:
    auto_compress_at_tokens: 50000   # when input exceeds this, auto-compress
    hard_refuse_at_tokens: 90000     # refuse new turns above this, suggest /new
    max_input_tokens: 60000          # target ceiling for input size
    preserve_min_recent_messages: 8  # always keep at least this many recent msgs

  # NEW: audit logging (MC-SESSION-BUDGET-1)
  audit:
    log_file: "/home/nofidofi/NofiTech-Ind/00_company_os/logs/session-compression.jsonl"
    fields: ["timestamp", "session_id", "agent", "trigger", "tokens_before",
             "tokens_after", "summary_file", "preserved_task_ids",
             "preserved_user_prefs", "preserved_open_blockers", "model", "provider"]
```

If the config schema doesn't natively support nested keys, either: (a) add them and read via the same config loader that already handles `compression.threshold`, or (b) write a small Python module that reads config.yaml directly.

### 2. Modify the compression runner to respect the new budget

Read `~/.hermes/hermes-agent/hermes_cli/partial_compress.py` first. Wire in the new thresholds:
- Trigger compression when input tokens > `auto_compress_at_tokens` (not just at 50% of context).
- After compression, target input tokens ≤ `max_input_tokens`.
- Always preserve at least `preserve_min_recent_messages` recent messages.
- At > `hard_refuse_at_tokens`, refuse with a clear message: "Session context too large. Send /new to start a fresh session or /compact to manually compress."

### 3. Add audit logging

Every time compression fires (auto or manual), append one JSONL row to the log file above with the fields listed.

### 4. Verify /new and /compact slash commands exist

```bash
grep -rn "/new\|/compact" ~/.hermes/hermes-agent/hermes_cli/ 2>/dev/null | head -20
```

If `/new` exists, document it. If `/compact` exists, wire it to call the compression runner + audit-log. If neither exists, add them as a small handler (e.g., in `commands.py`).

### 5. Long-session simulation (mandatory verification)

Write a small Python test that:
1. Builds a synthetic conversation with ~150 messages (mimicking a long Telegram session).
2. Measures token count before (should be ~140K-180K with realistic content).
3. Calls the compression runner.
4. Measures token count after (should be ≤ `max_input_tokens` = 60000).
5. Verifies that the active task ID (e.g. `MC-SESSION-BUDGET-1`) is preserved in the summary.
6. Verifies that NOFI's most recent user instruction is preserved in the summary.
7. Verifies audit log got one new row with all required fields.

Save the test as `tests/test_session_budget.py` or wherever the existing compression tests live.

## Concrete commands to run

```bash
# 1. Read the compression code
cat ~/.hermes/hermes-agent/hermes_cli/partial_compress.py | head -100

# 2. Check how config is loaded
grep -rn "compression\b" ~/.hermes/hermes-agent/hermes_cli/ | grep -v __pycache__ | grep -v test_ | head -10

# 3. Find compression trigger sites
grep -rn "auto.compress\|context.*compress\|threshold.*0.5\|should_compress" ~/.hermes/hermes-agent/hermes_cli/ 2>/dev/null | head -20

# 4. Existing /new, /compact
grep -rn "slash.*new\|/new\b\|slash.*compact\|/compact\b" ~/.hermes/hermes-agent/hermes_cli/ 2>/dev/null | head -10

# 5. Test existing compression first to baseline
cd ~/.hermes/hermes-agent && python3 -m pytest tests/cli/test_partial_compress.py -x -v 2>&1 | tail -20

# 6. Current config read-back
python3 -c "
import yaml
with open('/home/nofidofi/.hermes/config.yaml') as f:
    cfg = yaml.safe_load(f)
print(json.dumps(cfg.get('compression', {}), indent=2))
" 2>/dev/null
```

## Out of scope

- Don't modify the model or provider config (the `minimax` provider is fine).
- Don't touch the Telegram gateway code unless it's to add /new or /compact.
- Don't change memory/skill storage formats.

## Required final report

Return EXACTLY this JSON:

```json
{
  "status": "completed | blocked | failed",
  "files_changed": ["/absolute/paths"],
  "current_thresholds_found": {
    "threshold": "0.5 of context window",
    "target_ratio": 0.2,
    "protect_last_n": 20,
    "audit_log": "exists or null"
  },
  "new_thresholds_added": {
    "auto_compress_at_tokens": 50000,
    "hard_refuse_at_tokens": 90000,
    "max_input_tokens": 60000,
    "preserve_min_recent_messages": 8
  },
  "compression_behavior": "auto when input > auto_compress_at_tokens (was: 50% of context window)",
  "verification": {
    "tokens_before": 0,
    "tokens_after": 0,
    "memory_preserved": true,
    "audit_log_row_added": true
  },
  "risks": [],
  "next_recommendation": "..."
}
```

## Acceptance criteria

- [ ] `compression.per_session.*` keys added to config.yaml
- [ ] `compression.audit.*` keys added to config.yaml
- [ ] Compression runner reads the new per-session budget
- [ ] Audit log written to `00_company_os/logs/session-compression.jsonl` with all required fields
- [ ] `/new` and `/compact` slash commands exist (or added)
- [ ] Simulation test passes: 140K tokens → ≤60K after compression, preserves task_id + recent instructions
- [ ] Existing compression tests still pass (`pytest tests/cli/test_partial_compress.py`)
- [ ] Forge log: `00_company_os/04_agents/logs/2026-06-22/forge-MC-SESSION-BUDGET-1-<hash>.md`
- [ ] Task PATCHed to done
- [ ] Commit + push to origin/main

## Scope budget

This is a code+config change. 15-min budget is tight. Priority order if running out of time:
1. Add the config keys (5 min) — MANDATORY
2. Add the audit log emission (5 min) — MANDATORY
3. Verify the existing compression already does the right thing (5 min) — DOCUMENT the existing behavior if so
4. Slash commands — defer if no time
5. Simulation test — defer if no time
