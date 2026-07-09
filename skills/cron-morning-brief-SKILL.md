---
name: cron-morning-brief
description: Use when an unattended cron job must read NofiTech-style state files (events.jsonl, state.json, 04_agents/state.json) and emit a short structured morning brief — and optionally append a deduplicated forge_reported event to events.jsonl. Covers the 5-section brief shape (YESTERDAY / OPEN ORDERS / WARNINGS / AGENT STATUS / TODAY'S FOCUS), the "now anchor = latest event ts" rule, the "missing field → say so, never fabricate" rule, the dedup check (skip append if last forge_reported < 60 min), the safe-JSONL-append pitfall (file may not end in newline — verify boundary before relying on `>>`), and the execute_code-is-blocked-for-cron rule (use `terminal` with python heredocs). Triggers on any task spec that names MC-021-VALUE-CRON-1, "morning brief", "daily report", or describes this 5-section deliverable.
version: 1.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [cron, unattended, morning-brief, jsonl, events, dedup, nofitech, mission-control, forge_reported, append-safe, file-integrity, 3-agent, nofi-tech-3agent]
    related_skills: [personal-mission-control, thor-delegation-protocol, operator-driven-staged-delivery]
---

# Cron Morning Brief

The recurring pattern: an unattended cron job reads three canonical
NofiTech OS files (`events.jsonl`, `state.json`, `04_agents/state.json`),
emits a 5-section brief, and appends a deduplicated `forge_reported`
event so the mission-control UI shows the brief was delivered.

This class has a few non-obvious pitfalls. They are all about
**integrity**: file-integrity (the JSONL may not end in a newline),
data-integrity (do not fabricate numbers when fields are missing),
and job-integrity (the cron context blocks `execute_code` and some
tirith patterns).

## When to use this skill

Trigger on any of:

- Task description references `MC-021-VALUE-CRON-1`, `MC-021`, "morning
  brief", "morning-brief", "daily brief", "daily report".
- A cron job spec says "produce a brief with sections: yesterday / open
  orders / warnings / agents / today" or similar.
- The deliverable is a printed text block AND a single append to
  `events.jsonl` with `event_type: forge_reported`.

## The 5-Section Brief Shape (locked)

The brief is always exactly these 5 sections in this order:

1. **YESTERDAY (24h)** — anchor on the file's most recent event `ts`
   (NOT on wall-clock). Window is `[now-24h, now]`. Count events in
   the window. Group by `event_type`. Report the top 5 with counts.
   State the total count and the time window you used.
2. **OPEN ORDERS** — `pending_orders` count and `app_health` from
   `state.json`. **If the keys are absent, say so explicitly. Never
   fabricate a number.** The "missing field" is the truthful answer.
3. **WARNINGS** — `warnings` list length from `state.json`. Same
   "missing field → say so" rule.
4. **AGENT STATUS** — for each agent in `04_agents/state.json`
   `agents`, report `name | status | last_activity | current_assignment`.
5. **TODAY'S FOCUS** — most recent in-flight `task_id` from
   `events.jsonl`: `task_assigned` or `work_started` events without
   a following `task_completed` / `complete` / `task_done`. If none,
   say "No active in-flight tasks identified."

Rules baked into the shape:

- **Bullets > prose.** No "Here is your brief:". No filler.
- **≤ 400 words.** The cron delivers to a channel — long is hostile.
- **Cite real numbers.** `wc -l events.jsonl`, `jq`, or python
  Counter. Never round, never "approximately."

## The Three Hard Rules

### Rule 1 — Anchor on wall-clock, FLAG stale feed (locked 2026-06-28, MC-BRIEF-FIX-PROMPT)

`now = date -u +'%Y-%m-%dT%H:%M:%SZ'` (wall-clock UTC). NOT
`max(ts field across events.jsonl)`.

**Why we reversed the original "anchor on file" rule:** the file's
most-recent event ts is the timestamp of the LAST WRITE, which can
lag wall-clock by minutes-to-hours on a healthy system (no one's
writing events at 3am) or days when the org is quiet. The 06-27
brief anchored on a stale event ts and reported a 17-event window
that was actually 28 hours wide. The 06-28 brief anchored on the
same stale ts and reported "no events in last 24h" when in fact
17 events happened — the cron was just anchored to yesterday.

**Use wall-clock for the window.** If the most-recent event ts is
> 1 hour older than `now`, append ` — STALE feed` to section 1's
window label. The brief stays useful when the feed is live AND
honest when it's not.

### Rule 2 — Missing fields are answers first time, FAIL-LOUD on repeat (locked 2026-06-28)

First occurrence: when a section asks for a field that is not in
the file, write the absence sentence:

```
## 2. OPEN ORDERS
- pending_orders: no open orders field present in state.json
- app_health: field absent in state.json
```

This is correct and honest. The brief's job is to surface the
real state of the org, not to look complete.

**REPEAT occurrence (3+ consecutive runs with the same missing field):
fail loud.** The field is missing because something is BROKEN, not
because the org is in an unusual state. Emit:

```
## 2. OPEN ORDERS
- pending_orders: [BRIEF FAILED: state.json missing "pending_orders" key — should be populated by kanban-auto-process.sh / state-writer job. Field absent 3+ consecutive runs. Check ~/.hermes/scripts/kanban-auto-process.sh state-write path.]
```

The "fail loud" pattern applies to all read-time failures: missing
files, empty files, malformed JSON, missing required keys. Do NOT
silently produce an empty brief when the input is broken. Do NOT
say `[SILENT]` unless every required file was present AND every
section has real content.

### Rule 3 — execute_code is BLOCKED for cron

`execute_code` will return:

```
BLOCKED: execute_code runs arbitrary local Python (including
subprocess calls that bypass shell-string approval checks).
Cron jobs run without a user present to approve it.
```

Use `terminal` with a `python3 <<'PYEOF' ... PYEOF` heredoc instead.
The heredoc survives shell preprocessing; just don't try to
write secrets literally (use `shell_quote` or `~/.hermes/scripts/.env.mc`).

## The Dedup Check (do this BEFORE appending)

Before appending anything to `events.jsonl`:

```bash
grep '"event_type":"forge_reported".*"task_id":"MC-021-VALUE-CRON-1"' \
  /home/nofidofi/NofiTech-Ind/00_company_os/events.jsonl | tail -1
```

Parse the `ts` field of the last matching event. Compute
`minutes_since_last = (now_utc - last_ts_utc) / 60`.

**WARNING (locked 2026-07-07, see Pitfall 20):** `grep | tail -1`
returns the last PHYSICAL line, but that line may contain two
concatenated JSON objects (the `}{` no-newline corruption). A naive
`json.loads()` on that line fails with "Extra data" and the
cron can't read the actual latest ts. The robust pattern is:

```python
import sys
sys.path.insert(0, "/home/nofidofi/.hermes/skills/software-development/cron-morning-brief/scripts")
from append_event import parse_jsonl_lenient
events = parse_jsonl_lenient("/home/nofidofi/NofiTech-Ind/00_company_os/events.jsonl")
forge = [e for e in events if e.get("event_type") == "forge_reported" and e.get("task_id") == "MC-021-VALUE-CRON-1"]
forge.sort(key=lambda e: e.get("ts",""))
last_ts = forge[-1]["ts"] if forge else None
```

Use `last_ts` to compute `minutes_since_last`. The grep-then-tail-1
recipe above still works in practice (it returns the line with the
LAST forge_reported and the dedup decision is usually right because
two consecutive cron briefs are 24h apart) but it is NOT
parser-correct — switch to `parse_jsonl_lenient` if you ever see
"Extra data" or off-by-day dedup behavior.

- If `minutes_since_last < 60` → **DO NOT append.** Still print
  the brief in your final response, but append the literal text
  `(dedup: skipped events.jsonl append — last forge_reported was
  N min ago)` after the brief body.
- If `minutes_since_last >= 60` → append (see next section).

The dedup prevents the brief from spamming the events log when the
cron is run twice in an hour (manual trigger after a failure,
clock drift, etc.).

## The Safe Append (the trap everyone hits)

The append spec is:

```json
{"ts":"<current UTC ISO8601 with seconds>","actor":"forge","event_type":"forge_reported","project":"mission-control","task_id":"MC-021-VALUE-CRON-1","title":"morning-brief delivered","message":"<word_count> words","status":"delivered","source_file":"01_projects/mission-control/tasks/MC-021-VALUE-CRON-1.md","schema":"nofitech-event/v1"}
```

**The trap:** `events.jsonl` is built by dozens of actors. It is
**not guaranteed to end in a newline.** If you do `echo "$EVENT"
>> events.jsonl` and the file's last byte is `}` (no `\n`), your
event is concatenated onto the prior record:

```
..."schema":"nofitech-event/v1"}{"ts":"2026-06-25T04:01:24+00:00",...
```

Every JSONL parser will then fail to parse the prior record.
**Every downstream panel that reads events will silently show
nothing.**

The safe pattern (in Python, via `terminal` heredoc):

```python
import os
path = "/home/nofidofi/NofiTech-Ind/00_company_os/events.jsonl"
event_marker = b'{"ts":"2026-06-25T04:01:24+00:00"'  # or compute
with open(path, 'rb') as f:
    data = f.read()

# Find the byte just before our new event
idx = data.rfind(event_marker)
if idx > 0 and data[idx-1:idx] != b'\n':
    # No newline before our event — insert one to repair the boundary
    data = data[:idx] + b'\n' + data[idx:]

# Ensure no trailing newline (spec: "no trailing newline")
if data.endswith(b'\n'):
    data = data[:-1]

with open(path, 'wb') as f:
    f.write(data)
```

Verify after with:

```bash
tail -2 /path/events.jsonl
# Expect: two clean lines, each a valid JSON object.
# Check: python3 -c "import json; [json.loads(l) for l in open(p) if l.strip()]"
```

### Why this trap exists

The events file is grown by `mc_event.py` (Python, always writes
trailing `\n`) AND by shell `echo >>` (does NOT write a trailing
newline). The two patterns coexist; any single append via shell
inherits whatever boundary the prior writer left. The repair step
above is the durable fix.

### Bash-only safe alternative (when Python unavailable)

If you must do this in pure bash:

```bash
# Read last byte. If not \n, prepend \n to the new event.
LAST=$(tail -c 1 /path/events.jsonl | od -An -c | tr -d ' ')
NEW='{"ts":"...","actor":"forge",...}'
if [ "$LAST" = "\n" ] || [ -z "$LAST" ]; then
  printf '%s' "$NEW" >> /path/events.jsonl
else
  printf '\n%s' "$NEW" >> /path/events.jsonl
fi
```

But the Python version is easier to verify.

## The Word Count (`message` field)

The `message` field is `"<word_count> words"`. Count words of the
brief **body only** — not the section headers (`## 1. YESTERDAY`),
not the closing dedup line, not the meta instructions.

```bash
BRIEF='## 1. YESTERDAY...
## 2. OPEN ORDERS...
...'
echo "$BRIEF" | wc -w
```

Then put that number in the `message` field before appending.

## The Complete Cron Recipe

```bash
# 1. Read the files (use search_files / read_file, not cat)
#    - /home/nofidofi/NofiTech-Ind/00_company_os/events.jsonl
#    - /home/nofidofi/NofiTech-Ind/00_company_os/state.json
#    - /home/nofidofi/NofiTech-Ind/00_company_os/04_agents/state.json

# 2. Compute the brief (terminal with python heredoc, NOT execute_code):
python3 <<'PYEOF'
import json
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict

events_path = "/home/nofidofi/NofiTech-Ind/00_company_os/events.jsonl"
# events.jsonl may contain pre-existing concatenated records on a single line
# (old shell `echo >>` writers left `}{` adjacent). A naive json.loads(line)
# loop fails with "Extra data" on those lines. Use a balanced-brace walker
# that splits each physical line into N valid JSON objects.
import sys
sys.path.insert(0, "/home/nofidofi/.hermes/skills/software-development/cron-morning-brief/scripts")
from append_event import parse_jsonl_lenient  # see scripts/append_event.py
events = parse_jsonl_lenient(events_path)

def parse_ts(ts):
    return datetime.fromisoformat(ts.replace("Z","+00:00")).astimezone(timezone.utc)

now = max(parse_ts(e["ts"]) for e in events if "ts" in e)
window_start = now - timedelta(hours=24)
recent = [e for e in events if "ts" in e and window_start <= parse_ts(e["ts"]) <= now]

# Top 5 event_types
type_counter = Counter(e.get("event_type","(missing)") for e in recent)
print(f"now={now.isoformat()} total_recent={len(recent)}")
for t,c in type_counter.most_common(5):
    print(f"  {t}: {c}")

# In-flight tasks
lifecycle = ("task_assigned","work_started","task_completed","complete","task_done")
status = defaultdict(list)
for e in recent:
    if e.get("event_type") in lifecycle:
        tid = e.get("task_id") or e.get("task")
        if tid:
            status[tid].append((parse_ts(e["ts"]), e["event_type"]))

in_flight = []
for tid, lst in status.items():
    lst.sort()
    last = lst[-1][1]
    if last not in ("task_completed","complete","task_done"):
        in_flight.append((tid, last))
print("in_flight:", in_flight or "none")
PYEOF

# 3. Build the brief string in bash
BRIEF='## 1. YESTERDAY (24h)
...

## 2. OPEN ORDERS
...

## 3. WARNINGS
...

## 4. AGENT STATUS
...

## 5. TODAY'S FOCUS
...'
WORD_COUNT=$(echo "$BRIEF" | wc -w)

# 4. Dedup check
LAST_FORGE=$(grep '"event_type":"forge_reported".*"task_id":"MC-021-VALUE-CRON-1"' \
  /home/nofidofi/NofiTech-Ind/00_company_os/events.jsonl | tail -1 | grep -o '"ts":"[^"]*"')
# Compute minutes_since_last; if < 60, skip append.

# 5. Safe append (Python heredoc with boundary repair)
NOW_TS=$(date -u +"%Y-%m-%dT%H:%M:%S+00:00")
EVENT="{\"ts\":\"${NOW_TS}\",...,\"message\":\"${WORD_COUNT} words\",...}"
python3 <<PYEOF
path = "/home/nofidofi/NofiTech-Ind/00_company_os/events.jsonl"
marker = b'"ts":"${NOW_TS}"'
with open(path,'rb') as f: data = f.read()
idx = data.rfind(marker)
if idx > 0 and data[idx-1:idx] != b'\n':
    data = data[:idx] + b'\n' + data[idx:]
if data.endswith(b'\n'):
    data = data[:-1]
with open(path,'wb') as f: f.write(data)
PYEOF
echo "$EVENT" >> /home/nofidofi/NofiTech-Ind/00_company_os/events.jsonl
# Re-verify: tail -2 should show two clean lines.

# 6. Print the brief in the final response.
echo "$BRIEF"
```

## Pitfalls (locked from real sessions)

1. **execute_code returns BLOCKED for cron jobs.** Use
   `terminal` with `python3 <<'PYEOF' ... PYEOF`. The heredoc
   form is approved because the script is textually visible to
   the approval scanner.

2. **`echo >> events.jsonl` corrupts the prior record if the
   file doesn't end in `\n`.** Always check the byte boundary
   and insert `\n` if missing. See the safe-append recipe above.

3. **The `tail -1` after a raw `echo >>` lies.** It reads the
   prior line plus the new event as one record because the
   newline is missing. Use `tail -2` after repair, or verify
   with `python3 -c "import json; [json.loads(l) for l in
   open(p) if l.strip()]"`.

4. **`tail | python3 -m json.tool` may be blocked by tirith**
   ("schemeless URL → interpreter" false-positive pattern).
   Use `read_file` or the heredoc pattern instead. The brief
   reader's job is to **verify the appended line parses**, not
   to pretty-print.

5. **Anchoring on `datetime.now()` instead of file's most
   recent `ts`** produces a "no events in last 24h" brief that
   is technically correct but useless. The file is the truth.

6. **Fabricating `pending_orders: 0` when the field is absent**
   is the worst output. The brief becomes a lie that looks
   professional. Always write the absence sentence.

7. **`wc -w` on the bash string vs on the rendered markdown
   differs by the markdown punctuation.** The brief body (no
   section headers, no final dedup line) is what gets counted.
   Compute `WORD_COUNT` from the string you actually print.

8. **The cron spec is in `/home/nofidofi/NofiTech-Ind/00_company_os/charter.md`**
   and references `MC-021-VALUE-CRON-1`. The task file is at
   `01_projects/mission-control/tasks/MC-021-VALUE-CRON-1.md`.
   If either is missing, the brief is still valid — note the
   absence in section 5 ("task spec not located on disk").

9. **`events.jsonl` may contain PRE-EXISTING concatenated records
   on one line.** Old shell `echo >>` writers left `}{` adjacent
   in the middle of the file. Naive `[json.loads(l) for l in
   open(path)]` will fail with
   `json.decoder.JSONDecodeError: Extra data: line N column M`.
   The reader must split each physical line on `}{` boundaries
   (or walk balanced braces) and parse every substring
   individually. The recipe in the Complete Cron Recipe uses a
   balanced-brace walker that survives any pre-existing
   corruption. Don't try to "repair" the historical damage
   during the cron — that's a separate hygiene migration, not a
   brief step. Just parse around it and proceed.

10. **Agent state JSON (`04_agents/state.json`) often carries a
    `projects.<name>.approval_needed=true` flag when the root
    `state.json` has no `pending_orders`.** When section 2's
    primary answer is "no pending_orders field present," scan
    the agent state for an approval-pending project and surface
    it as a second-best answer:
    `pending_orders: <field absent>; <project> approval_needed=true (awaiting NOFI approval to advance)`.
    Same honesty rule applies — don't call it an "open order"
    if it's actually a stage gate, just name what it is.

11. **The cron may run when the file is up to ~24h stale.** If
    the most recent event ts is from yesterday, the 24h window
    will contain only 1-2 events (the prior brief deliveries
    themselves). The wall-clock anchor (Rule 1) handles this
    naturally — the brief computes the 24h window from
    wall-clock, then reports what was actually in that window,
    then surfaces the staleness in section 1 if the most recent
    event is > 1h older than now. The brief is honest, the user
    knows why activity is low.

12. **Today's focus event types are NOT `task_assigned` /
    `work_started` / `task_completed` / `complete` / `task_done`.**
    (locked 2026-06-28, MC-BRIEF-FIX-PROMPT) The kanban
    actually emits these event types — use exactly these:
    - **In-flight triggers** (start of an active task): `auto_process_started`, `auto_process_moved_to_ready`, `auto_process_dispatched`, `task_dispatched`, `work_started`
    - **Completion clears** (task finished): `auto_process_completed`, `result_recorded`, `auto_process_moved_to_done`

    The legacy `task_assigned` / `task_completed` / `complete` /
    `task_done` types are NOT emitted by the current kanban
    scripts. If the prompt asks for them, the brief reports
    "No active in-flight tasks identified" even when 3 cards are
    sitting in `running_now`. Locked from real session data:
    2026-06-27 brief missed 3 in-flight tasks because it was
    looking for `task_assigned` events that didn't exist.

13. **The model may print tool-call JSON as text instead of
    actually invoking the tool.** (locked 2026-06-28) The 06-28
    brief was empty because the model output
    `{"name": "read_file", "input": {"path": "..."}}` as plain
    text instead of calling `read_file`. The cron prompt MUST
    include a STEP 0 that explicitly forbids printing tool-call
    JSON and mandates actual tool invocation. Recommended STEP 0
    wording (copy verbatim into the cron prompt):

    ```
    STEP 0 — TOOL EXECUTION (MANDATORY, DO THIS BEFORE ANY OUTPUT):
    - You MUST actually CALL each tool listed below via the tool-calling mechanism.
    - Do NOT print, write, or paste tool-call JSON as plain text in your final response.
    - Do NOT describe what the tool calls would look like. Invoke them.
    - Each `read_file` call returns a `ToolResult` block that you parse into your working memory before producing any section of the brief.
    - If after invoking a tool you discover the file is missing or empty, emit "[BRIEF FAILED: <absolute path> missing or empty]" in place of any section that needs that data. Do NOT silently produce an empty brief. Do NOT say "[SILENT]" unless every required file was present AND every section has real content.
    ```

    Without this, any model that defaults to "describe my plan"
    instead of "execute" produces an empty brief.

14. **`Agent last_activity` is often frozen for weeks.** (locked
    2026-06-28, MC-BRIEF-FIX-AGENT-ACTIVITY) The brief's section
    4 will show `last_activity` frozen at the date the kanban
    scripts were last updated. A STALE check (`days_since > 7`)
    was added but the deeper fix is to PATCH the 4 kanban cron
    scripts (`kanban-auto-process.sh`, `kanban-auto-execute.sh`,
    `kanban-auto-done.sh`, `kanban-auto-dispatch.sh`) to update
    `<agent>.last_activity` on every tick. See
    `references/kanban-agent-activity-patch.md` for the canonical
    jq pattern. Without the patch, section 4 of the brief will
    always say "[STALE] forge / thor / argus" until the org runs
    for 7+ days.

15. **Cron `now` must include seconds, not minutes.** (locked
    2026-06-28) Format: `date -u +'%Y-%m-%dT%H:%M:%SZ'` (with
    `Z` suffix). Earlier versions used `date -u +'%Y-%m-%dT%H:%MZ'`
    (no seconds, Z zone). The seconds field is required for
    dedup check accuracy (two runs in the same minute will
    otherwise both pass the dedup's `< 60 min` test by being
    timestamped identically) AND for the events.jsonl event
    ordering (concurrent events should sort correctly). Always
    seconds, always UTC, always Z.

16. **Warning `ts` must come from the embedded parenthetical, NOT
    from `state.updated`.** (locked 2026-06-29,
    MC-WARNINGS-AUTOCLEAR-1) Warnings carry their own timestamp
    inside the text, e.g.
    `"... returned 403 missing MC_ADMIN_TOKEN (2026-06-28T12:54:32Z, errors.log)"`.
    The object's `ts` field (after migration) defaults to the
    timestamp of the LAST state.json write — that can be weeks
    newer than the warning itself. If the auto-clear script
    uses the object's `ts`, a warning that is genuinely 48h old
    gets judged as 0h old and never resolves. The fix is to
    regex `r"\(([^)]+)\)\s*$"` out of the text, take the first
    comma-separated token, parse as ISO, and use that as
    `w_ts`. The object's `ts` field is only a fallback when the
    text doesn't have an embedded parenthetical (rare). See
    `scripts/resolve-warnings.py::warn_embedded_ts`.

17. **The cron prompt's "now anchor" rule conflicts with Rule 1.**
    (locked 2026-07-02, observed in production) The current
    MC-021-VALUE-CRON-1 prompt says: "Use the file's most recent
    event timestamp as the 'now' anchor." But the skill's Rule 1
    (locked 2026-06-28) says the opposite: use wall-clock and
    flag stale feeds with ` — STALE feed`. The 07-02 brief ran
    end-to-end using the prompt's anchor-on-file rule and got a
    2-event 24h window (the only events were the prior briefs
    themselves) — exactly the failure mode Rule 1 was written
    to prevent. When the cron prompt and the skill disagree,
    the prompt wins (it's what gets executed), so the right fix
    is to UPDATE the cron prompt to match Rule 1. If you cannot
    edit the prompt in this session, at minimum APPEND a
    note to the brief acknowledging the discrepancy: e.g.
    `Window anchored on file's most recent ts (2026-07-01T04:00:56Z)
    per cron spec — wall-clock is 2026-07-02T04:00Z, feed is
    ~24h stale. Consider patching the cron prompt to use
    wall-clock per skill Rule 1.`

20. **The events.jsonl parser-mismatch trap is ACTIVE in 2026-07-07, not
    historical.** (locked 2026-07-07) Pitfall 9 says the `}{` concat
    damage is "permanent historical damage." That's misleading: every
    shell-append after a shell-append extends the corruption by 1
    event. As of 2026-07-07 the file has `wc -l=803` but
    `parse_jsonl_lenient()` returns 805 — a 2-event gap. The last
    physical line contains two consecutive forge_reported events
    with no newline between them. Concrete failure modes this
    introduces:
    - `wc -l` understates event count by N.
    - `read_file` reports `total_lines=N-1` (off by N from truth).
    - `[json.loads(l) for l in f]` silently drops the
      right-most concatenated events.
    - `grep ... | tail -1` returns the right text but
      `json.loads(grep ... | tail -1)` raises `Extra data`,
      masking the fact that you have TWO records there.
    - Dedup check is wrong: the second object on the bad line
      has the LATEST ts, but `tail -1` returns it
      concatenated with the first object. Parsing with
      `json.loads(line)` fails. The brief's "last forge_reported"
      therefore reads the FIRST object on the bad line, not the
      actual latest one — and minutes_since_last can be off by
      hundreds of minutes.
    **The rule:** for any cron reading events.jsonl, ALWAYS call
    `parse_jsonl_lenient()` and `verify_last_two()` from
    `scripts/append_event.py`. Do NOT trust `wc -l`, `read_file`
    line counts, `grep | tail -1 | json.loads`, or a naive
    list comprehension over the file. See
    `references/reading-corrupted-jsonl.md` for the canonical
    `wc -l` vs `parse_jsonl_lenient` sanity check and the
    one-time hygiene migration script.

19. **The cron prompt's "in-flight = task_assigned/work_started
    without task_completed" rule produces permanent false
    positives on stale tasks.** (locked 2026-07-04,
    observed on the 07-04 brief) The cron prompt asks for
    `task_assigned` / `work_started` events without a following
    `task_completed` / `complete`. But the kanban (per
    Pitfall 12) emits `task_dispatched` as the trigger and
    `result_recorded` as the completion — `task_assigned` and
    `task_completed` haven't been emitted since 2026-06-19.
    A task dispatched 2026-06-28 will therefore look
    "in-flight" forever (no `task_completed` ever arrives) and
    every morning brief for the next 6+ days will cite it as
    "today's focus" even though it was actually closed by a
    `result_recorded` event hours later. The 07-04 brief made
    exactly this error: it cited MC-KANBAN-CREATE-20260628085628-*
    as in-flight when the prior day already had a
    `result_recorded` event closing it.

    **The fix is to expand the in-flight lifecycle to the
    kanban's actual event types.** When building section 5,
    treat as **in-flight triggers**: `task_dispatched`,
    `work_started`, `auto_process_started`,
    `auto_process_moved_to_ready`, `auto_process_dispatched`.
    Treat as **completion clears**: `task_completed`,
    `complete`, `task_done`, `result_recorded`,
    `auto_process_completed`, `auto_process_moved_to_done`.
    A task is in-flight iff its most-recent lifecycle event is
    in the trigger set, not the completion set. Legacy
    `task_assigned` is allowed as a trigger for backwards
    compatibility with pre-2026-06-19 events but is otherwise
    dormant.

    **Additional freshness filter:** if the most-recent
    trigger event for a task is older than 7 days AND the
    task has had no lifecycle event since, surface it under
    a separate "stale tasks" line in section 5 instead of
    "today's focus" (or in a "stuck tasks" sub-bullet).
    Section 5 should reflect what's actually actionable
    *today*, not what was dispatched a week ago and never
    closed.

18. **`cronjob action=update` with only a `prompt` field OVERWRITES
    the existing prompt silently.** (locked 2026-06-29) The
    `update` API treats a passed `prompt` as the new full
    prompt — there is no merge or diff. If you call
    `cronjob_update(job_id=..., prompt="Read full prompt
    preview to see the cron spec.")` as a probe, you WILL
    replace the 3357-char production prompt with that single
    sentence. The cron will still run on schedule but will
    produce broken briefs (because the new prompt is the
    1-line probe). Recovery: look in `~/.hermes/cron/` for a
    backup file matching the job id — the platform creates
    `.bak-pre-brief-fix-<timestamp>` (and similar `.bak-*`)
    snapshots before prompt edits. The exact `.bak-*` prefix
    varies per edit; list the directory with `ls -lat
    ~/.hermes/cron/` and grep each `.bak-*` file for the
    original prompt length to identify the right backup.
    Prevention: pass the FULL updated prompt in a single
    `update` call (not a probe) OR use `cronjob_update`
    with `prompt=None` to leave the field untouched while
    changing other fields like `schedule`.

## Related Skills

- `personal-mission-control` — for the dashboard that reads
  `events.jsonl` and renders the brief's effect on the UI.
- `thor-delegation-protocol` — the agent that owns dispatching
  Forge to verify the brief.
- `operator-driven-staged-delivery` — the multi-stage pattern
  this brief measures progress against.

## WARNINGS Section v1.18 — Auto-Clear Resolved + Audit Trail (locked 2026-06-29, MC-WARNINGS-AUTOCLEAR-1)

Section 3 (WARNINGS) was upgraded in 2026-06-29 to separate active
warnings from a historical audit trail. The motivation: warnings used
to be append-only — once written they stayed in `state.json.warnings`
forever, so the WARNINGS section accumulated noise about bugs that
had already been fixed.

**Schema (v1.18):**

```json
{
  "warnings": [
    {"text": "...", "ts": "ISO", "resolved": false, "resolved_at": null}
  ],
  "resolved_warnings": [
    {"text": "...", "ts": "ISO", "resolved": true, "resolved_at": "ISO"}
  ]
}
```

**The migration + auto-clear script** lives at
`scripts/resolve-warnings.py` in this umbrella. The brief's STEP -1
calls it before reading state.json:

```bash
python3 /home/nofidofi/.hermes/scripts/resolve-warnings.py
# or, when the script lives inside the skill bundle:
python3 /home/nofidofi/.hermes/skills/software-development/cron-morning-brief/scripts/resolve-warnings.py
```

**What the script does (in order):**

1. Loads `state.json`.
2. Migrates any legacy string-form warnings (e.g. `"... (2026-06-27T08:01:05Z, errors.log)"`)
   into the object form `{text, ts, resolved: false, resolved_at: null}`.
3. For each warning, computes `age_hours = now_utc - w_ts` where
   `w_ts` is parsed from the embedded `(TS, errors.log)`
   parenthetical in the warning text (NOT from the object's `ts`
   field — see Pitfall 16).
4. Computes `still_failing(sig, recent_events)` by searching the
   last 24h of `events.jsonl` for any event whose text contains
   the warning's signature.
5. If `age_hours >= 24 AND NOT still_failing` → move the warning
   to `resolved_warnings`, stamp `resolved_at = now_utc`,
   append `[RESOLVED <ts>]` to its text.
6. Writes state.json atomically via `.tmp` + `replace()`.

**Brief rule (after auto-clear):**

- Section 3 reports `len(state.warnings)` and the text of each
  active entry.
- Optionally also reports `len(state.resolved_warnings)` as
  `resolved_warnings: N` on a separate line under the active list.
- The audit trail is preserved in `resolved_warnings` — never delete.

**Tunables** (via CLI flags on the script):

- `--window 24` — resolution window in hours (default 24)
- `--dry-run` — print what would happen without writing
- `--path <state.json>` — point at a different state file
- `--events <events.jsonl>` — point at a different event log

The script is idempotent — safe to call from every cron tick.

## See Also

- [`references/warnings-auto-clear.md`](references/warnings-auto-clear.md) —
  full design rationale, the migration + auto-clear pseudocode,
  and the failure modes (parsing errors, events.jsonl missing,
  state.json write failure). Locked 2026-06-29 from
  MC-WARNINGS-AUTOCLEAR-1.
- [`scripts/resolve-warnings.py`](scripts/resolve-warnings.py) —
  the migration + auto-clear script. Importable as a module or
  runnable as a CLI (`python3 resolve-warnings.py [--dry-run]
  [--window 24]`).
- [`references/safe-jsonl-append.md`](references/safe-jsonl-append.md) —
  the full boundary-repair recipe, with edge cases (empty file,
  single line, file with mixed `\n` / no-`\n` boundaries).
- [`references/reading-corrupted-jsonl.md`](references/reading-corrupted-jsonl.md) —
  the reader-side trap: pre-existing `}{` concatenation in
  `events.jsonl` from old shell appends. `parse_jsonl_lenient()`
  walks balanced braces per line.
- [`references/event-schema-nofitech-v1.md`](references/event-schema-nofitech-v1.md) —
  the exact field contract for `forge_reported` events and how
  they relate to the `nofitech-event/v1` schema in
  `00_company_os/event-schema.md`.
- [`references/cron-execute-code-blocked.md`](references/cron-execute-code-blocked.md) —
  the full error message, the workarounds, and the
  `terminal` heredoc pattern that survives the approval scanner.
- [`references/kanban-event-types-and-agent-activity.md`](references/kanban-event-types-and-agent-activity.md) —
  the REAL event types the kanban emits (vs the legacy types
  legacy prompts ask for) plus the canonical jq patch for
  keeping `04_agents/state.json` agent `last_activity` live.
  Updated 2026-06-28 after the morning-brief broke for 2
  consecutive days because the prompt referenced event types
  the system doesn't emit, and agent timestamps were frozen
  for 10 days because no script updated them.
- [`scripts/append_event.py`](scripts/append_event.py) —
  importable helpers `parse_jsonl_lenient(path)` and
  `safe_append(path, event)`. Also runnable as a CLI:
  `python3 append_event.py verify <path>` and
  `python3 append_event.py test <path>`.
