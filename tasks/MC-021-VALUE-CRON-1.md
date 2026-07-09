---
id: MC-021-VALUE-CRON-1
title: Add daily morning brief cron job (value-pipeline stage 1)
project: mission-control
created_by: thor
assigned_to: forge
status: done
priority: high
created_at: 2026-06-16T16:20:00+00:00
updated_at: 2026-06-16T16:30:00+00:00
current_stage: ship
blocker: ""
data_source: real
description: First concrete step toward the standing goal: an autonomous org producing value 24/7. Stage 1 of value-pipeline is a single daily cron job that produces a morning brief (yesterday's events.jsonl summary + today's pending orders + warnings count) and delivers it to chat. Proves the value-loop: scheduled LLM agent work → real artifact → user sees it. No scheduling of real builds yet — only the brief generator.
acceptance:
  - 1 cron job created via `cronjob action=create`, schedule "every 24h" anchored at 08:00 local, name `morning-brief`.
  - Job prompt self-contains: read events.jsonl (last 24h), read state.json, count warnings + pending_orders, format a short brief.
  - Job runs ONCE manually via `cronjob action=run` and produces a real brief (verified by reading the cron output file or the chat delivery).
  - events.jsonl gets a `task_assigned` event for MC-021 + a `work_started` + `forge_reported` once verified.
  - state.json shows 1 task in 'tasks' dict with status=complete after the brief is delivered.
  - No changes to serve.py or mission-control.html (this stage is backend/cron only).
  - Idempotent: re-running the cron job does not duplicate events or corrupt state.
---

# MC-021 — Value-Pipeline Stage 1: Daily Morning Brief

## Why
Goal: autonomous org that produces value 24/7. Current state: 1 cron job (github-push, every 6h) that only syncs. Zero value-producing scheduled work. This is the smallest step that moves the org from "monitoring" to "producing".

## Scope (small)
- One new cron job. Not a fleet. Not a UI panel.
- The job runs an LLM agent that reads company state and produces a brief.
- Delivered to chat (the user's home channel).

## Out of scope (later stages)
- More cron jobs (weekly project health, idea collector, etc.)
- Mission Control "Cron Jobs" panel UI
- The on-demand command interpreter ("thor, work on X")

## Reference
- Cron tool: `cronjob(action='create', schedule='0 8 * * *', name='morning-brief', prompt=<self-contained prompt>)`
- Self-contained prompt must include: paths to events.jsonl, state.json; instruction to format brief; instruction to append `work_started` and `forge_reported` events.
- Existing pattern: `~/.hermes/cron/jobs.json` (1 job present: github-push-nofitech)

## Verification (Argus)
1. `cronjob action=list` shows morning-brief job, enabled, schedule `0 8 * * *`.
2. `cronjob action=run job_id=...` produces a brief in chat that mentions:
   - count of events in last 24h from events.jsonl
   - count of pending orders from state.json
   - count of warnings from state.json
3. Running it twice does not duplicate events in events.jsonl.
4. The brief is NOT fabricated — it cites real numbers from the files.
