---
name: MC-SKILL-SURFACE-AUTONOMOUS-1
title: Surface autonomous-ai-agents skill subtree to Thor
project: mission-control
agent: thor
status: complete
kanban_status: done
priority: low
created: 2026-07-08
updated: 2026-07-08
description: Surface 3 skills from the autonomous-ai-agents subtree (ai-coding-cli-delegation, hermes-agent) and the software-development cron-morning-brief so Thor (the host agent) can use them when delegating to external coding CLIs, configuring Hermes itself, or planning cron jobs.
acceptance:
  - ai-coding-cli-delegation-SKILL.md mirrored: yes
  - hermes-agent-SKILL.md mirrored: yes
  - cron-morning-brief-SKILL.md mirrored: yes
  - SKILLS.md index updated with 3 new entries + per-agent relevance: yes
  - Argus role prompt extended to reference cron-morning-brief for verification: yes
  - No thor.md file exists (Thor is the host agent, baked into Hermes base prompt): confirmed
  - GitHub auto-push handles commit: pending
evidence: 00_company_os/04_agents/logs/2026-07-08/thor-mc-skill-surface-autonomous-1.md
---

# MC-SKILL-SURFACE-AUTONOMOUS-1

**Goal:** Make 3 more skills discoverable from the project tree so Thor
can pick the right one when delegating, configuring Hermes, or planning
cron jobs.

**Changes:**
1. Mirrored 3 skills to `01_projects/mission-control/skills/`:
   - `ai-coding-cli-delegation-SKILL.md`
   - `hermes-agent-SKILL.md`
   - `cron-morning-brief-SKILL.md`
2. Added 3 new sections to `00_company_os/skills/SKILLS.md` with
   per-agent (thor / argus) relevance.
3. Extended Argus role prompt to reference `cron-morning-brief` for
   cron-output verification.

**Why no Thor role-prompt edit:**
- `00_company_os/04_agents/thor.md` does not exist. Thor is the host
  agent prompt baked into Hermes' base prompt, not a file in the
  project tree. The skills index at `SKILLS.md` plus Hermes' built-in
  skill loader (which already auto-loads `hermes-agent` and
  `ai-coding-cli-delegation` from the global catalog) covers the use
  case.