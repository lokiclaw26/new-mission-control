---
task_id: MC-PARSER-AGENT-FIELD-1
assigned_to: forge
title: Parser: recognize `agent:` field as a valid assignee (Format A)
type: bugfix
priority: high
status: done
kanban_status: done
assignee: forge
created: 2026-06-17T16:05:00+04:00
created_by: thor
completed: 2026-06-17T16:08:00+04:00
argus_passed: true
approval_required: true
depends_on: [MC-KANBAN-2-DUAL-FORMAT-PARSER]
---

## Problem (reported by NOFI 2026-06-17 ~15:50 Dubai)

> "task is in running now .. but it shows unassigned !! why ??"

## Root cause

The kanban parser reads `assigned_to:` or `assignee:` from Format A task frontmatter, but some older task files use `agent:` (e.g. MC-007-token-budget.md has `agent: thor`). The parser misses `agent:` and the card displays as "unassigned" even though the file specifies an agent.

## Example

`01_projects/mission-control/tasks/MC-007-token-budget.md` frontmatter:
```yaml
id: MC-007
title: Token Budget Mode
project: mission-control
agent: thor          <-- this is the agent
status: open
priority: P1
...
```

Card on the kanban shows: `agent: thor` in the file → `assignee: unassigned` in the UI. Bug.

## Required actions

### Forge: edit `/home/nofidofi/NofiTech-Ind/01_projects/mission-control/code/kanban_parser.py`

1. Find the function that reads the assignee from Format A frontmatter
2. Add `agent:` as another valid field name. Precedence (highest first):
   - `assigned_to:` (explicit, list form)
   - `assignee:` (explicit, single)
   - `agent:` (legacy, single — used by older Stage 0-7 task files)
3. Apply the same precedence to both Format A and Format B (if Format B has any equivalent field)
4. Don't break existing behavior — `assigned_to` and `assignee` should still work
5. If the field is a list (e.g. `[thor, forge]`), use the first element as the primary assignee
6. If the field is empty string or null, treat as unassigned

### Forge: also backfill the existing files
For each Format A task file that has `agent:` but no `assigned_to:` or `assignee:`, add `assigned_to: <agent>` to the frontmatter. This way the file is unambiguous going forward. Use the parser script or sed:
```bash
cd /home/nofidofi/NofiTech-Ind
for f in $(grep -l "^agent:" 01_projects/*/tasks/*.md 2>/dev/null); do
  if ! grep -qE "^(assigned_to|assignee):" "$f"; then
    agent=$(grep -E "^agent:" "$f" | head -1 | awk -F': ' '{print $2}' | tr -d '"' | tr -d "'")
    # Insert assigned_to: <agent> after the agent: line
    sed -i "/^agent: /a assigned_to: $agent" "$f"
  fi
done
```

Test files: MC-007-token-budget.md is the only known one, but check all task files in 01_projects/*/tasks/.

### NOT in scope
- DO NOT change the parser output structure (just add a new input field)
- DO NOT change `kanban-set-state.sh` or any helper scripts
- DO NOT touch serve.py
- DO NOT touch kanban.html
- DO NOT add new features
- DO NOT touch the auto-process cron

### Argus
1. Verify parser reads `agent:` correctly:
   - Run the parser on MC-007-token-budget.md, confirm `assignee: thor` in output
   - Run on a Format A task with `assigned_to: forge` — confirm `assignee: forge` (no regression)
   - Run on a Format A task with `assignee: argus` — confirm `assignee: argus` (no regression)
   - Run on a Format A task with all three (agent, assignee, assigned_to) — confirm `assigned_to` wins
   - Run on a Format A task with no assignee fields — confirm `assignee: unassigned`
2. Verify backfill:
   - All Format A files that had `agent:` now also have `assigned_to:`
   - No new files lost their `agent:` field
3. Behavioral test: load `/kanban` in Playwright, find MC-007-token-budget card, verify it shows "thor" not "unassigned"
4. Mission Control still loads (HTTP 200 on / and /kanban)
5. No regression: scan a few Done column cards, confirm assignees still show correctly

## Acceptance criteria

### Parser
- [ ] `kanban_parser.py` recognizes `agent:` as an assignee field for Format A
- [ ] Precedence: `assigned_to` > `assignee` > `agent`
- [ ] Existing behavior with `assigned_to` and `assignee` is unchanged
- [ ] Empty/missing fields → unassigned
- [ ] No new bugs introduced

### Backfill
- [ ] All task files that have `agent:` now also have `assigned_to:` (or `assignee:`)
- [ ] The original `agent:` field is preserved (don't delete it, add `assigned_to` alongside)

### Verification
- [ ] MC-007-token-budget card now shows `assignee: thor` (not unassigned)
- [ ] Mission Control loads HTTP 200
- [ ] Playwright screenshot confirms MC-007 shows thor as assignee
- [ ] No other card's assignee changed (regression check)
- [ ] Commit created, pushed (or auto-sync)

## Notes for Forge
- The parser is at `/home/nofidofi/NofiTech-Ind/01_projects/mission-control/code/kanban_parser.py`
- The card display code is in `kanban.html` — check the `renderKanbanCard` function to see what field it expects
- If `kanban.html` reads `card.assigned_to` or `card.assignee`, the parser change should make the new fields appear
- The parser change should be minimal — just add `agent` to the list of recognized fields
- Test with: `python3 -c "import sys; sys.path.insert(0, '/home/nofidofi/NofiTech-Ind/01_projects/mission-control/code'); from kanban_parser import parse_task_file; print(parse_task_file('/home/nofidofi/NofiTech-Ind/01_projects/mission-control/tasks/MC-007-token-budget.md'))"`
