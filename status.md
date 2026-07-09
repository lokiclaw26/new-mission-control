---
id: mission-control
title: NofiTech Mission Control
phase: operational
status: live-monitor
progress_pct: 100%
approval_needed: false
next_action: "Mission Control v1.15.0 is the OPERATIONAL MONITOR. The page serves live data on a 30s refresh (4s overdue check). Currently tracking: diy-hub-v1 (Stage 11 shipped, awaiting NOFI verification). Read-only — no new features being built (code is frozen) but the page is alive and reports on what the rest of the company is doing."
blocker: ""
data_source: real
created: 2026-06-10
updated: 2026-06-16
version: 1.15.0-order-cleanup
charter: 01_projects/mission-control/charter.md
tasks: 01_projects/mission-control/tasks/
evidence: 00_company_os/04_agents/logs/2026-06-10/
---

# Project: NofiTech Mission Control

**PROJECT CODE FROZEN at v1.15.0-order-cleanup. PAGE IS OPERATIONAL.**

## Two-zone distinction (CRITICAL — fix from 2026-06-14 NOFI directive)

| Zone | State | Description |
|---|---|---|
| **Project code** (serve.py, mission-control.html) | **FROZEN** at v1.15.0-order-cleanup | No new features, no refactors, no UI changes, no auto-fix, no auth, no provider integration. Last commit: `dcccac4` (serve.py) + `78f8c96` (html). Tagged `mission-control-v1.15.0-order-cleanup`. |
| **Page runtime** (the operational monitor) | **LIVE & OPERATIONAL** | Polls live data: project status.md files, events.jsonl, agent state.json, task files, log health, app health. Refresh interval: 4s overdue, 30s health, 60s full. Surfaces whatever the rest of the company is doing. |

NOFI's 2026-06-14 directive clarified the original 2026-06-11 freeze: the **code is frozen** but the **page is operational**. Mission Control's job is to be a living, accurate mirror of NofiTech's disk state at all times. If the page is not showing the latest stage, that is a STATUS UPDATE failure on the agent's side, not a page failure.

## Current state (live)
- **Project code:** FROZEN at v1.15.0-order-cleanup — last shipped version, all checks passing
- **Page runtime:** OPERATIONAL — 4s overdue check, 30s health, 60s full refresh
- **PID 130719**, bound `0.0.0.0:8767`, uptime 405,000+ seconds
- 0 pending orders, 0 warnings, app_health=ok
- 8 panels live, 11 task files (all complete, frozen)
- 1 git tag: `mission-control-v1.15.0-order-cleanup`

## What the page reads (live, every refresh)
| Source | Path | What it shows |
|---|---|---|
| Project status files | `01_projects/*/status.md` | Per-project phase, status, progress, next_action, blocker, updated date |
| Event log | `00_company_os/events.jsonl` | Last 50 events (task_started, work_started, argus_passed, task_completed, etc.) with timestamps |
| Agent state | `00_company_os/state.json` | Thor/Forge/Argus status, current assignment, last activity timestamp |
| Task files | `01_projects/*/tasks/*.md` | Open/in-progress/closed tasks, acceptance criteria, Argus result |
| Provider status | `/api/version` | Live LAN IP, uptime, commit SHA, branch, dirty flag |
| Server health | Internal checks | All 4 servers reachable (MC, RGV1, DIY backend, DIY frontend) |
| App health | Internal | All 8 panels returning valid JSON, no 5xx errors |

## Currently monitored projects
- **diy-hub-v1 — Stage 11 (BUILD)** — Real fix for Wemos D1 Mini, awaiting NOFI verification
- **roguelike-v1 — PAUSED** — last shipped Stage 12 (Better Visual Style), game still playable at :8770

## Frozen scope (no code changes until NOFI unfreezes)
- ~~Cancel order button~~
- ~~Auth~~
- ~~Autostart~~
- ~~Provider integration~~
- ~~Token usage~~
- ~~Env pill cleanup~~
- ~~Log hygiene~~
- ~~UI changes~~

## Operational rules
- Mission Control never makes decisions — it reports disk state
- If a status.md is stale, that is the owning agent's failure (Thor/Forge), not MC's
- The page is read-only — no buttons that mutate state (no auto-fix, no cancel, no auth)
- Argus never edits status.md — only Thor (after explicit NOFI approval) updates a project's status
- All times shown in UTC with relative-time fallback ("2d ago", "5h ago")
