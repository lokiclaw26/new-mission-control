---
task_id: MC-KANBAN-2-DUAL-FORMAT-PARSER
title: Extend Kanban parser to read YAML frontmatter + markdown-table task files; fix PATCH data-loss bug; add missing git tag
project: mission-control
phase: live-monitor
status: done
priority: high
created: 2026-06-16T19:35:00+00:00
created_by: thor
assigned_to: forge, argus
approval_required: true
approval_status: approved
approval_phrase: "NOFI chose Option 2: extend parser to read both formats. Do not normalize all 50 task files."
argus_passed: false
depends_on: [MC-KANBAN-1]
blocks: []
tags: [mission-control, kanban, parser, dual-format, data-loss-fix, bug-fix]
kanban_status: done
---

# MC-KANBAN-2 — Dual-Format Parser + Data Loss Fix

## NOFI's decision (verbatim, 2026-06-16 ~19:35Z)
*"Good work on MC-KANBAN-1. I choose Option 2: Extend the Kanban parser to read both task formats. Do not normalize all 50 task files right now. The board should support existing historical markdown-table task files as well as newer YAML frontmatter task files. Changing 50 files creates unnecessary churn and risk. Future tasks can use YAML frontmatter, but old tasks should still be readable."*

## Goal
Make the Kanban board reflect the actual workload by supporting both task-file formats, and fix a real data-loss bug in the PATCH endpoint.

## Scope (5 parts)

### Part 1 — Extend parser to read BOTH formats (Forge)

`kanban_parser.py` currently only reads YAML frontmatter. It must also read the older `| Field | Value |` markdown-table format used by all 50 DIY-* task files.

Two format examples:

**Format A — YAML frontmatter** (already supported, 2/52 files):
```markdown
---
task_id: MC-KANBAN-1
title: Hermes Kanban tab...
project: mission-control
status: in_progress
priority: high
created: 2026-06-16T18:55:00+00:00
created_by: thor
assigned_to: forge, argus
current_assignment: MC-KANBAN-1
approval_required: true
approval_status: pending
---
```

**Format B — markdown table** (currently missed, 50/52 files):
```markdown
# DIY-011 — Stage 11: Real fix for Wemos D1 Mini case + similar bugs

| Field | Value |
|---|---|
| **id** | DIY-011 |
| **title** | Stage 11: Fix false-positive candidates ... |
| **project** | diy-hub-v1 |
| **phase** | build |
| **status** | in_progress |
| **priority** | high |
| **owner** | Thor (after NOFI direct bug report) |
| **created_at** | 2026-06-14T23:15:00Z |
| **started_at** | 2026-06-14T23:15:00Z |
| **due** | 2026-06-14T23:45:00Z |
| **depends_on** | DIY-010 (shipped, but with bugs NOFI found) |
```

Format B uses these field names (NOT the same as Format A):
- `id` (not `task_id`) → map to `task_id`
- `title` (same) → map to `title`
- `project` (same) → map to `project`
- `status` (same) → map to `status`
- `priority` (same) → map to `priority`
- `created_at` (not `created`) → map to `created`
- `owner` (not `assigned_to`) → map to `assigned_to` (lowercased, strip parenthetical explanations)
- `started_at` (Format B only) → map to `started_at`
- `due` (Format B only) → map to `due`
- `depends_on` (Format B only, free text) → map to `depends_on_raw` (do not parse)
- NO `current_assignment`, `approval_status`, `created_by`, `approval_required` in Format B

**Detection rule:** try YAML frontmatter first (look for `---\n...key: value...\n---` at start of file). If found, parse as Format A. If not, look for `| Field | Value |` table. If found, parse as Format B. If neither, skip the file silently (log to parser warnings).

**Status mapping** (project status → kanban column) is the same for both formats:
- `triage` → triage
- `in_progress` → running
- `complete` / `done` → done
- `blocked` → blocked
- `pending` / `approved` / `ready` → ready
- `archived` → archived (hidden by default)

**Field normalization:** both formats produce the same task dict shape so downstream code (serve.py, mission-control.html) doesn't change. The parser returns:
```python
{
    "task_id": "DIY-011",
    "title": "...",
    "project": "diy-hub-v1",
    "status": "in_progress",        # raw project status (preserved)
    "kanban_status": "running",     # computed column
    "priority": "high",
    "created": "2026-06-14T23:15:00Z",
    "created_by": None,             # not in Format B
    "assigned_to": "thor",          # owner from Format B
    "current_assignment": "DIY-011",  # fallback if not in Format A
    "approval_required": False,
    "approval_status": None,
    "source_format": "A" or "B",
    "source_file": "01_projects/diy-hub-v1/tasks/DIY-011.md",
    "warnings": [],
    "extra": {"started_at": ..., "due": ..., "depends_on_raw": ...}
}
```

