---
name: MC-SKILL-SURFACE-ESP32-1
title: Surface esp32-debugging skill to Argus via Mission Control
project: mission-control
agent: thor
status: complete
kanban_status: done
priority: low
created: 2026-07-07
updated: 2026-07-07
description: Make the Hermes `esp32-debugging` skill discoverable from the Mission Control project tree so Argus can reference it during ESP32 / firmware verification tasks.
acceptance:
  - Skill file copied to 01_projects/mission-control/skills/esp32-debugging-SKILL.md: yes
  - 00_company_os/skills/SKILLS.md index exists with per-agent tags: yes
  - Argus role prompt references the index: yes
  - Pointer file at ~/.hermes/skills/software-development/esp32-debugging/SKILL.md remains source of truth: yes
  - GitHub auto-push handles commit (no manual push needed): pending
evidence: 00_company_os/04_agents/logs/2026-07-07/thor-mc-skill-surface-esp32-1.md
---

# MC-SKILL-SURFACE-ESP32-1

**Goal:** Argus (QA) knows about `esp32-debugging` when delegated ESP32 verification tasks.

**Changes:**
1. Copied `~/.hermes/skills/software-development/esp32-debugging/SKILL.md` → `01_projects/mission-control/skills/esp32-debugging-SKILL.md` for project-tree discovery.
2. Created `00_company_os/skills/SKILLS.md` index with per-agent (thor/forge/argus) relevance tags.
3. Appended a "Skills index" pointer to Argus's role prompt at `00_company_os/04_agents/argus.md`.

**Why this matters:** Skills in `~/.hermes/skills/` are loaded by the host Hermes session but are NOT auto-injected into subagent dispatches unless explicitly named. By mirroring the file under the project tree AND giving Argus an explicit index to consult, future ESP32 firmware-verification tasks can pick it up without Thor having to remember to mention it.