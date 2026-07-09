---
id: MC-016-LAN-IP-LIVE
title: Stage 16 — Make LAN IP detection live (per-request)
project: mission-control
created_by: nofi
assigned_to: forge
status: done
priority: normal
created_at: "2026-06-11T11:45:00+00:00"
updated_at: "2026-06-11T11:55:38+00:00"
current_stage: ship
blocker: ""
data_source: real
description: "Argus 15.2 audit flagged LAN IP as a process-lifetime constant. _detect_lan_ip() runs once at module import. If DHCP changes the IP mid-session, the dashboard header shows a stale URL. Fix: re-detect on each /api/version request, with graceful fallback."
acceptance: "/api/version returns lan_ip detected at request time (not at module import). If detection fails, fall back to the previously-cached value. No new UI features. No auth. Dashboard still loads. Refresh works. start-mc.sh still works. No secrets exposed. No console/server errors. Git commit exists after pass."
argus_result: pass
---

## Brief
Argus 15.2 audit: 2 process-lifetime CONSTANTs found. One of them is `lan_ip` (the other is `port` which is hardcoded as 8767). Stage 16 moves LAN IP detection from module-import to per-request, with safe fallback if detection fails.

## Acceptance
1. /api/version returns lan_ip detected at request time
2. If detection fails, fallback to last good value (not None)
3. /api/health still works
4. Dashboard still loads
5. Refresh button still works
6. start-mc.sh still works
7. No console/server errors
8. No secrets exposed
9. Git commit exists after Argus passes