**Critical:** preserve the raw `status` field exactly. Don't overwrite it. The computed `kanban_status` is a SEPARATE field.

### Part 2 — Fix PATCH data-loss bug (Forge)

Current bug: PATCH overwrites the file's `status:` with the kanban column value (e.g. `running`), losing the project-native status (e.g. `in_progress`).

Fix: introduce a SEPARATE field `kanban_status` alongside the existing `status` field. The PATCH endpoint writes to `kanban_status` only; `status` is preserved.

YAML frontmatter example after PATCH:
```yaml
status: in_progress        # unchanged, project-native
kanban_status: running     # NEW, written by PATCH
```

Markdown-table example after PATCH — since Format B doesn't have a kanban_status field, the parser must INJECT a new row into the table WITHOUT touching the existing `| **status** | in_progress |` row:

```markdown
| **status** | in_progress |
| **kanban_status** | running |     # NEW row, added by PATCH
```

**Algorithm for the PATCH endpoint:**
1. Find the task file matching `task_id` (search `01_projects/*/tasks/*.md`)
2. Detect format (A or B) by re-parsing
3. For Format A: parse YAML, set `kanban_status: <new>`, write back. Never touch `status`.
4. For Format B: find the row `| **kanban_status** | ... |` — if present, update the value. If not present, INSERT a new row right after the `status` row. Never touch the `status` row.
5. Write back to disk. Preserve everything else (formatting, other fields, body).
6. Return 200 with the updated board state.

