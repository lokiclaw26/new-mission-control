# NofiTech Mission Control

A local-only, zero-dependency dashboard for the **Hermes agent company** (NOFI's 3-agent team: ⚡ Thor — CEO/Planner, 🔨 Forge — Builder/Engineer, 👁️ Argus — QA/Security). It runs on a home server, reads the company's task files straight off disk, and gives you a live overview, a drag-and-drop kanban board, and a 3D memory graph — all from the Python standard library. No pip installs, no database server, no build step.

## What's in the box

| Page | URL | What it shows |
|---|---|---|
| Mission Control | `/` | Overview, agents, tasks, projects, logs/health, GitHub status, warnings |
| Kanban board | `/kanban` | 6-column board (triage → todo → ready → running_now → blocked → done) with per-agent lanes, task creation, assignment, and result popups |
| Memory graph | `/memory-graph` | 3D force-graph of the agents' shared memory (nodes: goals, tasks, decisions, errors, …) |

The **source of truth is the filesystem**: task files are markdown with YAML frontmatter (Format A) or `| Field | Value |` tables (Format B) under `01_projects/*/tasks/`. The server parses them on request — there is no hidden task database to drift out of sync.

## Quick start

```bash
cd code
./start-mc.sh          # starts serve.py on 0.0.0.0:8767 (idempotent, PID-file guarded)
# or in the foreground:
python3 serve.py
```

Then open `http://<lan-ip>:8767/`.

**Deployment layout:** the code expects to live at `01_projects/mission-control/` inside the company root (e.g. `~/NofiTech-Ind/`). `serve.py` derives the company root from its own location (`code/../..`) — see the note in [Known limitations](#known-limitations) about a few remaining hardcoded paths.

## Authentication

**None — by design.** This is a personal single-user dashboard on a trusted home LAN; the old `MC_ADMIN_TOKEN` gate was retired (2026-07-10) and every endpoint is open. Never expose the server to the public internet. If that ever changes, `security.is_authorized()` is still called before every write — restore the token check there (full implementation in git history) and everything re-locks.

The one destructive endpoint, `POST /api/memory-graph/admin-reset`, requires an explicit `{"confirm": true}` body — a safety latch against accidental wipes, not a security gate.

All persisted payloads still pass through a field-aware secret redactor (`redact_secrets`) that strips API keys, tokens, JWTs, and passwords while preserving task IDs.

## API surface

```
GET  /api/health                        status, version, uptime
GET  /api/version                       version, commit, branch, LAN IP, port
GET  /api/data/overview                 dashboard summary
GET  /api/data/agents                   thor / forge / argus rows (+ heartbeat liveness)
GET  /api/data/tasks                    real tasks (?include=demo to opt in)
GET  /api/data/projects                 01_projects/*/status.md rollup
GET  /api/data/logs                     events + health + env
GET  /api/data/github                   git remote + GitHub API + last cron run
GET  /api/data/events                   last N events from events.jsonl
GET  /api/data/kanban                   full board grouped by status + agent lanes
GET  /api/data/kanban/task/:id/result   "## Result" section for the modal
POST /api/data/kanban/task              create a task file            [auth]
PATCH /api/data/kanban/task/:id         move card / record result     [auth]
PATCH /api/data/kanban/task/:id/assign  assign to thor/forge/argus    [auth]
POST /api/data/order                    append a fix_order event      [auth]
GET/POST /api/heartbeat                 agent liveness (write is open by design)
GET  /api/memory-graph                  full graph snapshot
POST /api/memory-graph/events           ingest node/edge events       [auth]
POST /api/memory-graph/reset|rebuild    admin maintenance             [auth]
GET  /api/file?path=<rel>               serve company files (auth for everything;
                                        images/videos under results|public|assets
                                        are public, served with CSP sandbox)
```

## Automation (the "auto" loop)

Two cron-driven scripts in `scripts/` close the loop from kanban card to running agent:

1. **`kanban-auto-dispatch.sh`** (every 60s) — finds cards in `ready`, creates an `MC-AUTO-*` child task, and moves the card to `running_now`.
2. **`kanban-auto-execute.sh`** (every 2min) — finds `running_now` cards and spawns the assigned agent (`hermes -z`) with safety rails: kill-switch file, per-task dedup, agent whitelist, max 3 concurrent dispatches, max 6 per agent per hour.

Pause everything by creating `00_company_os/04_agents/.auto-execute-paused`.

## Tests

```bash
python3 -m unittest discover -s tests
```

154 tests cover auth, secret redaction, kanban parsing/moves, the memory-graph store, importer idempotency, and heartbeats. CI (GitHub Actions) runs the machine-independent suites on every push; three suites (`test_global_store`, `test_agents_live`, `test_import`) contain assertions tied to the production host's filesystem and only fully pass there.

## Design decisions

- **Stdlib only.** No pip deps anywhere — the server must survive OS reinstalls and run on anything with Python 3.10+. The 3D graph libs (`three.js`, `3d-force-graph`) are vendored under `code/vendor/`.
- **Files over databases.** Tasks are human-readable markdown, editable by agents and humans with any tool. The kanban PATCH writes a separate `kanban_status` field so the project-native `status` field is never clobbered.
- **Writes are serialized and atomic.** All task-file mutations funnel through a process-wide lock and are written via `.tmp` + `os.replace`, so concurrent PATCHes can't interleave and readers never see a half-written file.
- **Polling over push.** The dashboard polls every 5–30s; SSE was deliberately retired for robustness.
- **Every response carries security headers** (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`), and files served from `/api/file` get `Content-Security-Policy: sandbox` so an SVG with embedded script is inert.

## Known limitations

- The company-root path defaults to the production server's `/home/nofidofi/NofiTech-Ind` in `memory_graph_global.py`, `memory_graph_import.py`, and `security.py`; set the **`NOFITECH_ROOT`** env var to override it (CI does this). The LAN IP (`192.168.0.29`) is still hardcoded in `start-mc.sh` and `scripts/kanban-delegate.sh`, and the shell scripts don't honor `NOFITECH_ROOT` yet — finishing that centralization is the next planned refactor.
- `serve.py` is a single large module; the kanban/memory-graph/security logic is already split out, and the remaining `data_*()` panels are next.
- Task history lives in `tasks/` indefinitely; an archival policy for done tasks is planned.

## Repo layout

```
code/            server (serve.py), parsers, security, static HTML pages, vendored JS
scripts/         cron automation (dispatch, execute, delegate, migrations)
tasks/           kanban task files — the live board data AND the project's own history
tests/           unittest suites (no external deps)
qa/              QA harness scripts
skills/          agent skill documents (delegation protocol, morning brief, …)
cron-prompts/    prompt templates used by scheduled agent runs
data/            memory-graph seed data (runtime state is gitignored)
status.md        machine-readable project status (read by the dashboard itself)
```
