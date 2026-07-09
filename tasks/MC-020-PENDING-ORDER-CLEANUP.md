---
id: MC-020-PENDING-ORDER-CLEANUP
title: Stage 20 — Pending order cleanup + smoke-test fixture removal
project: mission-control
created_by: nofi
assigned_to: forge
status: done
priority: normal
created_at: "2026-06-11T14:05:00+00:00"
updated_at: "2026-06-11T18:30:00+00:00"
current_stage: ship
blocker: ""
data_source: real
description: "NOFI approved: clean up the 8 pending test orders from Stage 19 verification. Cancel/archive orders that are clearly test artifacts (smoke POSTs, backcompat POSTs, weird-thing POSTs). The 1 smoke-test warning fixture (test-warn-argus.md) is confirmed to be only a test fixture from Stage 4 — Forge may remove it and the warning will go away. Real orders (if any) MUST be preserved. Real project data, real task files, real warnings MUST NOT be touched."
acceptance: "(1) The 8 pending test orders are no longer in /api/data/orders (status moved from pending to cancelled or archived). (2) test-warn-argus.md is removed from disk and a deletion event is logged. (3) Warning count drops from 1 to 0. (4) No real project data, real task files, or real warnings were modified. (5) Fix-order button still works (creates new pending orders). (6) Dashboard still loads. (7) No secrets exposed. (8) No console errors. (9) start-mc.sh still works. (10) Git commit exists after pass."
argus_result: pass
---

## Brief
8 pending orders, all from Stage 19 verification POSTs (Thor + Argus + Forge smoke tests). All have warning_text values like "smoke test warn", "backcompat test", "weird thing" — clearly test artifacts. The 1 warning they refer to (test-warn-argus.md) is from Stage 4 and is a test fixture only.

## Acceptance details
- Forge: identify each of the 8 orders. For each, mark status="cancelled" (or "archived" — pick one, document choice) in events.jsonl by appending a follow-up `fix_order` event with the same `order_id` and `status: cancelled` (or modify the original event in-place — your call but document it). Add a `cancelled_by: "thor"` field and a `cancellation_reason: "cleanup of Stage 19 test artifacts"` field.
- Forge: confirm test-warn-argus.md is a test fixture (it has frontmatter `officer: argus, level: warn, title: smoke test - log level=warn parsing` — clearly a fixture)
- Forge: delete the file via os.remove() OR pathlib.Path.unlink()
- Forge: append a deletion event to events.jsonl with event_type=`system_event`, actor=`forge`, message="Removed test fixture: 00_company_os/04_agents/logs/2026-06-10/test-warn-argus.md (per NOFI approval MC-020)"
- Forge: do NOT touch any other file
- Verify: curl /api/data/orders returns 0 orders; curl /api/data/logs shows warnings=0; app_health should now be "ok"; test-warn-argus.md no longer exists

## Constraints
- Stdlib Python only
- No breaking changes to /api/* GET response shapes
- No changes to sendFixOrder() or the button behavior
- No changes to the Pending Orders panel rendering (it should now show the empty state since 0 orders)
- No auth, no token usage, no public internet
- No new task files except the 5 closure events
- No touching real project files, real task files, real warnings
- Server restart required if serve.py changes. (If you only edit events.jsonl + delete the fixture, no restart needed.)