**Edge case:** if the task file has no `kanban_status` row in Format B AND the PATCH is for the same column the project status already maps to (e.g. `in_progress` → `running`), the parser should still set `kanban_status: running` (don't skip just because it matches).

**Edge case:** if the file is BOTH formats (e.g. has both frontmatter and a table — rare but possible), prefer frontmatter. Warn the user in the response.

**Forbidden:**
- DO NOT remove the `status` field
- DO NOT rename `status` to `kanban_status` (silent rename is data loss)
- DO NOT delete any rows
- DO NOT change the order of existing rows in Format B
- DO NOT add a new file — modify in place

### Part 3 — Update `data_kanban()` endpoint to use the new field (Forge)

The `GET /api/data/kanban` endpoint currently groups by the raw `status` field. After Part 1+2, it must group by `kanban_status` (which is computed on the fly by the parser from `status` if `kanban_status` is missing).

Logic:
- If task has `kanban_status`, use that for column assignment
- Else compute from `status` using the existing mapping

This way, old tasks without `kanban_status` still show in the right column.

### Part 4 — Add missing git tag (Forge)

If tag `mc-kanban-1` does not exist, add it as an annotated tag pointing at commit `462422b`:

```bash
cd /home/nofidofi/NofiTech-Ind
git tag -a mc-kanban-1 462422b -m "MC-KANBAN-1: Kanban tab in Mission Control — 3-agent board (Thor/Forge/Argus)"
git push origin mc-kanban-1
```

Verify it was pushed: `git ls-remote --tags origin | grep mc-kanban-1`

### Part 5 — Verification (Argus sub-agent)

Argus must run all checks below and write `00_company_os/04_agents/logs/2026-06-16/argus-mc-kanban-2.md`.

A. **Task-first proof:**
- `ls -la /home/nofidofi/NofiTech-Ind/01_projects/mission-control/tasks/MC-KANBAN-2-DUAL-FORMAT-PARSER.md` → must exist
- `grep "MC-KANBAN-2" /home/nofidofi/NofiTech-Ind/00_company_os/events.jsonl | wc -l` → must be ≥ 6 (task_created, task_assigned, work_started, forge_reported, argus_started, argus_passed/failed, task_completed)

B. **Parser coverage:**
- `curl -s http://192.168.0.29:8767/api/data/kanban | python3 -c "import json,sys; d=json.load(sys.stdin); print(sum(c['count'] for c in d['columns']))"` → must be > 2 (preferably > 30)
- `curl -s http://192.168.0.29:8767/api/data/kanban | python3 -c "..."` → count tasks with `source_format: A` and `source_format: B`
- Verify no historical file was mass-converted: `find /home/nofidofi/NofiTech-Ind/01_projects -name "*.md" -path "*/tasks/*" -newer /home/nofidofi/NofiTech-Ind/00_company_os/memory-log.md` → should be small (just the new task file + a few test fixtures, not all 50)

C. **PATCH data-loss fix:**
- Find a Format B task: `ls /home/nofidofi/NofiTech-Ind/01_projects/diy-hub-v1/tasks/DIY-011.md`
- Capture original status: `grep "^\| \*\*status\*\* |" /home/nofidofi/NofiTech-Ind/01_projects/diy-hub-v1/tasks/DIY-011.md | head -1`
- PATCH it: `curl -s -X PATCH http://192.168.0.29:8767/api/data/kanban/task/DIY-011 -H "Content-Type: application/json" -d '{"status":"done"}' -w "\n%{http_code}\n"` → must return 200
- Verify file: `grep -E "status|kanban_status" /home/nofidofi/NofiTech-Ind/01_projects/diy-hub-v1/tasks/DIY-011.md` → must show BOTH the original `status` (unchanged) AND a new `kanban_status: done` row
- PATCH back to original: `curl -s -X PATCH http://192.168.0.29:8767/api/data/kanban/task/DIY-011 -H "Content-Type: application/json" -d '{"status":"running"}'` (since the project status was `in_progress`, kanban column is `running`)

D. **Existing functionality (no regressions):**
- `curl -s http://192.168.0.29:8767/` → 200
- All 12 endpoints still 200: /api/health, /api/version, /api/data/overview, /api/data/agents, /api/data/projects, /api/data/tasks, /api/data/logs, /api/data/orders, /api/data/warnings-field, /api/data/github, /api/data/kanban
- Page still has Section 10: `curl -s http://192.168.0.29:8767/ | grep -c "section-kanban"` → ≥ 1
- Drag-drop still in HTML: `grep -c "draggable\|dragstart\|drop" mission-control.html` → ≥ 4
- Inline create button: `grep -c "add-btn" mission-control.html` → ≥ 1
- Search input: `grep -c "kanban-search\|search-input" mission-control.html` → ≥ 1
- Polling: `grep -c "setInterval.*kanban\|kanban.*setInterval" mission-control.html` → ≥ 1
- Lanes by profile: `grep -c "lanes-by-profile\|lane_by_profile" mission-control.html` → ≥ 1

E. **Git state:**
- `cd /home/nofidofi/NofiTech-Ind && git log --oneline -3` → Forge commit must be HEAD or 2nd
- `git ls-remote --tags origin | grep mc-kanban-1` → must return 1 line
- `git tag | grep mc-kanban-1` → must return 1 line

F. **Security:**
- No secrets in new code: `grep -rn "token\|password\|secret\|key" /home/nofidofi/NofiTech-Ind/01_projects/mission-control/code/kanban_parser.py` → must not include any actual token values
- No exposure of `/home/nofidofi/.hermes/scripts/.env.github`

## Out of scope
- Mass conversion of 50 task files to YAML (NOFI rejected this)
- Visual UI redesign
- New columns or features
- WebSocket live updates (still polling)
- Auto-decompose
- Multi-tenant

## Acceptance criteria
- [ ] `kanban_parser.py` reads both Format A (YAML frontmatter) and Format B (markdown table)
- [ ] Board shows > 2 tasks (target: 30+)
- [ ] `kanban_status` field preserved separately from `status` field
- [ ] PATCH writes to `kanban_status`, never overwrites `status`
- [ ] For Format B, PATCH adds a new row `| **kanban_status** | ... |` without touching existing rows
- [ ] No mass-conversion of historical task files
- [ ] `mc-kanban-1` git tag exists (annotated, pushed to remote)
- [ ] All 12 existing endpoints still return 200
- [ ] Drag-drop, inline create, search, polling, lanes all still work
- [ ] No secrets leaked
- [ ] Argus PASS in argus log file

## Files to touch
- `01_projects/mission-control/code/kanban_parser.py` — major refactor (Format A + B)
- `01_projects/mission-control/code/serve.py` — update PATCH endpoint to use kanban_status
- `01_projects/mission-control/code/mission-control.html` — minor: show kanban_status if present
- Backup: `01_projects/mission-control/code/backups/pre-mc-kanban-2-2026-06-16/`

## Handoff to Forge

1. Read the task file (this one) fully
2. Read `/home/nofidofi/NofiTech-Ind/00_company_os/04_agents/logs/2026-06-16/forge-mc-kanban-1.md` to understand the existing parser
3. Make backup first
4. Refactor `kanban_parser.py` to support both formats
5. Update PATCH endpoint to write `kanban_status` separately
6. Update `data_kanban()` to use `kanban_status` for column grouping
7. Test with curl: PATCH a Format B task, verify file content
8. Add the missing git tag
9. Commit + push
10. Write your own log at `00_company_os/04_agents/logs/2026-06-16/forge-mc-kanban-2.md`
11. Set mtime to NOW (don't backdate)

## Handoff to Argus

After Forge is done:
1. Read the task file (this one) and Forge's log
2. Run all A-F checks above
3. Write `argus-mc-kanban-2.md` with PASS/FAIL counts for each
4. Update state.json
5. Commit + push
6. Set mtime to NOW
