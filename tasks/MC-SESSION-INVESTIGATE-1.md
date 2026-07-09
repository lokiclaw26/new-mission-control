---
title: "MC-SESSION-INVESTIGATE-1 — investigate session 20260613_181010_978a77"
status: done
kanban_status: done
priority: high
assigned_to: forge
created_at: 2026-06-22T12:05+04:00
project: mission-control
has_result: true
---
## Result
**Date:** 2026-06-22T13:30:03+04:00 Dubai
**By:** thor
**Status:** complete

Session 20260613_181010_978a77 is LIVE, owned by NOFI (telegram:dm:266656607), platform=telegram, NOT a stuck clarify or cron. Last API call 2026-06-22T13:22:38+04:00 (in=149594 out=356 total=149950). 140 calls today, 19M tokens (~3.8M/hr when active, 0 when idle). Burn is real interactive work — DO NOT STOP. Started 2026-06-13 18:10:10 Dubai (split from 20260611_235958_a1dc04), 9 days old, never formally closed. All 10 investigation commands run. Evidence + full JSON report in forge log: 00_company_os/04_agents/logs/2026-06-22/forge-MC-SESSION-INVESTIGATE-1-7f3c91

### Result entry — 2026-06-22T13:30:21+04:00
**By:** thor
**Status:** complete

test

---
.md

---

## Research started (auto-process)

The auto-process cron picked up this task on 2026-06-22T13:12:54+04:00 Dubai. v1 auto-process does not perform real research yet — it just moves the card out of triage and sets the assignee via the title heuristic (research→thor, qa/test/verify→argus, else→forge; `auto_assign:` frontmatter overrides). For v2 (real LLM research), see MC-AUTO-PROCESS-1 follow-up.

# MC-SESSION-INVESTIGATE-1 — Investigate long-lived session 20260613_181010_978a77

## Context (Thor's discovery during MC-LLM-BURN-FIX-1)

Forge flagged in `forge-MC-LLM-BURN-FIX-1-a1b2c3.md`:
> The real burn source is the long-running interactive session `session=20260613_181010_978a77`. Started 2026-06-13 18:10:10 Dubai, still making API calls today at 11:38+. This is a 9-day-old human-driven session, likely with a stuck `clarify` button on the Telegram gateway (last gateway entry: "Telegram clarify button resolved ... user=Ahmad" at 11:30:32). The `morning-brief` cron is LLM-mode but fires ONCE daily at 08:00 — NOT the burn source.

NOFI's standing rule: investigate before action. Don't kill anything that might be live.

## Scope (DO NOT exceed)

1. **Do NOT change any kanban cron config.** Don't touch jobs.json or the 4 crons.
2. **Do NOT touch MC-LLM-BURN-FIX-1 deliverables.** `00_company_os/llm_guard.py` and the audit hook in `kanban-auto-execute.sh` are shipped and verified.
3. **Investigate the session.** Read-only only.
4. **Measure call frequency, provider, model, token usage.**
5. **Identify owner.** Is it: (a) live Telegram chat, (b) stuck clarify button, (c) cron, (d) something else?
6. **Recommend, don't act.** If safe to stop, list the steps. DO NOT execute them.

## Investigation commands (run these — read-only)

