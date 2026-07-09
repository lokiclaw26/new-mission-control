---
id: MC-GITHUB-REPO-SETUP-1
title: "Set up NofiTech Ind. public GitHub repo + 6h auto-push cron"
project: mission-control
created_by: thor
assigned_to: forge,argus
status: done
priority: high
created: 2026-06-16
updated: 2026-06-16T11:39:11Z
current_stage: "sprint-1-create-repo-push"
blocker: ""
description: |
  NOFI directive 2026-06-16 15:30 local. NofiTech Ind. needs a GitHub mirror
  for backup + external visibility. Plan:
  1. Create public repo https://github.com/lokiclaw26/Nofitech (provided)
  2. Initial push of /home/nofidofi/NofiTech-Ind/ (full company files)
  3. Cron job every 6h: git add -A, if any diff, commit + push
  4. Cron job logs to 00_company_os/cron-output/ for visibility
  5. Status: visible on Mission Control page
  Token: github_pat_11B6YGPUA0... (fine-grained PAT, repo scope)

acceptance: |
  1. Repo https://github.com/lokiclaw26/Nofitech exists (public)
  2. Initial commit on main contains the full /home/nofidofi/NofiTech-Ind/ tree
     EXCLUDING secrets (.env, *.pem, *.key, agent-state.json if it has tokens)
  3. `git -C /home/nofidofi/NofiTech-Ind remote -v` shows origin pointing at
     https://github.com/lokiclaw26/Nofitech.git
  4. Cron job registered with hermes (every 6h, name github-push-nofitech)
  5. Cron job uses no_agent=True (script-only) per rule:
     "cron-run sessions should not recursively schedule more cron jobs"
  6. First manual cron run completes successfully (push or "no changes")
  7. .gitignore updated to exclude: .env, *.pem, *.key, data/diy-hub.db
     (SQLite DBs are large, regenerable; not needed in source control)

evidence: ""
argus_result: pending
data_source: real
---

# MC-GITHUB-REPO-SETUP-1: GitHub repo + 6h auto-push

## Why
Backup + external visibility. Public so NOFI can share a link with anyone
without auth.

## Plan
1. .gitignore update (exclude secrets + large regenerable files)
2. Create repo via GitHub API (POST /user/repos)
3. Add origin + initial commit + push
4. Write auto-push script at ~/.hermes/scripts/github-push-nofitech.sh
5. Register cron job: every 6h, no_agent=True, script-only
6. Test: run cron once manually, verify push (or "no changes" no-op)

## What goes in the repo
- Everything in /home/nofidofi/NofiTech-Ind/ EXCEPT:
  - .env files (secrets)
  - *.pem, *.key (TLS keys)
  - data/diy-hub.db (SQLite, regenerable)
  - code/__pycache__/, code/.vite/, code/node_modules/
  - 00_company_os/04_agents/state.json if it has tokens
  - Any file matching the existing .gitignore

## What does NOT go in
- The PAT itself (write it to ~/.hermes/scripts/.env.github, NOT in repo)
- node_modules (regenerable, huge)
- .vite cache
- Python __pycache__
- Log files larger than 1MB (keep last 100KB)
