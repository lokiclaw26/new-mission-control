---
title: "MC-RESULT-VISIBLE-1 — make agent results visible on kanban cards"
status: done
kanban_status: done
priority: high
assigned_to: forge
created_at: 2026-06-22T15:30+04:00
project: mission-control
---


## Research started (auto-process)

The auto-process cron picked up this task on 2026-06-22T15:33:58+04:00 Dubai. v1 auto-process does not perform real research yet — it just moves the card out of triage and sets the assignee via the title heuristic (research→thor, qa/test/verify→argus, else→forge; `auto_assign:` frontmatter overrides). For v2 (real LLM research), see MC-AUTO-PROCESS-1 follow-up.

# MC-RESULT-VISIBLE-1 — Persist agent results so they show on the kanban card

## Context (do NOT redo this discovery — Thor already did it)

NOFI created a test task: "test, if ok write back all good" → assignee=argus. Argus did the work and PATCHed the task to done WITH a result text. The result IS in `events.jsonl` and the argus log file, but the kanban card shows `DONE` with no result.

**Verified facts (Thor, 2026-06-22 15:25 Dubai):**

- The UI **already has** the result rendering logic at `kanban.html` line 1398-1400:
  ```js
  ${t.has_result ? `
    <div class="result-teaser">${esc(t.result_teaser || '')}</div>
    <button type="button" class="result-button" data-action="view-result" data-task-id="${esc(t.task_id)}">📋 Result</button>` : ''}
  ```
- The board projection (`kanban_parser.build_board`) at `kanban_parser.py` line 447-448 and 547-548 already extracts a `## Result` section via `_extract_result_section(body)`.
- The expected format (from `_extract_result_section` lines 307-310):
  ```markdown
  ## Result
  **Date:** 2026-06-22T15:23:30+04:00
  **By:** argus
  **Status:** success

  <result text>
  ```
- **The bug:** the PATCH endpoint at `serve.py` line 1753 (`patch_kanban_task`) ONLY accepts `new_status` and ignores any other fields in the body. So when agents PATCH `{status: done, result: "all good"}`, the `result` is silently dropped — never reaches the task file.
- Argus's last subagent message confirmed this: `has_result=False is just because the board projection doesn't surface the result field for the GET endpoint — the PATCH response confirmed the result was accepted`.

**The test task:** `MC-KANBAN-CREATE-20260622111708-F71B07` is in done state but the card shows no result. After this fix, the card should show a "📋 Result" button with teaser "all good — kanban round-trip test passed. MC :8767 healthy, task verified in running_now, PATCH→done succeeded."

## Scope (NON-NEGOTIABLE — DO NOT exceed)

1. **DO NOT touch kanban crons** (jobs.json, kanban-auto-*.sh).
2. **DO NOT touch MC-LLM-BURN-FIX-1 or MC-SESSION-BUDGET-1 deliverables** (llm_guard.py, audit hook in kanban-auto-execute.sh, compression config).
3. **DO NOT change the PATCH endpoint signature** — just extend it to accept more fields.
4. **Make agent results visible on done cards.**
5. **Backward-compatible** — PATCH with only `status` (no `result`) still works as before.

## Concrete changes to make

### 1. Add a parser helper in `kanban_parser.py`

Add a new function (e.g. `upsert_result_section(task_id, result_text, metadata, root)`) that:
- Locates the task file (use the same `iterdir` logic as the existing endpoint).
- Reads it.
- Finds the `## Result` section (or appends one before the next `## ` heading, or at end of body if none).
- Replaces existing `## Result` content with new content.
- Writes the file back.
- Returns `(ok, reason)`.

**Format to write:**
```markdown

## Result
**Date:** 2026-06-22T16:50:10+04:00
**By:** forge
**Status:** success

MC-RESULT-VISIBLE-1 verified complete end-to-end on 2026-06-22T16:50 Dubai.
- Code: serve.py PATCH handler extended (+66) + kanban_parser.upsert_result_section helper (+105), already in commit 033bb61.
- Backward compat: PATCH with only status still works — verified (Test 1 in forge log).
- Result persistence: PATCH with result+done writes a ## Result section in correct format — verified with fresh task MC-RESULT-VISIBLE-1-VERIFY-20260622124935 (Task file shows: ## Result / **Date:** / **By:** forge / **Status:** success / body).
- GET surface: has_result=true + result_teaser populated — verified (curl above).
- result_recorded event: appended to events.jsonl — verified (grep showed the line).
- Idempotency: second PATCH with new result text REPLACES in place, exactly ONE ## Result heading remains — verified (grep -c returned 1).
- Original test task (MC-KANBAN-CREATE-20260622111708-F71B07): backfilled in prior forge session, card now shows result.
- Out of scope: untouched kanban crons, llm_guard.py, kanban-auto-execute.sh audit hook, compression config, kanban.html, _extract_result_section.
## Required final report

```json
{
  "status": "completed | blocked | failed",
  "files_changed": ["absolute paths"],
  "patch_endpoint_signature": "unchanged (backward compatible) | changed",
  "parser_helper_added": "upsert_result_section at /path/line",
  "test_result": {
    "task_id": "MC-KANBAN-CREATE-20260622111708-F71B07 or new test id",
    "before": "card showed no result button",
    "after": "card shows 📋 Result button + teaser 'all good — ...'",
    "evidence": "curl output or screenshot"
  },
  "out_of_scope_untouched": ["list of files NOT modified"],
  "risks": [],
  "next_recommendation": "..."
}
```

## Acceptance criteria

- [ ] PATCH `/api/data/kanban/task/:id` accepts optional `result` and `result_metadata` fields
- [ ] When `result` is present AND `status=done`, the task file's body gets a `## Result` section with the right format
- [ ] When `result` is absent, behavior is unchanged (backward compat)
- [ ] After PATCH, `GET /api/data/kanban` returns `has_result: true` and a non-empty `result_teaser` for that task
- [ ] Test task `MC-KANBAN-CREATE-20260622111708-F71B07` shows the result in the UI (either backfill it, or verify with a fresh PATCH)
- [ ] No changes to kanban crons, MC-LLM-BURN-FIX-1, or MC-SESSION-BUDGET-1 files
- [ ] Forge log: `00_company_os/04_agents/logs/2026-06-22/forge-MC-RESULT-VISIBLE-1-<hash>.md`
- [ ] Task PATCHed to done
- [ ] Commit + push to origin/main

## Out of scope

- Don't change the kanban.html rendering (it already shows result when has_result is true).
- Don't change the kanban_parser._extract_result_section (it already works).
- Don't add a /new result endpoint — just extend PATCH.
- Don't change Telegram notification flow (separate task if needed).