```bash
# 1. Find all session= entries for this ID in agent.log
grep "20260613_181010_978a77" ~/.hermes/logs/agent.log | head -30
echo "---"
grep -c "20260613_181010_978a77" ~/.hermes/logs/agent.log
echo "---"
# Show most recent 10 entries for this session
grep "20260613_181010_978a77" ~/.hermes/logs/agent.log | tail -10

# 2. What's the last API call timestamp and token usage?
grep "20260613_181010_978a77" ~/.hermes/logs/agent.log | grep "API call" | tail -5
echo "---"
# Sum up the token usage from API calls
grep "20260613_181010_978a77" ~/.hermes/logs/agent.log | grep "API call" | grep -oE "in=[0-9]+ out=[0-9]+ total=[0-9]+" | head -20

# 3. What was the most recent turn-end for this session?
grep "20260613_181010_978a77" ~/.hermes/logs/agent.log | grep "Turn ended" | tail -5

# 4. Is there a state.db row for this session? (Hermes stores session state)
sqlite3 ~/.hermes/state.db "SELECT datetime(created_at), role, substr(content, 1, 200) FROM messages WHERE session_id='20260613_181010_978a77' ORDER BY created_at DESC LIMIT 10;" 2>/dev/null || \
  ~/.local/bin/sqlite3 ~/.hermes/state.db "SELECT datetime(created_at), role, substr(content, 1, 200) FROM messages WHERE session_id='20260613_181010_978a77' ORDER BY created_at DESC LIMIT 10;" 2>/dev/null

# 5. Is there a process actually running this session right now?
pgrep -af "20260613_181010_978a77" 2>/dev/null
echo "---"
# Or check the gateway's process list
ps aux | grep -E "hermes.*20260613_181010" | grep -v grep | head -5

# 6. What owns this session? Look for "session_started" event
grep -E "session_started|20260613_181010_978a77" ~/.hermes/logs/agent.log | head -10

# 7. Clarify button state — are there unresolved clarifies?
grep -E "clarify" ~/.hermes/logs/agent.log | grep "20260613_181010_978a77" | tail -10

# 8. Token burn rate (per hour) for this session in last 24h
grep "20260613_181010_978a77" ~/.hermes/logs/agent.log | grep "API call" | awk -F'timestamp=' '{print $2}' | awk '{print $1}' | cut -d, -f1 | sort | uniq -c | head -30

# 9. Provider + model breakdown for this session
grep "20260613_181010_978a77" ~/.hermes/logs/agent.log | grep -oE "provider=[a-z]+ model=[A-Za-z0-9-]+" | sort | uniq -c

# 10. Find any "session ended" / "session abandoned" / "session closed" markers
grep -E "session (ended|closed|abandoned|expired|killed)" ~/.hermes/logs/agent.log | grep "20260613_181010_978a77" | tail -5
```

## Safety rails

- Read-only investigation. NO `hermes` commands that mutate state.
- NO `kill` commands. NO `hermes cron pause` commands.
- NO file modifications.
- If you find the session is dead and there's nothing to recommend, say so honestly.

## Required final report format

Return EXACTLY this JSON:

```json
{
  "status": "completed | blocked | failed",
  "session_id": "20260613_181010_978a77",
  "active": true | false,
  "owner": "telegram_user | cron | stuck_clarify | stuck_session | unknown",
  "last_provider_call": "ISO8601 timestamp or null",
  "call_frequency": "calls per hour (estimated from logs) or null",
  "estimated_token_burn": "tokens/hour or null",
  "evidence": ["file:line of each piece of evidence"],
  "safe_to_stop": true | false | "unclear",
  "recommended_action": "human-readable recommendation string"
}
```

## Acceptance criteria

- [ ] All 10 investigation commands run, output captured
- [ ] Owner identified with at least one piece of evidence
- [ ] Last call timestamp found
- [ ] If active: estimate token burn rate
- [ ] If safe to stop: list exact steps (don't execute)
- [ ] If unsafe to stop: explain why, who to ask
- [ ] Forge log written to `00_company_os/04_agents/logs/2026-06-22/forge-MC-SESSION-INVESTIGATE-1-<hash>.md`
- [ ] Task `MC-SESSION-INVESTIGATE-1` PATCHed to `done` (or `blocked` if you can't determine owner)
- [ ] No `hermes cron edit` / `kill` / file modifications made
- [ ] Push to origin/main (log only, no code changes expected)

## Scope budget

This is mostly investigation. 15 min budget. If you can't determine the owner after 15 min, PATCH to `blocked` with what you tried and what you need.
