---
name: MC-SKILL-SURFACE-SEP-1
title: Surface software-engineering-practice skill to Forge + Argus
project: mission-control
agent: thor
status: complete
kanban_status: done
priority: low
created: 2026-07-08
updated: 2026-07-08
description: Make the Hermes `software-engineering-practice` skill discoverable from the Mission Control project tree so both Forge (build) and Argus (verify) apply TDD / systematic-debugging / simplify-code / pre-commit-review patterns.
acceptance:
  - Skill mirrored to 01_projects/mission-control/skills/software-engineering-practice-SKILL.md: yes
  - 00_company_os/skills/SKILLS.md index updated with software-engineering-practice entry: yes
  - Forge role prompt references the skill (TDD / spike / systematic-debugging modes): yes
  - Argus role prompt references the skill (pre-commit review + systematic debugging for sev-1s): yes
  - Paired with MC-SKILL-SURFACE-ESP32-1: yes
  - GitHub auto-push handles commit: pending
evidence: 00_company_os/04_agents/logs/2026-07-08/thor-mc-skill-surface-sep-1.md
---

# MC-SKILL-SURFACE-SEP-1

**Goal:** Both Forge and Argus apply software-engineering-practice modes
(TDD, systematic debugging, simplify-code, spike, pre-commit review)
when working on code tasks.

**Changes:**
1. Mirrored `~/.hermes/skills/software-development/software-engineering-practice/SKILL.md`
   → `01_projects/mission-control/skills/software-engineering-practice-SKILL.md`.
2. Added a new section to `00_company_os/skills/SKILLS.md` listing the skill
   with per-agent (thor/forge/argus) relevance.
3. Added a "Skills to consult" block to **both** the Forge and Argus role
   prompts at `00_company_os/04_agents/{forge,argus}.md`.

**Why this skill for both agents:**
- **Forge** gets the most mileage — picks the right mode before writing
  code (TDD vs spike vs refactor).
- **Argus** uses the pre-commit review checklist as a verification lens
  and the systematic-debugging framework for sev-1 bug classification.
- **Thor** uses the mode-selection guidance when planning a task.