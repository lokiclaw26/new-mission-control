---
id: MC-WARNINGS-AUTOCLEAR-1
title: "Warnings auto-clear (mark-resolved + audit trail)"
status: done
kanban_status: done
priority: medium
assigned_to: forge
created: 2026-06-29
updated: 2026-06-29
project: mission-control
has_result: true
---

## Result
**Date:** 2026-06-29 11:25 Dubai
**By:** thor
**Status:** complete

Resolved the warning-rotation noise (warnings that stay on the list forever even after the underlying bug is fixed).

**What shipped:**

1. **`/home/nofidofi/.hermes/scripts/resolve-warnings.py`** (NEW, 200 LOC)
   - Migrates legacy string-form warnings into objects `{text, ts, resolved, resolved_at}`
   - On every run, moves any warning older than 24h with no matching event in `events.jsonl` from `state.json.warnings` to `state.json.resolved_warnings`
   - Idempotent — safe to re-run
   - Atomic write via `.tmp` + `replace()`
   - Extracts the warning's true timestamp from its embedded `(YYYY-MM-DDTHH:MM:SSZ, errors.log)` parenthetical (not the state-write `updated` field — bug fix during dev)

2. **`state.json` schema v1.18**:
   - `warnings`: array of `{text, ts, resolved: bool, resolved_at: ISO|null}` — active only
   - `resolved_warnings`: array of same shape with `resolved: true` — full audit trail preserved

3. **Morning-brief cron prompt** (job `8691521f5597`)
   - New `STEP -1 — RESOLVE-WARNINGS` section that runs the script BEFORE reading state.json
   - WARNINGS section updated to explain the object format and read only `resolved: false` entries
   - Optionally surfaces `resolved_warnings` count as a separate "audit trail" line

**Tested:**

- Dry-run + real-run on current state: 1 warning auto-cleared (the 2026-06-27 morning-brief schema-fix warning), 1 retained (the 2026-06-28 MC_ADMIN_TOKEN probe, ~18h old, within 24h window — conservative default).
- Idempotency: re-running produces `resolved_warnings=0` newly resolved.
- Manual cron trigger produced a brief showing `WARNINGS: 1 active / resolved_warnings: 1` — exactly the desired output.

**NOT in scope (deliberate):**

- No mark-resolved via task file `result: success` link (the 24h-event-absence heuristic is simpler and self-healing).
- No config knob for resolution window yet — easy follow-up if NOFI wants <24h or >24h.

**Files changed:**

- `00_company_os/state.json` (migration + first auto-clear)
- `~/.hermes/scripts/resolve-warnings.py` (new)
- `~/.hermes/cron/jobs.json` (morning-brief prompt update, restored after accidental overwrite)
- `~/.hermes/cron/output/8691521f5597/2026-06-29_11-25-13.md` (test output)