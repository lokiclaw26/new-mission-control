---
id: MC-015-1-LIVE-VERSION
title: "Stage 15.1 — Make version and commit live"
project: mission-control
created_by: nofi
assigned_to: thor
status: done
priority: normal
created_at: "2026-06-11T11:22:38+00:00"
updated_at: "2026-06-11T11:22:38+00:00"
current_stage: ship
blocker: ""
data_source: real
description: Stage 15.1 stopped hardcoding the version string and commit hash in the dashboard — `serve.py` now reads them from git at request time so the About / footer area always shows the real `v<version>+<short-sha>` for the current checkout, not a stale baked-in value.
acceptance: `mission-control.html` (or the server endpoint it pulls from) reflects the live git version and short commit hash on every page load; no hardcoded version in the HTML; v1.10.1-live-version is the current value; Argus verified live.
argus_result: pass
---

## Brief
Stage 15.1 fixed a small but visible lie: the dashboard used to render a
hardcoded version string and a hardcoded commit hash. Thor replaced the
hardcoded values with a call into git at request time, so the displayed
version is always the real `v<version>+<short-sha>` for the current
checkout. Landed in commit c069738.

## Acceptance
- `serve.py` reads version + short commit from git at request time.
- No hardcoded version string or commit hash in `mission-control.html`.
- The current displayed value is `v1.10.1-live-version` on the live build.
- Argus verified live (no key leaks, no regression).

## Notes
- Backfilled task file: records work already shipped.
- `assigned_to: thor` is honest — Thor did this one directly.
- `argus_result: pass` reflects the 18432-byte Argus report on
  Stage 15 (which covered the live-version fix as part of its sweep).
