#!/usr/bin/env python3
"""
NofiTech Mission Control v1.9.0 (Stage 14 — auto task+event wiring)
Local-only dashboard for NOFI. 3-agent company. 6 sections.
Stage 9: Logs/Health panel with 7 fields (events, errors, warnings, app/api health, last verification, env status).
Stage 11: stabilization — task filter (demo/real), auto-detect LAN IP, LAN warning banner.
Stage 12: live data only — demo tasks hidden by default (?include=demo opt-in),
          strict log level detection (explicit `level:` only, no body inference),
          real projects only, "Last refreshed" timestamp, v1.8.0 bump.
Stage 14: automatic task and event wiring — data_tasks() reads 14-field
          frontmatter for real tasks; data_overview() counts only real
          tasks; new /api/data/events endpoint serves events.jsonl;
          data_logs() merges events.jsonl into the Logs/Health panel.
Stage 17: Provider/Model panel retired from the HTML; new Warnings panel
          with fix-order buttons (POST /api/data/order). The /api/data/provider
          endpoint is still served for any hidden API consumer.
Stage 20 (2026-06-16): added Section 9 "GitHub Connection" — new endpoint
          /api/data/github reads git remote, GitHub API, last cron run, and
          last_run.json. Additive only — no changes to existing endpoints.
MC-LIVE-REFRESH-1 (2026-06-18): POST /api/heartbeat writes a
          .heartbeat-<oid> file to the same logs_root that data_agents()
          already scans. GET /api/heartbeat returns the most-recent
          heartbeat per agent. data_agents() now also reads heartbeat
          mtime — if <120s old, the agent is treated as "live"
          (status=in_progress, last_activity="live"), regardless of
          kanban running_now or log mtime. Additive: a new
          `heartbeat_mtime_iso` field is exposed in each agent row.
MC-KANBAN-1 (2026-06-16): added Section 10 "Kanban — Multi-Agent Board" —
          3 endpoints serve the Hermes Agent Kanban tab (NOFI's 3-agent team:
          Thor/Forge/Argus). Reads the same project task files already on
          disk; no external kanban.db, no pip deps.
MC-KANBAN-2 (2026-06-16): dual-format parser. kanban_parser now reads BOTH
          YAML frontmatter (Format A) and markdown `| Field | Value |` tables
          (Format B). PATCH writes a SEPARATE `kanban_status` field instead
          of overwriting the project-native `status` field (data-loss fix).

Endpoints:
  GET  /                              → static HTML
  GET  /mission-control.html          → static HTML (alt)
  GET  /api/health                    → {status, version, uptime_sec}
  GET  /api/version                   → {version, commit, uptime_sec, started_at, lan_ip, port}
  GET  /api/data/overview             → 6 fields, real or null+reason
  GET  /api/data/agents               → 3 rows: thor, forge, argus
  GET  /api/data/tasks                → real tasks by default; ?include=demo to also show demo
  GET  /api/data/projects             → 0+ rows from 01_projects/*/status.md
  GET  /api/data/provider             → 2 rows: free, paid  (panel retired; endpoint kept)
  GET  /api/data/logs                 → events + health + env + jsonl_events
  GET  /api/data/github               → git remote + GitHub API + last cron run (Stage 20)
  GET  /api/data/events               → last 50 events from events.jsonl
  POST /api/data/order                → append a fix_order event to events.jsonl (Stage 17→19)
  GET  /api/data/orders               → list pending/in_progress fix_order events (Stage 19)
  GET  /api/data/kanban               → full board grouped by status + 3-agent lanes (MC-KANBAN-1)
  PATCH /api/data/kanban/task/:id     → update task status on disk (MC-KANBAN-1)
  POST  /api/data/kanban/task         → create a new task file from the UI (MC-KANBAN-1)
  PATCH /api/data/kanban/task/:id/assign → update task assignee on disk (MC-KANBAN-ASSIGN-1)
  POST  /api/heartbeat                  → write .heartbeat-<oid> file (MC-LIVE-REFRESH-1)
  GET   /api/heartbeat                  → most-recent heartbeat per agent (MC-LIVE-REFRESH-1)
"""
import http.server
import socketserver
import json
import mimetypes
import os
import re
import time
import urllib.parse
import urllib.request
import glob
import socket
import subprocess
import uuid
from pathlib import Path
from datetime import datetime, timezone

# MC-KANBAN-1 (2026-06-16): 3-endpoint Kanban tab.
# Imported here so the board parser lives next to the static HTML/JS that
# renders it. The parser reads the SAME project task files that the existing
# /api/data/tasks endpoint already scans, so no DB is introduced.
import kanban_parser  # noqa: E402  (intentional local import — keeps top of file clean)

PORT = 8768
HOST = "0.0.0.0"  # v1.3.0 — full LAN access (reversed Stage-1 'local only' lock per NOFI directive)
HERE = Path(__file__).parent.resolve()
PROJECT_ROOT = HERE.parent              # 01_projects/mission-control
COMPANY_ROOT = PROJECT_ROOT.parent.parent  # ~/NofiTech-Ind
DASHBOARD_PROJECT_NAME = PROJECT_ROOT.name  # 'mission-control-v2'
START_TIME = time.time()

# v1.10.0 — live version: read from git at request time (no restart needed).
# Fallback to manual values if git is unavailable or this is a fresh checkout.
FALLBACK_VERSION = "1.19.0"  # MC-V1.19.0: result body polish + DASHBOARD_PROJECT_NAME skip-self-ref + PORT=8768
FALLBACK_COMMIT = "live"

def _git(*args):
    try:
        out = subprocess.run(
            ["git", "-C", str(COMPANY_ROOT), *args],
            capture_output=True, text=True, timeout=2
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""

def get_version():
    """Read version + commit from git tags/HEAD at call time. Falls back to constants."""
    # Prefer: latest annotated tag matching 'mission-control-v*'
    tag = _git("describe", "--tags", "--abbrev=0", "--match", "mission-control-v*")
    head_short = _git("rev-parse", "--short", "HEAD")
    head_long = _git("rev-parse", "HEAD")
    dirty = _git("status", "--porcelain")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    if tag:
        # tag looks like "mission-control-v1.10.0-ui-ux" — strip prefix
        ver = tag.replace("mission-control-", "")
        commit = ver + (f"+{head_short}-dirty" if dirty else f" @ {head_short}")
    elif head_short:
        ver = FALLBACK_VERSION
        commit = head_short + ("-dirty" if dirty else "")
    else:
        ver = FALLBACK_VERSION
        commit = FALLBACK_COMMIT
    return {
        "version": ver,
        "commit": commit,
        "commit_full": head_long or None,
        "branch": branch or None,
        "dirty": bool(dirty),
        "tag": tag or None,
    }

# ---- 3-agent company (locked 2026-06-10, charter v3.0) ----
AGENTS = ["thor", "forge", "argus"]

AGENT_META = {
    "thor":  {"name": "Thor",  "role": "CEO / Planner / Coordinator", "emoji": "⚡"},
    "forge": {"name": "Forge", "role": "Builder / Engineer / DevOps", "emoji": "🔨"},
    "argus": {"name": "Argus", "role": "QA / Tester / Security",       "emoji": "👁️"},
}

# MC-LIVE-REFRESH-1 (2026-06-18): heartbeat freshness window. If a
# .heartbeat-<oid> file's mtime is within this many seconds, the agent is
# considered "live" (responding to chat right now). 120s = 2 minutes — long
# enough that a once-per-turn heartbeat from the chat UI never drops out
# between user keystrokes, short enough that a crashed/abandoned agent
# flips back to idle within a couple of polls (5s polling cadence).
HEARTBEAT_TTL_SEC = 120
HEARTBEAT_FILENAME = ".heartbeat"   # full path: <logs_root>/.heartbeat-<oid>


# ---- MC-MEMORY-GRAPH-1 (2026-06-17): Memory Graph page integration ----
# Locked decisions: Python stdlib only, JSON on disk, polling for realtime.
# Event contract: {type, ...payload} where type ∈ {node.upsert, edge.upsert,
# memory.snapshot, node.delete, edge.delete}. Nodes keyed by stable id; edges
# get stable id `edge-<source>-target-<kind>` for idempotent upsert. The
# append-only event log lives next to the snapshot file.
MG_DATA_DIR = PROJECT_ROOT / "data"
MG_GRAPH_PATH = MG_DATA_DIR / "memory-graph.json"
MG_EVENTS_PATH = MG_DATA_DIR / "memory-graph-events.jsonl"
MG_SAMPLE_PATH = MG_DATA_DIR / "sample-graph.json"
MG_EVENT_LOG_MAX_LINES = 10_000
MG_NODE_KINDS = {
    "goal", "task", "memory", "decision", "tool", "file",
    "error", "concept", "entity", "session", "message",
}
MG_VALID_EVENT_TYPES = {
    "node.upsert", "edge.upsert", "memory.snapshot",
    "node.delete", "edge.delete",
}


# ---------- helpers ----------

def _detect_lan_ip():
    """Detect primary outbound LAN IP via UDP-socket trick.
    Opens a UDP socket, 'connects' to 8.8.8.8:80 (no packet sent), reads
    the local endpoint the OS assigned, closes. Falls back to 127.0.0.1.
    Returns (ip, ok) tuple so callers can show a banner on failure."""
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.3)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0], True
    except Exception:
        return "127.0.0.1", False
    finally:
        if s:
            try: s.close()
            except Exception: pass


# Detect once at import time so the value is stable across requests.
# Stage 16: also seed the per-request fallback cache with the import-time value,
# so a later transient detection failure still returns SOMETHING sensible.
HOST_IP, _LAN_IP_OK = _detect_lan_ip()
_last_known_lan_ip = HOST_IP  # cache for get_lan_ip() fallback


def get_lan_ip():
    """Stage 16: per-request LAN IP detection with last-known-good fallback.

    Tries to re-detect the outbound LAN IP (handles DHCP/VPN/network switch
    mid-session). On any failure, returns the cached `_last_known_lan_ip`
    so the dashboard never goes blank. As a side effect, updates the cache
    on success so subsequent failures degrade to the freshest good value.
    """
    global _last_known_lan_ip
    try:
        ip, ok = _detect_lan_ip()
    except Exception:
        return _last_known_lan_ip
    if ok and ip:
        _last_known_lan_ip = ip
        return ip
    return _last_known_lan_ip


def safe_read(path, max_bytes=256 * 1024):
    try:
        p = Path(path)
        if not p.is_file():
            return None
        if p.stat().st_size > max_bytes:
            return None
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def parse_frontmatter(text):
    """Returns (meta_dict, body_str). Empty meta if no frontmatter."""
    if not text or not text.startswith("---\n"):
        return {}, text or ""
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    fm = text[4:end]
    body = text[end + 5:]
    meta = {}
    for line in fm.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body


def safe_join(root, requested):
    """Resolve a path under root, raise if it escapes."""
    rel = os.path.normpath(requested or ".").lstrip("/")
    if rel in ("", "."):
        return str(root)
    full = os.path.abspath(os.path.join(str(root), rel))
    if not (full == str(root) or full.startswith(str(root) + os.sep)):
        raise ValueError("Path escapes root")
    return full


def list_subdirs(root):
    p = Path(root)
    if not p.is_dir():
        return []
    return sorted([d.name for d in p.iterdir() if d.is_dir() and not d.name.startswith(".")])


def list_files(root, pattern):
    p = Path(root)
    if not p.is_dir():
        return []
    return sorted(p.glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True)


def rel_time(iso_or_mtime):
    """Return 'Xm ago' / 'Xh ago' / 'Xd ago' or '—'."""
    try:
        if isinstance(iso_or_mtime, (int, float)):
            dt = datetime.fromtimestamp(iso_or_mtime, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(iso_or_mtime).replace("Z", "+00:00"))
        diff = (datetime.now(timezone.utc) - dt).total_seconds()
        if diff < 0:
            return "now"
        if diff < 60:
            return f"{int(diff)}s ago"
        if diff < 3600:
            return f"{int(diff // 60)}m ago"
        if diff < 86400:
            return f"{int(diff // 3600)}h ago"
        return f"{int(diff // 86400)}d ago"
    except Exception:
        return "—"


# ---------- data endpoints ----------

def data_overview():
    """6 fields, each real or null+reason.

    MC-LIVE-DASHBOARD-1 (2026-06-18): rewritten to derive EVERYTHING from
    `data_kanban()` — the live source of truth — instead of stale task-file
    status + memory-log entries. The kanban is updated on every PATCH and
    is the most-recent state; the frontmatter status + memory-log are
    historical and lag behind.

    Derivation rules (locked in spec):
      current_project  = project of any running_now task; fallback to project
                         of the most-recent task-file mtime in last 24h; else
                         "—" (NOT alphabetical first subdir).
      active_tasks     = count of kanban tasks with kanban_status=running_now
      failed_tasks     = count of kanban tasks with kanban_status=blocked AND
                         no blocker_reason on disk
      warnings         = blocked count + log warns count
      last_check       = now (every poll = "just polled")
      polled_at_iso    = current UTC ISO timestamp (used by the JS pulse)
    """
    out = {}

    # Always-true polled-at timestamp — used by the JS to render the
    # "live" pulse + relative-time freshness indicator.
    now_dt = datetime.now(timezone.utc)
    out["polled_at_iso"] = now_dt.isoformat()

    # 1. Hermes status: probe the gateway (best-effort) + report uptime
    try:
        # Light probe: check that ~/.hermes/ exists and has a config
        cfg = Path.home() / ".hermes" / "config.yaml"
        out["hermes_status"] = {
            "value": "ok" if cfg.exists() else "unknown",
            "reason": None if cfg.exists() else "no ~/.hermes/config.yaml",
        }
    except Exception as e:
        out["hermes_status"] = {"value": None, "reason": str(e)}

    # 2. Current project: DERIVE FROM KANBAN (most live source).
    # Get the live board; fall back to "—" if anything goes wrong.
    try:
        board = data_kanban()
    except Exception as e:
        board = {"columns": [], "summary": {"by_status": {}, "by_assignee": {}}}
    running_now_tasks = []
    for col in (board.get("columns") or []):
        if col.get("id") == "running_now":
            running_now_tasks = list(col.get("tasks") or [])
            break
    # Flatten the by_status for convenience
    by_status = (board.get("summary") or {}).get("by_status") or {}

    current_project_value = None
    current_project_reason = None
    if running_now_tasks:
        # Use the project of the first running_now task (kanban is sorted
        # by created desc so this is the most recently started).
        current_project_value = running_now_tasks[0].get("project") or None
        if current_project_value is None:
            current_project_reason = "running task has no project field"
    else:
        # Fallback: most-recent task-file mtime in last 24h
        try:
            most_recent = None
            for root in (COMPANY_ROOT / "01_projects", COMPANY_ROOT / "00_company_os"):
                if not root.is_dir():
                    continue
                for tf in root.glob("*/tasks/*.md"):
                    try:
                        mt = tf.stat().st_mtime
                    except Exception:
                        continue
                    if (now_dt.timestamp() - mt) > 86400:
                        continue  # older than 24h — skip
                    if most_recent is None or mt > most_recent[0]:
                        most_recent = (mt, tf)
            if most_recent:
                # The project is the directory two levels up from the task file
                # (e.g. .../01_projects/<project>/tasks/<task>.md).
                # MC-FIX-CURRENT-PROJECT-SELF (2026-07-15): skip the dashboard's
                # own dir so the "current project" card always reflects a real
                # project, not "mission-control-v2" pointing at itself.
                task_file = most_recent[1]
                project_dir = task_file.parent.parent
                if project_dir.name in (DASHBOARD_PROJECT_NAME,):
                    # Look for the next-recent task file outside the dashboard dir
                    candidates = []
                    for root in (COMPANY_ROOT / "01_projects", COMPANY_ROOT / "00_company_os"):
                        if not root.is_dir():
                            continue
                        for tf in root.glob("*/tasks/*.md"):
                            if tf.parent.parent.name == DASHBOARD_PROJECT_NAME:
                                continue
                            try:
                                mt = tf.stat().st_mtime
                            except Exception:
                                continue
                            if (now_dt.timestamp() - mt) > 86400:
                                continue
                            candidates.append((mt, tf))
                    if candidates:
                        candidates.sort(key=lambda x: x[0], reverse=True)
                        project_dir = candidates[0][1].parent.parent
                current_project_value = project_dir.name
            else:
                current_project_reason = "no kanban activity in last 24h and no recent task files"
        except Exception as e:
            current_project_reason = f"project lookup failed: {e}"

    out["current_project"] = {
        "value": current_project_value,
        "reason": current_project_reason,
    }

    # 3. Active tasks: kanban running_now count
    active = by_status.get("running_now", 0)
    out["active_tasks"] = {
        "value": active,
        "reason": None if active else "no tasks in running_now",
    }

    # 4. Failed tasks: blocked count with empty blocker reason
    # We must read blocker reason from the source file because the kanban
    # card dict doesn't expose it. Skip if the file is unreadable.
    blocked_count = by_status.get("blocked", 0)
    failed = 0
    if blocked_count:
        blocked_col = None
        for col in (board.get("columns") or []):
            if col.get("id") == "blocked":
                blocked_col = col
                break
        if blocked_col:
            for t in (blocked_col.get("tasks") or []):
                if not _task_has_blocker_reason(t):
                    failed += 1
    out["failed_tasks"] = {
        "value": failed,
        "reason": None if (active or failed or blocked_count) else "no blocked tasks",
    }

    # 5. Warnings: blocked count + log warns count
    log_warnings = 0
    logs_root = COMPANY_ROOT / "00_company_os" / "04_agents" / "logs"
    if logs_root.is_dir():
        for f in logs_root.rglob("*.md"):
            txt = safe_read(f)
            if not txt:
                continue
            meta, _ = parse_frontmatter(txt)
            if (meta.get("level") or "").lower() == "warn":
                log_warnings += 1
    warnings = blocked_count + log_warnings
    have_any_source = bool((board.get("columns") or [])) or logs_root.is_dir()
    out["warnings"] = {
        "value": warnings if have_any_source else None,
        "reason": None if have_any_source else "no tasks or log files yet",
        "breakdown": {"blocked_tasks": blocked_count, "log_warns": log_warnings},
    }

    # 6. Last check = now (every poll = "just polled"). The frontend uses
    # `polled_at_iso` for the live pulse + relative time display.
    last_iso = now_dt.isoformat()
    out["last_check"] = {
        "value": last_iso,
        "reason": None,
        "rel": "live",
    }

    return out


def _task_has_blocker_reason(task_card):
    """Return True if the underlying task file on disk has a non-empty
    blocker reason. Reads the source_file referenced by the kanban card.
    Tolerant of missing/unreadable files (returns False)."""
    try:
        rel = task_card.get("source_file") or ""
        if not rel:
            return False
        path = COMPANY_ROOT / rel
        if not path.is_file():
            return False
        txt = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    # Try Format A (YAML frontmatter `blocker:` or `blockers:`)
    meta, _ = parse_frontmatter(txt)
    for key in ("blocker", "blockers"):
        v = meta.get(key)
        if v is None:
            continue
        s = str(v).strip()
        if s and s.lower() not in ("none", "null", "n/a", "-"):
            return True
    # Try Format B (markdown table with `| **blocker** | ... |`)
    table, _body = kanban_parser.parse_markdown_table(txt)
    for key in ("blocker", "blockers"):
        v = table.get(key)
        if v is None:
            continue
        s = str(v).strip()
        if s and s.lower() not in ("none", "null", "n/a", "-"):
            return True
    return False


def _read_agent_state():
    """Read 00_company_os/04_agents/state.json if present. Returns dict or {}."""
    p = COMPANY_ROOT / "00_company_os" / "04_agents" / "state.json"
    txt = safe_read(p)
    if not txt:
        return {}
    try:
        d = json.loads(txt)
        if not isinstance(d, dict):
            return {}
        return d
    except Exception:
        return {}


def data_agents():
    """3 rows: thor, forge, argus.

    MC-LIVE-DASHBOARD-1 (2026-06-18): rewritten to derive each agent's
    `current_assignment`, `status`, and `last_activity` from the live
    kanban board (via `data_kanban()`), not from the stale state.json.
    The kanban reflects "what each agent is working on RIGHT NOW" because
    every PATCH updates it; state.json is only written on rare explicit
    transitions.

    MC-LIVE-REFRESH-1 (2026-06-18): heartbeat precedence — if a
    .heartbeat-<oid> file in logs_root has an mtime within HEARTBEAT_TTL_SEC
    (120s), the agent is considered "live" (responding to chat right now)
    and is reported with status="in_progress" and last_activity="live",
    regardless of kanban running_now or log mtime. Heartbeat wins over
    running_now because heartbeat = "agent is active right this second",
    which is strictly fresher than "task assigned to this agent on the
    board". A new additive field `heartbeat_mtime_iso` is exposed so the
    frontend can render the freshness independently.

    Source-of-truth precedence (per spec):
      current_assignment = the most-recently-running_now task for this agent
                          (fallback: empty string — NOT stale state.json).
      status             = "in_progress" if heartbeat fresh OR running_now
                          "idle"          if has no running task but log
                                           mtime in last 24h
                          "never-active"  if no logs at all
      last_activity      = "live" if status == in_progress
                          else rel_time(last_log_mtime)
      stale              = unchanged: true if running_now > 0 but no log
                           mtime in 30 min
    """
    # ---- live board snapshot ----
    try:
        board = data_kanban()
    except Exception:
        board = {"columns": [], "summary": {"by_status": {}, "by_assignee": {}}}

    # Build a per-agent index: running_now tasks grouped by assignee.
    # The kanban already sorts each column by created desc, so the first
    # match for an agent is the most-recently-running one.
    running_by_agent: dict[str, dict] = {}
    running_total = 0
    for col in (board.get("columns") or []):
        if col.get("id") != "running_now":
            continue
        running_total = col.get("count", 0) or 0
        for card in (col.get("tasks") or []):
            assignee = (card.get("assigned_to") or "").strip().lower()
            if not assignee:
                continue
            # First-seen for this agent wins (already most-recent by created).
            if assignee not in running_by_agent:
                running_by_agent[assignee] = card
        break

    state = _read_agent_state()
    agent_state = state.get("agents", {}) if isinstance(state.get("agents"), dict) else {}
    state_updated_mtime = None
    sp = COMPANY_ROOT / "00_company_os" / "04_agents" / "state.json"
    if sp.is_file():
        state_updated_mtime = sp.stat().st_mtime

    logs_root = COMPANY_ROOT / "00_company_os" / "04_agents" / "logs"
    rows = []
    for oid in AGENTS:
        meta = AGENT_META[oid]
        ast = agent_state.get(oid, {}) if isinstance(agent_state.get(oid), dict) else {}

        # ---- running_now task (live source of truth) ----
        live_task = running_by_agent.get(oid)
        live_task_id = (live_task or {}).get("task_id") or ""

        # ---- last activity (real log file mtime) ----
        last_mtime = None
        last_file = None
        if logs_root.is_dir():
            # Match BOTH the canonical convention (<oid>-*.md) AND legacy files
            # that contain the agent name anywhere (e.g. test-warn-argus.md from Stage 4).
            # We dedupe via a set to avoid double-counting files that match both.
            seen = set()
            for pattern in (f"{oid}-*.md", f"*-{oid}-*.md", f"*{oid}*.md"):
                for f in logs_root.rglob(pattern):
                    if f in seen:
                        continue
                    seen.add(f)
                    mt = f.stat().st_mtime
                    if last_mtime is None or mt > last_mtime:
                        last_mtime = mt
                        last_file = f
        # For thor (the CEO agent), also count the state.json itself as activity
        # ONLY if the state has an entry for thor with status=active.
        # This is honest because thor literally wrote that file.
        if oid == "thor" and state_updated_mtime and ast.get("status") == "active":
            if last_mtime is None or state_updated_mtime > last_mtime:
                # Use state.json as the last_activity timestamp source
                last_mtime = state_updated_mtime
                last_file = sp

        # ---- MC-LIVE-REFRESH-1: heartbeat freshness ----
        # Check the .heartbeat-<oid> file in logs_root. If its mtime is
        # within HEARTBEAT_TTL_SEC, the agent is responding to chat right
        # now → heartbeat_mtime is set and heartbeat_fresh=True.
        heartbeat_mtime = None
        heartbeat_path = None
        if logs_root.is_dir():
            hb = logs_root / f"{HEARTBEAT_FILENAME}-{oid}"
            if hb.is_file():
                heartbeat_path = hb
                heartbeat_mtime = hb.stat().st_mtime
        heartbeat_fresh = bool(
            heartbeat_mtime is not None
            and (time.time() - heartbeat_mtime) < HEARTBEAT_TTL_SEC
        )
        if heartbeat_fresh:
            # Override mtime_age_seconds — heartbeat is the freshest signal.
            last_mtime = heartbeat_mtime
            last_file = heartbeat_path

        # ---- status (derived from heartbeat > kanban > log mtime) ----
        if heartbeat_fresh or live_task:
            status = "in_progress"
        elif last_mtime and (time.time() - last_mtime) < 86400:
            status = "idle"
        elif last_mtime:
            # logs exist but all older than 24h → idle
            status = "idle"
        else:
            status = "never-active"

        # ---- current assignment + blocker ----
        # LIVE source: the kanban running_now task. NO state.json fallback
        # — state.json is stale by definition (only written on rare explicit
        # transitions). If the agent has no running task, current_assignment
        # is None so the UI shows "no current assignment" honestly.
        if live_task:
            current_assignment = live_task.get("task_id") or None
        else:
            current_assignment = None
        # If current_assignment is empty string, treat as None
        if current_assignment == "":
            current_assignment = None
        blocker = ast.get("blocker") or None
        if blocker == "":
            blocker = None

        # ---- last_activity: "live" for active, relative time for idle ----
        if status == "in_progress":
            last_activity_label = "live"
        else:
            last_activity_label = rel_time(last_mtime) if last_mtime else "—"

        # ---- reason for unavailable fields ----
        reasons = []
        if not last_mtime and status == "never-active":
            reasons.append("no log files yet for this agent")
        if not current_assignment:
            reasons.append("no current assignment")
        if blocker is None:
            reasons.append("no blocker")

        # ---- MC-AGENT-LOG-FIX-1: expose mtime_iso + mtime_age_seconds so the
        # frontend can decide its own "stuck" threshold. Stale = no fresh log
        # in 30+ min AND agent claims to be spawning/in_progress (i.e. should
        # be writing logs but isn't).
        if last_mtime:
            mtime_iso = datetime.fromtimestamp(last_mtime, tz=timezone.utc).isoformat()
            mtime_age_seconds = int(time.time() - last_mtime)
        else:
            mtime_iso = None
            mtime_age_seconds = None
        # MC-LIVE-REFRESH-1: expose the heartbeat-specific mtime separately
        # so the frontend can render its own freshness indicator without
        # relying on the (now-overridden) generic mtime_iso. None when no
        # heartbeat file exists for this agent.
        if heartbeat_mtime is not None:
            heartbeat_mtime_iso = datetime.fromtimestamp(
                heartbeat_mtime, tz=timezone.utc
            ).isoformat()
            heartbeat_age_seconds = int(time.time() - heartbeat_mtime)
        else:
            heartbeat_mtime_iso = None
            heartbeat_age_seconds = None
        STUCK_STATUSES = {"spawning", "in_progress", "in-progress"}
        # An agent is "stale" if it has NO live task but state.json claims
        # it was actively working AND we have no log mtime in 30+ min.
        stale = bool(
            mtime_age_seconds is not None
            and mtime_age_seconds > 30 * 60
            and status in STUCK_STATUSES
        )

        rows.append({
            "id": oid,
            "name": meta["name"],
            "role": meta["role"],
            "emoji": meta["emoji"],
            "status": status,
            "last_activity": last_activity_label,
            "last_activity_iso": mtime_iso,
            "mtime_iso": mtime_iso,
            "mtime_age_seconds": mtime_age_seconds,
            "heartbeat_mtime_iso": heartbeat_mtime_iso,
            "heartbeat_age_seconds": heartbeat_age_seconds,
            "heartbeat_fresh": heartbeat_fresh,
            "stale": stale,
            "last_log": str(last_file.relative_to(COMPANY_ROOT)) if last_file else None,
            "current_assignment": current_assignment,
            "blocker": blocker,
            "reasons": reasons,
        })

    # MC-LIVE-DASHBOARD-1: also surface the polled_at timestamp so the
    # frontend can render the live pulse + relative time consistently
    # across all panels.
    return {
        "agents": rows,
        "count": len(rows),
        "polled_at_iso": datetime.now(timezone.utc).isoformat(),
    }


# ---- MC-LIVE-REFRESH-1 (2026-06-18): heartbeat endpoint + writers ----------

def _heartbeat_path(agent_id):
    """Return the on-disk path for agent_id's heartbeat file.

    Uses the SAME logs_root that data_agents() scans (so the file is found
    on the next /api/data/agents request without extra plumbing). The
    leading dot makes the file hidden in normal `ls` listings — these are
    signal files, not user-facing logs.
    """
    logs_root = COMPANY_ROOT / "00_company_os" / "04_agents" / "logs"
    return logs_root / f"{HEARTBEAT_FILENAME}-{agent_id}"


def write_heartbeat(agent_id):
    """Write a fresh .heartbeat-<oid> file. Default agent = "thor".

    Body: {"agent": "<oid>", "ts": "<iso>"}. The "ts" field is the
    server-side wall clock at write time — the frontend does not supply
    its own timestamp (would let a buggy client fake an agent that
    crashed hours ago). The file is written atomically: write to a
    sibling .tmp then os.replace, so a concurrent reader never sees a
    half-written file.
    """
    agent = (agent_id or "").strip().lower() or "thor"
    if agent not in AGENTS:
        raise ValueError(f"unknown agent: {agent!r}; must be one of {AGENTS}")
    path = _heartbeat_path(agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "agent": agent,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return {
        "ok": True,
        "agent": agent,
        "ts": payload["ts"],
        "path": str(path.relative_to(COMPANY_ROOT)),
    }


def read_heartbeats():
    """Return the most-recent heartbeat per agent, oldest-first.

    Reads every .heartbeat-<oid> file under logs_root and groups by agent.
    If multiple files exist for the same agent (shouldn't, but possible
    if logs_root ever races), the newest mtime wins. Each entry has the
    parsed JSON payload plus an mtime_iso + age_seconds field so the
    frontend can render without doing date math.
    """
    logs_root = COMPANY_ROOT / "00_company_os" / "04_agents" / "logs"
    by_agent: dict[str, dict] = {}
    if logs_root.is_dir():
        for f in logs_root.glob(f"{HEARTBEAT_FILENAME}-*"):
            oid = f.name[len(HEARTBEAT_FILENAME) + 1:]
            if oid not in AGENTS:
                continue
            try:
                mtime = f.stat().st_mtime
            except OSError:
                continue
            try:
                payload = json.loads(f.read_text(encoding="utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = {}
            entry = {
                "agent": payload.get("agent") or oid,
                "ts": payload.get("ts"),
                "mtime_iso": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat(),
                "age_seconds": int(time.time() - mtime),
                "fresh": (time.time() - mtime) < HEARTBEAT_TTL_SEC,
                "path": str(f.relative_to(COMPANY_ROOT)),
            }
            existing = by_agent.get(oid)
            if existing is None or mtime > existing["_mtime"]:
                entry["_mtime"] = mtime
                by_agent[oid] = entry
    # Strip the internal _mtime helper key and order: thor, forge, argus.
    out = []
    for oid in AGENTS:
        e = by_agent.get(oid)
        if e is None:
            out.append({"agent": oid, "ts": None, "fresh": False})
            continue
        e.pop("_mtime", None)
        out.append(e)
    return {
        "heartbeats": out,
        "count": len(out),
        "ttl_sec": HEARTBEAT_TTL_SEC,
        "polled_at_iso": datetime.now(timezone.utc).isoformat(),
    }


def data_tasks(include_demo=False):
    """All tasks across all projects. By default, EXCLUDES demo data.
    Pass include_demo=True to also include local-demo tasks.
    A task is "demo" if its frontmatter has data_source: local-demo.
    Stage 12: live-data dashboard — demo is opt-in via ?include=demo.
    Stage 14: returns the full 14-field schema for real tasks; legacy
    Stage 6 demo tasks get a 'description' / 'evidence' / 'argus_result'
    passthrough so they still render the same way as before.
    """
    rows = []
    tasks_dirs = sorted((COMPANY_ROOT / "01_projects").glob("*/tasks"))
    for td in tasks_dirs:
        for tf in td.glob("*.md"):
            txt = safe_read(tf)
            if not txt:
                continue
            meta, body = parse_frontmatter(txt)
            ds = (meta.get("data_source") or "").strip()
            if ds == "local-demo" and not include_demo:
                continue  # hide demo from main dashboard (Stage 12)

            is_real = ds == "real"
            if is_real:
                # Stage 14 schema — 14 fields. Use '—' for missing values
                # so the UI never renders an empty cell.
                def _or_dash(v):
                    return v if (v is not None and str(v).strip() not in ("", "none")) else "—"
                rows.append({
                    "id": meta.get("id") or tf.stem,
                    "title": meta.get("title") or tf.stem,
                    "project": meta.get("project") or td.parent.name,
                    "created_by": _or_dash(meta.get("created_by") or meta.get("agent")),
                    "assigned_to": _or_dash(meta.get("assigned_to") or meta.get("agent")),
                    "status": (meta.get("status") or "triage").lower(),
                    "priority": (meta.get("priority") or "normal").lower(),
                    "created": _or_dash(meta.get("created_at") or meta.get("created")),
                    "updated": _or_dash(meta.get("updated_at") or meta.get("updated")),
                    "created_at": _or_dash(meta.get("created_at")),
                    "updated_at": _or_dash(meta.get("updated_at")),
                    "current_stage": _or_dash(meta.get("current_stage")),
                    "blocker": _or_dash(meta.get("blocker") or meta.get("blockers")),
                    "description": meta.get("description") or "",
                    "acceptance": meta.get("acceptance") or "",
                    "evidence": meta.get("evidence") or "none",
                    "argus_result": meta.get("argus_result") or "pending",
                    "data_source": "real",
                    "path": str(tf.relative_to(COMPANY_ROOT)),
                })
            else:
                # Legacy / demo shape — keep the old render path intact.
                rows.append({
                    "id": meta.get("id") or tf.stem,
                    "title": meta.get("title") or tf.stem,
                    "project": meta.get("project") or td.parent.name,
                    "agent": meta.get("agent") or "—",
                    "status": meta.get("status") or "open",
                    "priority": meta.get("priority") or "P2",
                    "created": meta.get("created") or "—",
                    "updated": meta.get("updated") or "—",
                    "description": meta.get("description") or "",
                    "evidence": meta.get("evidence") or "none",
                    "blockers": meta.get("blockers") or "",
                    "argus_result": meta.get("argus_result") or "pending",
                    "data_source": meta.get("data_source") or "",
                    "path": str(tf.relative_to(COMPANY_ROOT)),
                })
    rows.sort(key=lambda r: r.get("updated") or r.get("updated_at") or "", reverse=True)
    sources = set()
    for r in rows:
        if r.get("data_source"):
            sources.add(r["data_source"])
    return {
        "tasks": rows,
        "count": len(rows),
        "data_sources": sorted(sources) if sources else [],
        "include_demo": include_demo,
        "reason": None if rows else "No real tasks yet.",
    }


# ---------- GitHub Connection (Section 9, added 2026-06-16 FORGE/NOFI directive) ----------

def data_github():
    """GitHub connection status + cron job state.
    Reads:
      - git remote origin URL
      - GitHub API for repo info (if token available)
      - git log for unpushed commits
      - ~/.hermes/cron-output/github-push-nofitech/last_run.json
      - hermes cron list (parsed for next run)
    Additive — does not modify any existing endpoint or function.
    """
    out = {"ts": datetime.now(tz=timezone.utc).isoformat(), "errors": []}

    # ---- repo info ----
    out["repo"] = {"url": "", "visibility": "?", "last_push_at": None,
                   "total_commits_on_main": 0, "description": ""}
    try:
        r = subprocess.run(
            ["git", "-C", str(COMPANY_ROOT), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5,
        )
        out["repo"]["url"] = r.stdout.strip()
    except Exception as e:
        out["errors"].append(f"git remote failed: {e}")

    # GitHub API (if token)
    env_file = Path.home() / ".hermes" / "scripts" / ".env.github"
    if env_file.exists():
        try:
            env = {}
            for line in env_file.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
            token = env.get("GITHUB_TOKEN", "")
            # Parse owner/repo from URL
            url = out["repo"]["url"]
            if "github.com/" in url:
                owner_repo = url.split("github.com/")[-1].rstrip(".git").rstrip("/")
                if "/" in owner_repo:
                    owner, repo = owner_repo.split("/", 1)
                    api_url = f"https://api.github.com/repos/{owner}/{repo}"
                    req = urllib.request.Request(api_url, headers={
                        "Authorization": f"token {token}",
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "nofitech-mission-control",
                    })
                    try:
                        with urllib.request.urlopen(req, timeout=5) as r:
                            data = json.loads(r.read())
                            out["repo"]["visibility"] = data.get("visibility", "?")
                            out["repo"]["last_push_at"] = data.get("pushed_at")
                            out["repo"]["description"] = data.get("description", "")
                            # default_branch + size
                            out["repo"]["default_branch"] = data.get("default_branch", "?")
                            out["repo"]["size_kb"] = data.get("size", 0)
                            out["repo"]["stars"] = data.get("stargazers_count", 0)
                            out["repo"]["open_issues"] = data.get("open_issues_count", 0)
                    except Exception as api_e:
                        out["errors"].append(f"github api repo: {api_e}")
        except Exception as e:
            out["errors"].append(f"github api: {e}")

    # ---- local state ----
    out["local"] = {"branch": "?", "last_commit_sha": "", "last_commit_msg": "",
                    "unpushed_commits": 0}
    try:
        r = subprocess.run(
            ["git", "-C", str(COMPANY_ROOT), "branch", "--show-current"],
            capture_output=True, text=True, timeout=5,
        )
        out["local"]["branch"] = r.stdout.strip() or "(detached)"
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["git", "-C", str(COMPANY_ROOT), "log", "-1", "--format=%H|%s"],
            capture_output=True, text=True, timeout=5,
        )
        parts = r.stdout.strip().split("|", 1)
        if parts and parts[0]:
            out["local"]["last_commit_sha"] = parts[0]
            out["local"]["last_commit_msg"] = parts[1] if len(parts) > 1 else ""
    except Exception:
        pass
    # Unpushed commits — fetch origin/<branch> first so the local ref isn't
    # stale. Without this, origin/main can lag days behind GitHub and MC reports
    # every cron-pushed commit as "unpushed" (45+) even though the push succeeded.
    # Fetch is best-effort: on failure, fall back to the cached ref + capture the
    # error so MC can surface "fetch failed" instead of fake-unpushed numbers.
    try:
        branch = out["local"]["branch"] or "main"
        # Skip fetch on detached HEAD / non-branch branches where origin/<branch>
        # would not exist anyway.
        if branch and branch not in ("(detached)", "?"):
            fr = subprocess.run(
                ["git", "-C", str(COMPANY_ROOT), "fetch", "origin", branch,
                 "--quiet"],
                capture_output=True, text=True, timeout=5,
            )
            if fr.returncode != 0:
                out["errors"].append(
                    f"git fetch origin {branch} failed: "
                    f"{(fr.stderr or '').strip()[:120] or fr.stdout.strip()[:120]}"
                )
        # Try the exact remote ref
        r = subprocess.run(
            ["git", "-C", str(COMPANY_ROOT), "log", f"origin/{branch}..HEAD", "--oneline"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            out["local"]["unpushed_commits"] = len(
                [l for l in r.stdout.splitlines() if l.strip()]
            )
    except Exception:
        pass

    # ---- cron state ----
    out["cron"] = {
        "job_id": "", "name": "", "schedule": "", "next_run": "", "last_run": None,
        "last_outcome": "unknown", "last_message": "", "last_error": "",
        "last_duration_ms": 0, "last_files_changed": 0, "last_commit_sha": "",
    }
    try:
        r = subprocess.run(
            ["hermes", "cron", "list"],
            capture_output=True, text=True, timeout=5,
        )
        text = r.stdout
        # The cron list output is a pretty-printed block per job. Find the
        # block that mentions github-push-nofitech and extract its fields.
        # Block delimiters: hex job_id line `  <hex> [active]` followed by
        # indented `Name: ...`, `Schedule: ...`, `Next run: ...`.
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if "github-push-nofitech" in line.lower():
                # Walk backwards to find the job_id (8+ hex chars at line start)
                for j in range(i, max(-1, i - 5), -1):
                    m = re.search(r'^\s*([a-f0-9]{8,})\s*\[', lines[j])
                    if m:
                        out["cron"]["job_id"] = m.group(1)
                        break
                # Walk forward within the same block to extract fields.
                # The block ends at the next job_id or at a blank line followed
                # by another job_id. Cap at +10 lines.
                ctx = "\n".join(lines[i:i + 10])
                m = re.search(r'Name:\s*(\S+)', ctx)
                if m:
                    out["cron"]["name"] = m.group(1)
                m = re.search(r'Schedule:\s*(\S+)', ctx)
                if m:
                    out["cron"]["schedule"] = m.group(1)
                m = re.search(r'Next run:\s*(\S+)', ctx)
                if m:
                    out["cron"]["next_run"] = m.group(1)
                break
    except Exception as e:
        out["errors"].append(f"hermes cron: {e}")

    # ---- last run status from file ----
    status_file = (Path.home() / ".hermes" / "cron-output"
                   / "github-push-nofitech" / "last_run.json")
    if status_file.exists():
        try:
            data = json.loads(status_file.read_text())
            out["cron"]["last_run"] = data.get("ts")
            out["cron"]["last_outcome"] = data.get("outcome", "unknown")
            out["cron"]["last_message"] = data.get("message", "")
            out["cron"]["last_error"] = data.get("error", "")
            out["cron"]["last_duration_ms"] = data.get("duration_ms", 0)
            out["cron"]["last_files_changed"] = data.get("files_changed", 0)
            out["cron"]["last_commit_sha"] = data.get("commit_sha", "")
        except Exception as e:
            out["errors"].append(f"last_run.json read: {e}")
    else:
        out["cron"]["last_outcome"] = "never_ran"

    # ---- overall status ----
    if out["cron"]["last_outcome"] == "failed":
        out["status"] = "failed"
    elif out["local"]["unpushed_commits"] and out["local"]["unpushed_commits"] > 0:
        out["status"] = "behind"
    elif out["cron"]["last_outcome"] in ("success", "no_changes"):
        out["status"] = "ok"
    else:
        out["status"] = "unknown"

    return out


# ---------- events.jsonl (Stage 14) ----------

def _read_events_tail(limit: int = 50):
    """Read the last `limit` lines of events.jsonl as parsed dicts.
    Returns ([], 'No events yet.') if the file is missing or empty.
    Tolerates malformed lines (skips them)."""
    p = COMPANY_ROOT / "00_company_os" / "events.jsonl"
    if not p.is_file() or p.stat().st_size == 0:
        return [], "No events yet."
    out = []
    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return out, None
    if not out:
        return [], "No events yet."
    # Keep last `limit`, most recent first
    return out[-limit:][::-1], None


def data_events(limit: int = 50):
    """Public wrapper for /api/data/events."""
    events, reason = _read_events_tail(limit=limit)
    return {
        "events": events,
        "count": len(events),
        "limit": limit,
        "reason": reason,
    }


# ---------- Stage 17→19: append a structured fix_order event to events.jsonl ----------

def _build_recommended_fix(warning_text: str, warning_source: str) -> str:
    """Heuristic that maps a warning context to a recommended fix string.

    Stage 19: simple keyword-based triage. This is a SUGGESTION only — Thor
    decides what to do in chat, gated by 'Thor, do it' or
    'Thor, execute pending order <order_id>'. No auto-execution ever.
    """
    wt = (warning_text or "").lower()
    src = (warning_source or "").lower()
    if "warning" in wt and "test-" in src:
        return f"delete the test fixture file at {warning_source or 'unknown'}"
    if ("no key" in wt) or ("missing" in wt) or ("not configured" in wt):
        return f"configure the missing dependency referenced in {warning_source or 'unknown'}"
    return f"investigate and resolve the issue: {warning_text}"


def _append_fix_order_event(payload: dict) -> dict:
    """Append one nofitech-event/v1 fix_order line to events.jsonl.

    Stage 19: event_type is now "fix_order" (an allowed value in
    00_company_os/event-schema.md). The event carries structured order
    fields (order_id, recommended_fix, requires_chat_confirmation,
    requested_by, etc.) so /api/data/orders can list them and the
    Pending Orders panel can render them.

    The button only WRITES an order; it does NOT execute anything. Per
    NOFI directive 2026-06-11, Thor acts only on chat confirmation.

    Returns a dict with ok / event_id / ts / order_id / status /
    requires_chat_confirmation / recommended_fix. The old (Stage 17)
    `ok` and `event_id` keys are preserved for backward compatibility.
    """
    warning_text = (payload.get("warning_text") or "").strip()
    if not warning_text:
        raise ValueError("warning_text is required")
    warning_id   = (payload.get("warning_id")   or "").strip()
    warning_src  = (payload.get("warning_source") or "").strip()
    warning_lvl  = (payload.get("warning_level")  or "warn").strip().lower()
    if warning_lvl not in ("warn", "error", "info"):
        warning_lvl = "warn"
    ts = datetime.now(timezone.utc).isoformat()
    order_id = f"order-{uuid.uuid4().hex[:8]}"
    short = uuid.uuid4().hex[:8]
    event_id = f"fix-order-{int(time.time())}-{short}"

    recommended_fix = _build_recommended_fix(warning_text, warning_src)
    title_text = warning_text[:80]
    source_file = warning_src or "00_company_os/events.jsonl"

    line = {
        "ts":            ts,
        "actor":         "nofi",
        "event_type":    "fix_order",
        "project":       "mission-control",
        "task_id":       "",
        "title":         f"FIX ORDER: {title_text}",
        "message": (
            f"{recommended_fix}. "
            f"(warning_id={warning_id}, level={warning_lvl}). "
            f"Awaiting chat confirmation: 'Thor, do it' or "
            f"'Thor, execute pending order {order_id}'. "
            f"NO auto-execution per NOFI directive 2026-06-11."
        ),
        "status":      "pending",
        "source_file": source_file,
        "schema":      "nofitech-event/v1",
        "order_id":    order_id,
        "recommended_fix": recommended_fix,
        "requires_chat_confirmation": True,
        "requested_by": "nofi",
        "chat_confirmation_phrase": "Thor, do it",
        "chat_confirmation_phrase_with_id": f"Thor, execute pending order {order_id}",
        "execution_locked_reason": "NOFI directive 2026-06-11: no auto-fix from dashboard buttons",
    }
    p = COMPANY_ROOT / "00_company_os" / "events.jsonl"
    # Append in a single open() so concurrent writers can't interleave a
    # half-line. No secrets are echoed; warning_text is a user-visible
    # warning message, not a key.
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return {
        "ok": True,
        "event_id": event_id,
        "ts": ts,
        "order_id": order_id,
        "status": "pending",
        "requires_chat_confirmation": True,
        "recommended_fix": recommended_fix,
    }


# ---------- Stage 19: list pending/in_progress fix_order events ----------

def data_orders() -> dict:
    """Read events.jsonl and return all fix_order events with
    status in (pending, in_progress). Newest first.

    Stage 20: also exclude any order_id that has ANY event
    whose status is in (cancelled, resolved) — so cancellation
    append-events (added by Forge/Thor) supersede the original
    pending entry without modifying the original on disk.
    Implemented as a two-pass scan: pass 1 collects superseded
    order_ids; pass 2 emits the visible (pending/in_progress)
    orders, skipping any whose order_id was superseded.

    Source: 00_company_os/events.jsonl (single source of truth).
    Open endpoint, no auth, no secrets logged. Tolerant of corrupt
    lines (skipped, never raises on bad JSON).
    """
    p = COMPANY_ROOT / "00_company_os" / "events.jsonl"
    orders = []
    superseded_ids = set()  # order_ids that have a cancelled/resolved event
    parsed_events = []      # all parsed fix_order events, for the second pass
    if p.exists():
        try:
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if not s:
                        continue
                    try:
                        ev = json.loads(s)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(ev, dict):
                        continue
                    if ev.get("event_type") != "fix_order":
                        continue
                    parsed_events.append(ev)
                    ev_status = (ev.get("status") or "").strip().lower()
                    ev_oid = ev.get("order_id")
                    # Pass 1: any fix_order with status in
                    # (cancelled, resolved) marks its order_id as superseded.
                    if ev_oid and ev_status in ("cancelled", "resolved"):
                        superseded_ids.add(ev_oid)
        except OSError:
            pass
    # Pass 2: emit pending/in_progress orders, skipping superseded ones.
    for ev in parsed_events:
        ev_status = (ev.get("status") or "").strip().lower()
        ev_oid = ev.get("order_id")
        if ev_status not in ("pending", "in_progress"):
            continue
        if ev_oid and ev_oid in superseded_ids:
            continue
        ev["rel"] = rel_time(ev.get("ts") or "")
        ev["source"] = ev.get("source_file") or ""
        orders.append(ev)
    # Newest first; fall back to ts lexicographic (ISO sorts correctly).
    orders.sort(key=lambda r: r.get("ts") or "", reverse=True)
    return {
        "orders": orders,
        "count": len(orders),
        "reason": None if orders else "no pending orders",
    }


# ---------- Stage 19: mark_order_status() — NO-OP stub ----------
# Intentionally NOT exposed via any HTTP endpoint in Stage 19.
# This stub exists so future code (Stage 20+) can mark orders as
# in_progress / resolved / cancelled without rewiring the call site.
# The button does NOT call it. Per NOFI directive 2026-06-11, the
# only way an order changes status is via chat confirmation.
def mark_order_status(order_id: str, new_status: str, actor: str = "thor") -> dict:
    """Stage 19 stub. Returns a sentinel; does NOT mutate events.jsonl."""
    return {
        "ok": False,
        "noop": True,
        "reason": "mark_order_status is a Stage 19 no-op stub; status changes require chat confirmation",
        "order_id": order_id,
        "new_status": new_status,
        "actor": actor,
    }


def data_projects():
    """All projects in 01_projects/."""
    rows = []
    for proj_dir in sorted((COMPANY_ROOT / "01_projects").iterdir()):
        if not proj_dir.is_dir() or proj_dir.name.startswith("."):
            continue
        status_path = proj_dir / "status.md"
        charter_path = proj_dir / "charter.md"
        txt = safe_read(status_path) if status_path.exists() else None
        if txt:
            meta, body = parse_frontmatter(txt)
        else:
            meta, body = {}, ""
        rows.append({
            "name": proj_dir.name,
            "phase": meta.get("phase") or "—",
            "status": meta.get("status") or "—",
            "progress_pct": meta.get("progress_pct") or "—",
            "next_action": meta.get("next_action") or "—",
            "approval_needed": (meta.get("approval_needed") or "false").lower() == "true",
            "blocker": meta.get("blocker") or "",
            "charter_exists": charter_path.exists(),
            "status_exists": status_path.exists(),
            "data_source": meta.get("data_source") or "—",
            "updated": meta.get("updated") or "—",
            "path": str(proj_dir.relative_to(COMPANY_ROOT)),
        })
    sources = set()
    for r in rows:
        if r.get("data_source") and r["data_source"] != "—":
            sources.add(r["data_source"])
    return {
        "projects": rows,
        "count": len(rows),
        "data_sources": sorted(sources) if sources else [],
        "reason": None if rows else "no projects yet",
    }


def _check_port_open(host, port, timeout=0.3):
    """Quick non-blocking check whether a TCP port is open on host.
    Returns True/False. Does not send any data."""
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _dns_resolves(host, timeout=0.5):
    """Quick check whether a hostname resolves via /etc/hosts or DNS.
    Does not make an HTTP request."""
    import socket
    try:
        socket.getaddrinfo(host, None, socket.AF_INET)
        return True
    except Exception:
        return False


def data_provider():
    """2 rows: free (Hermes proxy) + paid (Minimax).
    Connection status is determined by CHEAP, HONEST signals:
      - Free: is port 8768 bound on localhost?
      - Paid: is .env present + key set + DNS resolves for api.minimax.io?
    NO live LLM calls. NO fake 'Connected' state.
    Never echoes the API key."""
    env_path = COMPANY_ROOT / ".config" / "nofitech" / ".env"
    env_exists = env_path.exists()

    key_set = False
    free_model = "nvidia/nemotron-3-ultra:free"
    paid_model = "minimax/minimax-m3"
    if env_exists:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip()
            if k == "NOFITECH_LLM_API_KEY" and v:
                key_set = True
            elif k == "NOFITECH_LLM_MODEL_FREE":
                free_model = v
            elif k == "NOFITECH_LLM_MODEL_PAID":
                paid_model = v

    # Last successful/failed check from agent logs (existing logic, kept)
    logs_root = COMPANY_ROOT / "00_company_os" / "04_agents" / "logs"
    last_ok = None
    last_fail = None
    if logs_root.is_dir():
        for f in sorted(logs_root.rglob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
            txt = safe_read(f)
            if not txt:
                continue
            if last_ok is None and "model:" in txt and "error" not in txt.lower()[:200]:
                m = re.search(r"model:\s*(\S+)", txt)
                if m:
                    last_ok = {
                        "model": m.group(1),
                        "at": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
                    }
            if last_fail is None and re.search(r"\b(LLM call failed|primary failed|error)\b", txt, re.IGNORECASE):
                last_fail = {
                    "at": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
                    "source": str(f.relative_to(COMPANY_ROOT)),
                }
            if last_ok and last_fail:
                break

    # FREE slot: Hermes proxy on 127.0.0.1:8768
    free_port_open = _check_port_open("127.0.0.1", 8768)
    if free_port_open:
        free_conn = "Unknown"  # port open but we haven't called it
        free_conn_detail = "port 8768 open; live call not performed"
    else:
        free_conn = "Not connected"
        free_conn_detail = "port 8768 not bound (Hermes proxy not running)"

    # PAID slot: Minimax direct endpoint
    paid_dns = _dns_resolves("api.minimax.io")
    if not env_exists:
        paid_conn = "Not configured"
        paid_conn_detail = ".env missing at .config/nofitech/.env"
    elif not key_set:
        paid_conn = "Not configured"
        paid_conn_detail = "NOFITECH_LLM_API_KEY not set in .env"
    elif not paid_dns:
        paid_conn = "Unreachable"
        paid_conn_detail = "DNS resolution for api.minimax.io failed"
    else:
        paid_conn = "Unknown"  # key + DNS ok, but no live call
        paid_conn_detail = "key set + DNS resolves; live call not performed"

    rows = [
        {
            "slot": "free",
            "provider": "Nous (Hermes proxy)",
            "model": free_model,
            "endpoint": "http://127.0.0.1:8768/v1/chat/completions",
            "key_configured": free_port_open,  # HONEST: only true if port is open
            "connection_status": free_conn,
            "connection_detail": free_conn_detail,
            "last_ok": last_ok,
            "last_fail": last_fail,
        },
        {
            "slot": "paid",
            "provider": "Minimax (Anthropic-compat)",
            "model": paid_model,
            "endpoint": "https://api.minimax.io/anthropic/v1/messages",
            "key_configured": key_set,
            "connection_status": paid_conn,
            "connection_detail": paid_conn_detail,
            "last_ok": None,
            "last_fail": None,
        },
    ]
    return {"providers": rows, "count": len(rows)}


# ---- env status (no secret values exposed) ----
# Mapping from internal env-var name → safe public display name.
# The env-var name is NOT exposed in the API response. Only the safe label.
_ENV_DISPLAY = {
    "NOFITECH_LLM_API_KEY":     "LLM API key",
    "NOFITECH_LLM_MODEL_FREE":  "LLM model (free)",
    "NOFITECH_LLM_MODEL_PAID":  "LLM model (paid)",
}


def _env_status():
    """Return env var status without ever exposing the value OR the raw var name.
    Status is one of: 'configured' | 'missing' | 'unknown'.
    Keys returned are safe display labels; the underlying env-var name never appears
    in HTTP responses (avoids trivial grep hits on common secret-var names).
    """
    env_path = COMPANY_ROOT / ".config" / "nofitech" / ".env"
    out = {}
    for var, label in _ENV_DISPLAY.items():
        v = None
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                kk, _, vv = line.partition("=")
                if kk.strip() == var:
                    v = vv.strip()
                    break
        out[label] = "configured" if v else "missing"   # NEVER the value, NEVER the var name
    # Also: is the env file itself present at all? (boolean only)
    out["__env_file_present__"] = env_path.exists()
    return out


def data_logs():
    """Last 20 log events + health + env summary.
    Stage 9: real level detection, last_verification, env status (no values),
    app/api health booleans + reasons.
    Stage 18: single source of truth for warnings/errors. The warnings count
    and the warnings panel both read from `warnings_list` / `errors_list`
    (unbounded, every warn/error entry). The `events` array now contains
    ALL warn + ALL error + the 20 most recent info entries (sorted by ts desc)
    so the recent-activity view still surfaces them too.
    """
    warnings_list = []   # ALL warn-level entries, no cap
    errors_list = []     # ALL error-level entries, no cap
    info_list = []       # ALL info-level entries, capped to 20 most recent below
    roots = [COMPANY_ROOT / "00_company_os" / "04_agents" / "logs"]
    for proj in (COMPANY_ROOT / "01_projects").glob("*/logs"):
        roots.append(proj)

    last_verification = None  # newest argus-*.md mtime
    last_verification_source = None
    for r in roots:
        if not r.is_dir():
            continue
        for f in r.rglob("*.md"):
            txt = safe_read(f)
            if not txt:
                continue
            meta, body = parse_frontmatter(txt)

            # Strict level detection (Stage 12) — ONLY explicit `level:` in frontmatter.
            # No body-inference, no filename-inference. If a log has no `level:` field,
            # it is treated as `info`. This is the rule visible to the user.
            level = (meta.get("level") or "").strip().lower()
            if level not in ("error", "warn", "info"):
                level = "info"  # default to info, not error

            entry = {
                "ts": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
                "rel": rel_time(f.stat().st_mtime),
                "source": str(f.relative_to(COMPANY_ROOT)),
                "officer": (meta.get("officer") or meta.get("agent") or (f.stem.split("-")[0] if "-" in f.stem else None)),
                "level": level,
                "title": meta.get("title") or f.stem,
            }

            if level == "error":
                errors_list.append(entry)
            elif level == "warn":
                warnings_list.append(entry)
            else:
                info_list.append(entry)

            # Track last verification (argus-*.md)
            if f.stem.startswith("argus-") and (last_verification is None or f.stat().st_mtime > last_verification):
                last_verification = f.stat().st_mtime
                last_verification_source = str(f.relative_to(COMPANY_ROOT))

    # Sort all three lists by ts desc
    warnings_list.sort(key=lambda e: e["ts"], reverse=True)
    errors_list.sort(key=lambda e: e["ts"], reverse=True)
    info_list.sort(key=lambda e: e["ts"], reverse=True)

    # Counts derived from the unbounded lists
    errors = len(errors_list)
    warnings = len(warnings_list)

    # Final events array: ALL warnings + ALL errors + 20 most recent infos,
    # sorted by ts desc. This guarantees the warn/error entries never get
    # pushed out of view by a flood of newer info entries.
    events = warnings_list + errors_list + info_list[:20]
    events.sort(key=lambda e: e["ts"], reverse=True)

    # Stage 14: merge events.jsonl into the Logs/Health panel. The last 20
    # entries from 00_company_os/events.jsonl surface alongside the log-file
    # events so the user sees the full activity stream in one place.
    jsonl_events, jsonl_reason = _read_events_tail(limit=20)
    # jsonl_events is already most-recent-first; UI sorts by ts desc which
    # is the same direction, so we just pass it through.

    # App health: derived from errors count
    if errors > 0:
        app_health = "degraded"
        app_health_reason = f"{errors} error event(s) in log"
    elif warnings > 0:
        app_health = "degraded"
        app_health_reason = f"{warnings} warning(s) in log"
    else:
        app_health = "ok"
        app_health_reason = None

    # API health: simple — server is responding means API health is ok
    api_health = "ok"  # we are responding, so the server itself is healthy
    api_health_reason = None

    return {
        "events": events,
        "count": len(events),
        "errors": errors,
        "warnings": warnings,
        "info_count": sum(1 for e in events if e["level"] == "info"),
        # Stage 18: unbounded, every warn/error entry — single source of truth
        # for the Warnings panel and the warnings count.
        "warnings_list": warnings_list,
        "errors_list": errors_list,
        "app_health": app_health,
        "app_health_reason": app_health_reason,
        "api_health": api_health,
        "api_health_reason": api_health_reason,
        "last_verification": datetime.fromtimestamp(last_verification, tz=timezone.utc).isoformat() if last_verification else None,
        "last_verification_rel": rel_time(last_verification) if last_verification else "—",
        "last_verification_source": last_verification_source,
        "env": _env_status(),
        # Stage 14: events.jsonl surface area
        "jsonl_events": jsonl_events,
        "jsonl_count": len(jsonl_events),
        "jsonl_reason": jsonl_reason,
    }


# ---------- MC-KANBAN-1: Kanban tab endpoints (added 2026-06-16) ----------

def data_kanban(include_archived: bool = False) -> dict:
    """GET /api/data/kanban — full board grouped by 6 columns, with 3-agent
    swimlanes inside Running. Reads project task files via kanban_parser.
    No external kanban.db; no pip deps. Additive to the existing endpoints."""
    board = kanban_parser.build_board(COMPANY_ROOT, include_archived=include_archived)
    board["last_updated"] = datetime.now(timezone.utc).isoformat()
    board["errors"] = []
    return board


def get_kanban_task_result(task_id: str) -> tuple[int, dict]:
    """MC-KANBAN-5 (2026-06-17): GET /api/data/kanban/task/:id/result — return
    the full "## Result" section body for the kanban modal popup, plus the
    parsed metadata (date/by/status). Returns 404 if the task or its Result
    section is not found. The body is the raw markdown text AFTER the header
    block (`**Date:**/By/Status` lines) and AFTER the `---` separator, so the
    frontend can render it as markdown directly.
    """
    task_id = (task_id or "").strip()
    if not task_id:
        return 400, {"error": "task_id is required"}

    # Locate the task file using the same logic as the parser
    found_path = None
    for proj_dir in (COMPANY_ROOT / "01_projects").iterdir():
        if not proj_dir.is_dir():
            continue
        candidate = proj_dir / "tasks" / f"{task_id}.md"
        if candidate.is_file():
            found_path = candidate
            break
    if not found_path:
        # also try 00_company_os
        co = COMPANY_ROOT / "00_company_os"
        if co.is_dir():
            for sub in co.iterdir():
                candidate = sub / "tasks" / f"{task_id}.md"
                if candidate.is_file():
                    found_path = candidate
                    break
    if not found_path:
        return 404, {"error": f"task file not found: {task_id}"}

    try:
        text = found_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return 500, {"error": f"read failed: {e}"}

    # Extract the body and locate the ## Result section
    if not text.startswith("---\n"):
        return 404, {"error": f"task has no frontmatter: {task_id}"}
    end = text.find("\n---\n", 4)
    if end < 0:
        return 404, {"error": f"task has malformed frontmatter: {task_id}"}
    body = text[end + 5:]

    # Use the parser's extractor for metadata
    teaser, metadata = kanban_parser._extract_result_section(body)
    if teaser is None and not metadata:
        return 404, {"error": f"task has no Result section: {task_id}"}

    # Slice the result body out (between the header block and the closing ---)
    # so the modal can render the markdown verbatim.
    import re as _re
    header_re = _re.compile(r"^##\s+Result\s*$\n", _re.MULTILINE)
    m = header_re.search(body)
    if not m:
        return 404, {"error": f"task has no Result section: {task_id}"}
    rest = body[m.end():]
    next_h = _re.search(r"^##\s+", rest, _re.MULTILINE)
    section = rest if not next_h else rest[: next_h.start()]
    # Strip the **Date:**/**By:**/**Status:** header lines + the closing ---
    body_lines = []
    for line in section.splitlines():
        s = line.strip()
        if s.startswith("**Date:**") or s.startswith("**By:**") or s.startswith("**Status:**"):
            continue
        body_lines.append(line)
    # Drop trailing "---" line if present
    while body_lines and body_lines[-1].strip() == "---":
        body_lines.pop()
    # Drop leading blank lines
    while body_lines and not body_lines[0].strip():
        body_lines.pop(0)
    # Drop trailing blank lines
    while body_lines and not body_lines[-1].strip():
        body_lines.pop()
    full_body = "\n".join(body_lines).strip()

    # MC-RESULT-IMAGES-1 (2026-06-22): scan the result body for image/video
    # filenames (png/jpg/jpeg/gif/webp/svg/mp4/webm, case-insensitive) and
    # resolve each one to a real file on disk under COMPANY_ROOT. Return the
    # resolved list as `assets` so the kanban modal can render thumbnails.
    # Resolution order, per spec:
    #   1. 01_projects/<project>/           (frontmatter project)
    #   2. 01_projects/<project>/results/   (frontmatter project)
    #   3. any 01_projects/*/results/       (fallback for cross-project tasks)
    #   4. COMPANY_ROOT directly            (bare filename)
    assets = _scan_result_assets(full_body, task_id, found_path)

    return 200, {
        "task_id": task_id,
        "title": "",  # caller already has it from the kanban card
        "metadata": metadata or {},
        "teaser": teaser,
        "body": full_body,
        "assets": assets,
    }


# Asset extensions considered "images or videos" for the result gallery.
_ASSET_EXTS = ("png", "jpg", "jpeg", "gif", "webp", "svg", "mp4", "webm")
# Match filenames inside the result body text. Allow word chars, dots, slashes,
# and hyphens so paths like "results/foo.png" or "01_projects/x/y.png" work.
_ASSET_RE = re.compile(
    r"\b[\w./\-]+\.(?:" + "|".join(_ASSET_EXTS) + r")\b",
    re.IGNORECASE,
)
# Cap per task to keep the payload + UI lean.
_MAX_ASSETS_PER_TASK = 24
# 25 MiB hard cap per individual asset (matches spec for /api/file).
_MAX_ASSET_BYTES = 25 * 1024 * 1024


def _scan_result_assets(body: str, task_id: str, task_path: Path) -> list[dict]:
    """MC-RESULT-IMAGES-1: extract resolved image/video assets from a result
    body. Returns a list of {name, rel_path, url, type, size_bytes, ext}
    objects, deduped by rel_path and capped at _MAX_ASSETS_PER_TASK.

    Tolerant to frontmatter `project:` being wrong or pointing to a project
    other than where the deliverables actually live: we also scan ALL
    `01_projects/*/results/` directories as a fallback. This handles the
    common case where a task created in `mission-control` writes assets to
    another project's results dir (e.g. `diy-hub-v1/results/`).
    """
    if not body:
        return []
    seen_rel: set[str] = set()
    assets: list[dict] = []

    # Read the frontmatter project (best-effort) for the preferred lookup dirs.
    fm_project = None
    try:
        text = task_path.read_text(encoding="utf-8", errors="replace")
        if text.startswith("---\n"):
            end = text.find("\n---\n", 4)
            if end > 0:
                fm = text[4:end]
                m = re.search(r"^project:\s*([^\s#]+)", fm, re.MULTILINE)
                if m:
                    fm_project = m.group(1).strip().strip("'\"")
    except Exception:
        fm_project = None

    # Build the ordered list of candidate search roots.
    search_roots: list[Path] = []
    projects_root = COMPANY_ROOT / "01_projects"
    if fm_project:
        # 1+2: frontmatter project dir + its results subdir
        search_roots.append(projects_root / fm_project)
        search_roots.append(projects_root / fm_project / "results")
    # 3: any project results dir (fallback for cross-project tasks)
    if projects_root.is_dir():
        for results_dir in sorted(projects_root.glob("*/results")):
            if results_dir not in search_roots:
                search_roots.append(results_dir)
        # And the bare project dirs as a deeper fallback
        for proj_dir in sorted(projects_root.iterdir()):
            if proj_dir.is_dir() and proj_dir not in search_roots:
                search_roots.append(proj_dir)
    # 4: COMPANY_ROOT directly (bare filename)
    search_roots.append(COMPANY_ROOT)

    # Find candidate filenames in the body text.
    candidates: list[str] = []
    for match in _ASSET_RE.finditer(body):
        # Skip pure .svg used as inline decoration markers? We accept them —
        # they're real files on disk.
        filename = match.group(0)
        # Normalize: strip a leading "./" if any
        if filename.startswith("./"):
            filename = filename[2:]
        candidates.append(filename)

    # Companion-asset expansion: if the body mentions `foo.svg + .png` (a
    # common shorthand), the `.png` will not match the regex on its own.
    # For every candidate we found, also try the same basename with each
    # other asset extension. This is bounded by _MAX_ASSETS_PER_TASK.
    expanded: list[str] = []
    for filename in candidates:
        expanded.append(filename)
        stem, dot, ext = filename.rpartition(".")
        if not dot:
            continue
        ext_lc = ext.lower()
        if ext_lc in _ASSET_EXTS:
            for sibling_ext in _ASSET_EXTS:
                if sibling_ext == ext_lc:
                    continue
                expanded.append(f"{stem}.{sibling_ext}")

    for filename in expanded:
        if len(assets) >= _MAX_ASSETS_PER_TASK:
            break
        # Resolve: try each search root
        resolved: Path | None = None
        for root in search_roots:
            if not root.is_dir():
                continue
            cand = (root / filename).resolve()
            try:
                # Security: must remain under COMPANY_ROOT
                if not _is_under_company_root(cand):
                    continue
            except Exception:
                continue
            if not cand.is_file():
                continue
            try:
                if cand.is_symlink():
                    # Resolve symlink target — refuse symlinks-to-dirs.
                    target = cand.resolve()
                    if not target.is_file():
                        continue
            except Exception:
                continue
            # Check size cap
            try:
                size = cand.stat().st_size
            except Exception:
                continue
            if size > _MAX_ASSET_BYTES:
                continue
            resolved = cand
            break

        if resolved is None:
            continue

        rel_path = str(resolved.relative_to(COMPANY_ROOT))
        if rel_path in seen_rel:
            continue
        seen_rel.add(rel_path)

        ext = resolved.suffix.lstrip(".").lower()
        kind = "video" if ext in ("mp4", "webm") else "image"
        url = "/api/file?path=" + urllib.parse.quote(rel_path, safe="/")
        try:
            size_bytes = resolved.stat().st_size
        except Exception:
            size_bytes = 0
        assets.append({
            "name": resolved.name,
            "rel_path": rel_path,
            "url": url,
            "type": kind,
            "size_bytes": size_bytes,
            "ext": ext,
        })

    return assets


def _is_under_company_root(p: Path) -> bool:
    """True iff Path p resolves to a location under COMPANY_ROOT."""
    try:
        root = COMPANY_ROOT.resolve()
        target = p.resolve()
        # Python 3.9+ has is_relative_to; for broader stdlib compat, compare
        # using commonpath.
        import os as _os
        return _os.path.commonpath([str(root), str(target)]) == str(root)
    except Exception:
        return False




def _emit_live_task_node(task_id: str, new_status: str,
                        project: str | None = None,
                        label: str | None = None) -> None:
    """MC-LIVE-MEMORY-GRAPH-1 (2026-06-19): live auto-emit from
    kanban/agent/event hot paths. Idempotent on `id`. Never raises.
    """
    try:
        from memory_graph_global import get_global_store, init_global_store
        try:
            store = get_global_store()
        except RuntimeError:
            store = init_global_store()
        tid_safe = re.sub(r"[^A-Za-z0-9._\-]+", "-", (task_id or "").strip())
        if not tid_safe:
            return
        proj_safe = re.sub(r"[^A-Za-z0-9._\-]+", "-", (project or "mission-control").strip()) or "mission-control"
        nid = f"task:{tid_safe}"
        store.add_node({
            "id": nid,
            "kind": "task",
            "label": (label or task_id)[:200],
            "summary": f"Kanban task {task_id} → {new_status}",
            "importance": 0.7,
            "confidence": 0.9,
            "status": str(new_status or "active"),
            "tags": ["kanban", "task", new_status or "active"],
            "source": "serve.py:live_emit",
            "project": proj_safe,
        })
        # Edge: task belongs to project
        store.add_edge({
            "id": f"edge-project:{proj_safe}-{nid}-contains",
            "source": f"project:{proj_safe}",
            "target": nid,
            "kind": "contains",
            "weight": 0.7,
            "metadata": {"via": "live_emit", "status": new_status},
        })
        # Audit event
        store.add_event(
            event_type="kanban.status_change",
            actor="serve.py",
            task_id=task_id,
            project=proj_safe,
            agent=None,
            source="serve.py:patch_kanban_task",
            payload={"new_status": str(new_status), "label": label},
        )
    except Exception:
        # never break the user-facing op
        pass


def patch_kanban_task(task_id: str, new_status: str) -> tuple[int, dict]:
    """PATCH /api/data/kanban/task/:id — update task's `kanban_status` on disk.

    MC-KANBAN-2: writes to `kanban_status` (a separate field), NOT to `status`.
    The project-native `status` field is preserved exactly. Detects the file
    format (YAML frontmatter vs markdown table) and routes to the correct
    mutator. For Format B (markdown table), inserts/updates a
    `| **kanban_status** | <new> |` row right after the `| **status** | ... |`
    row, leaving all other rows untouched.

    Returns (http_status, body_dict). The body is a full updated board on
    success, an error dict on failure."""
    task_id = (task_id or "").strip()
    new_status = (new_status or "").strip().lower()
    if not task_id:
        return 400, {"error": "task_id is required", "ok": False}
    if new_status not in kanban_parser.ALLOWED_STATUSES:
        return 400, {
            "error": f"unknown status: {new_status!r}",
            "allowed": list(kanban_parser.ALLOWED_STATUSES),
            "ok": False,
        }
    ok, reason, path = kanban_parser.update_task_status(task_id, new_status, COMPANY_ROOT)
    if not ok:
        # 404 only for "not found"; 400 for any other write failure
        if "not found" in reason:
            return 404, {"error": reason, "ok": False, "task_id": task_id}
        return 400, {"error": reason, "ok": False}
    board = data_kanban(include_archived=False)
    # MC-MEMORY-GRAPH-1 (2026-06-17): event bridge — emit node.upsert for
    # every status change. Best-effort.
    try:
        emit_kanban_memory_event(task_id, new_status)
    except Exception as _mg_emit_err:
        # Never let memory graph errors break the kanban op
        pass
    # MC-LIVE-MEMORY-GRAPH-1 (2026-06-19): direct live emit to the global
    # store (no event-bridge hop). Surfaces in the graph within ~1s.
    _emit_live_task_node(task_id, new_status, project="mission-control")
    return 200, {
        "ok": True,
        "task_id": task_id,
        "new_status": new_status,
        "path": str(path.relative_to(COMPANY_ROOT)) if path else None,
        "reason": reason,
        "board": board,
    }


def assign_kanban_task(task_id: str, payload: dict) -> tuple[int, dict]:
    """PATCH /api/data/kanban/task/:id/assign — update task's `assigned_to`
    (Format A YAML) or `owner` row (Format B markdown table) on disk.

    MC-KANBAN-ASSIGN-1 (2026-06-17): supports 4 values — thor, forge, argus,
    or "" (unassign). Empty string removes the field (Format A) or the row
    (Format B). Preserves every other line in the file exactly. Returns
    (http_status, body_dict) with the full updated board on success.
    """
    import pathlib  # local; cheap
    task_id = (task_id or "").strip()
    if not task_id:
        return 400, {"error": "task_id is required", "ok": False}
    new_assignee = (payload.get("assignee") or "").strip().lower()
    if new_assignee not in {"thor", "forge", "argus", ""}:
        return 400, {
            "error": f"unknown assignee: {new_assignee!r}; must be thor, forge, argus, or empty (unassign)",
            "ok": False,
            "task_id": task_id,
        }

    # Find the task file (reuse the same matching strategy as
    # kanban_parser.update_task_status: stem, exact filename, or frontmatter
    # task_id / Format B id row).
    target: pathlib.Path | None = None
    company_root = pathlib.Path(COMPANY_ROOT)
    for root in (company_root / "01_projects", company_root / "00_company_os"):
        if not root.is_dir():
            continue
        for td in root.glob("*/tasks"):
            if not td.is_dir():
                continue
            for tf in sorted(td.glob("*.md")):
                if tf.stem == task_id or tf.name == f"{task_id}.md":
                    target = tf
                    break
                # also match by Format A frontmatter task_id or Format B id
                try:
                    txt = tf.read_text(encoding="utf-8")
                except Exception:
                    continue
                meta, _ = kanban_parser.parse_frontmatter(txt)
                if (meta.get("task_id") or "").strip() == task_id:
                    target = tf
                    break
                table, _ = kanban_parser.parse_markdown_table(txt)
                if (table.get("id") or "").strip() == task_id:
                    target = tf
                    break
            if target is not None:
                break
        if target is not None:
            break
    if target is None:
        return 404, {"error": f"task_id not found: {task_id!r}", "ok": False, "task_id": task_id}

    # Re-detect format
    txt = target.read_text(encoding="utf-8")
    fmt = kanban_parser.detect_format(txt)

    # ---- Apply the assign update ----
    if fmt == "A":
        # Format A: YAML frontmatter. Update or insert `assigned_to: <value>`
        # right after `task_id:`. If empty, REMOVE the `assigned_to:` line.
        lines = txt.splitlines()
        # find frontmatter bounds
        if not lines or lines[0].strip() != "---":
            return 400, {"error": "Format A file is missing leading `---`", "ok": False, "task_id": task_id}
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_idx = i
                break
        if end_idx is None:
            return 400, {"error": "Format A file is missing closing `---`", "ok": False, "task_id": task_id}
        header = lines[1:end_idx]
        body = lines[end_idx + 1:]

        assigned_to_re = re.compile(r"^(\s*assigned_to\s*:\s*)(.*?)(\s*(?:#.*)?)$")
        task_id_re = re.compile(r"^(\s*task_id\s*:\s*)(.*?)(\s*(?:#.*)?)$")

        if new_assignee:
            new_header = []
            replaced = False
            for line in header:
                m = assigned_to_re.match(line)
                if m:
                    new_header.append(f"{m.group(1)}{new_assignee}{m.group(3)}")
                    replaced = True
                else:
                    new_header.append(line)
            if not replaced:
                # insert after task_id: (or at end of header if not found)
                new_header2 = []
                inserted = False
                for line in new_header:
                    new_header2.append(line)
                    if (not inserted) and task_id_re.match(line):
                        new_header2.append(f"assigned_to: {new_assignee}")
                        inserted = True
                if not inserted:
                    new_header2.append(f"assigned_to: {new_assignee}")
                new_header = new_header2
        else:
            # Unassign: remove the `assigned_to:` line entirely (preserve blank lines around it)
            new_header = [ln for ln in header if not assigned_to_re.match(ln)]

        out = "---\n" + "\n".join(new_header) + "\n---\n" + "\n".join(body)
        if not out.endswith("\n"):
            out += "\n"
        target.write_text(out, encoding="utf-8")

    elif fmt == "B":
        # Format B: markdown `| **field** | value |` table. Update or insert
        # the `| **owner** | <value> |` row. If empty, REMOVE the row entirely.
        lines = txt.splitlines()
        header_idx = None
        for i, line in enumerate(lines):
            if kanban_parser._TABLE_HEADER_RE.match(line):
                header_idx = i
                break
        if header_idx is None:
            return 400, {"error": "Format B table header not found", "ok": False, "task_id": task_id}
        data_start = header_idx + 1
        if data_start < len(lines) and kanban_parser._TABLE_SEP_RE.match(lines[data_start]):
            data_start += 1

        row_kv_re = kanban_parser._TABLE_ROW_KV_RE
        owner_row_idx = None
        id_row_idx = None
        for j in range(data_start, len(lines)):
            ln = lines[j]
            if not ln.lstrip().startswith("|"):
                break
            m = row_kv_re.match(ln)
            if not m:
                break
            raw_key = m.group("key").strip()
            if raw_key.startswith("**") and raw_key.endswith("**") and len(raw_key) >= 4:
                key = raw_key[2:-2].strip().lower()
            else:
                key = raw_key.strip().lower()
            if key == "owner":
                owner_row_idx = j
            elif key == "id":
                id_row_idx = j

        if new_assignee:
            if owner_row_idx is not None:
                # update existing row, preserve exact key rendering
                ln = lines[owner_row_idx]
                m = row_kv_re.match(ln)
                raw_key = m.group("key").strip()
                lines[owner_row_idx] = f"| {raw_key} | {new_assignee} |"
            else:
                # insert new owner row after the id row (or as first data row)
                insert_at = (id_row_idx + 1) if id_row_idx is not None else data_start
                lines.insert(insert_at, f"| **owner** | {new_assignee} |")
        else:
            # Unassign: remove the owner row entirely
            if owner_row_idx is not None:
                lines.pop(owner_row_idx)

        out = "\n".join(lines)
        if not out.endswith("\n"):
            out += "\n"
        target.write_text(out, encoding="utf-8")

    else:
        return 400, {
            "error": f"task file is not in a recognized format (A or B): {target.name}",
            "ok": False,
            "task_id": task_id,
        }

    board = data_kanban(include_archived=False)
    return 200, {
        "ok": True,
        "task_id": task_id,
        "assignee": new_assignee,
        "path": str(target.relative_to(COMPANY_ROOT)),
        "board": board,
    }


def create_kanban_task(payload: dict) -> tuple[int, dict]:
    """POST /api/data/kanban/task — create a new task file from the Kanban UI.

    Body: { title, assignee, priority }
    Writes to 01_projects/mission-control/tasks/<TASK_ID>.md (existing convention
    — keeps everything in one project tree). Returns 201 on success."""
    title = (payload.get("title") or "").strip()
    assignee = (payload.get("assignee") or "").strip().lower()
    priority = (payload.get("priority") or "normal").strip().lower()
    if not title:
        return 400, {"error": "title is required", "ok": False}
    if assignee not in kanban_parser.AGENT_IDS:
        return 400, {
            "error": f"unknown assignee: {assignee!r}",
            "allowed": kanban_parser.AGENT_IDS,
            "ok": False,
        }
    # TASK_ID format per spec: "MC-KANBAN-CREATE-<timestamp>" or "MC-<random>"
    import secrets
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    rand = secrets.token_hex(3).upper()
    task_id = f"MC-KANBAN-CREATE-{ts}-{rand}"
    ok, reason, path = kanban_parser.create_task_file(
        task_id, title, assignee, priority, COMPANY_ROOT
    )
    if not ok:
        return 400, {"error": reason, "ok": False, "task_id": task_id}
    board = data_kanban(include_archived=False)
    # Return the new card so the UI can optimistically insert it
    new_card = None
    for col in board.get("columns", []):
        for t in col.get("tasks", []):
            if t.get("task_id") == task_id:
                new_card = t
                break
        if new_card:
            break
    # MC-MEMORY-GRAPH-1 (2026-06-17): event bridge — emit node.upsert when
    # a new task is created. Best-effort.
    try:
        emit_kanban_memory_event(task_id, "triage")
    except Exception:
        pass
    # MC-LIVE-MEMORY-GRAPH-1 (2026-06-19): direct live emit.
    _emit_live_task_node(task_id, "triage", project="mission-control", label=title)
    return 201, {
        "ok": True,
        "task_id": task_id,
        "path": str(path.relative_to(COMPANY_ROOT)) if path else None,
        "card": new_card,
        "board": board,
    }


# ---------- MC-MEMORY-GRAPH-1 (2026-06-17): Memory Graph page integration ----------
# Locked stack: Python stdlib only (no pip deps), JSON on disk (no SQLite for v1),
# 5s polling on the frontend (no SSE/WebSocket). This block adds the
# redactor, snapshot persistence, event-log append, and the ingest helper
# that turns an event dict into a mutated graph + log line. Routes are
# wired in the Handler class below (do_GET, do_POST, do_DELETE).


# --- MC-MEMORY-GRAPH-3A-BACKEND: redactor + memory storage + ingest
# have moved to dedicated modules. We import them here so the rest of
# serve.py stays the same shape it was before.
from security import redact_secrets, is_authorized, auth_required_error  # noqa: E402
import memory_graph_store as _mg_store  # noqa: E402
import memory_graph_api as _mg_api  # noqa: E402
from memory_graph_store import init_store as _mg_init_store  # noqa: E402
# MC-MEMORY-GRAPH-4-GLOBAL: global memory graph store + importer.
from memory_graph_global import init_global_store  # noqa: E402
from memory_graph_import import MemoryGraphImporter  # noqa: E402

# Backwards-compat alias: kanban_service still calls this name.
emit_kanban_memory_event = _mg_api.emit_kanban_memory_event

# On import, open the SQLite store (and migrate from JSON if needed).
_mg_init_store(MG_DATA_DIR)

# MC-MEMORY-GRAPH-4-GLOBAL: open the GLOBAL store at the canonical
# company path and run an incremental import on startup. We never
# fail the boot on import errors — the legacy MC store is still
# there as a fallback.
try:
    init_global_store()
    try:
        _imp = MemoryGraphImporter()
        _imp_stats = _imp.incremental()
        print(f"[mc] global memory graph import: { _imp_stats.get('nodes_upserted', 0) } nodes, "
              f"{ _imp_stats.get('edges_upserted', 0) } edges "
              f"({ _imp_stats.get('files_ingested', 0) } files ingested)",
              flush=True)
    except Exception as _e_imp:
        print(f"[mc] global memory graph import skipped: { _e_imp }", flush=True)
except Exception as _e_glob:
    print(f"[mc] global memory store init failed: { _e_glob }", flush=True)

# ---------- HTTP ----------

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # quiet
        pass

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path):
        full = HERE / path.lstrip("/")
        if not full.is_file():
            self.send_response(404)
            self.end_headers()
            return
        if full.suffix == ".html":
            ctype = "text/html; charset=utf-8"
        else:
            ctype = "application/octet-stream"
        body = full.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        # MC-KANBAN-BUGFIX-2 (2026-06-16): prevent browser from caching the
        # static HTML/JS — NOFI was seeing stale pages that didn't include
        # the prior fix. no-store forces a fresh fetch on every page load.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_company_file(self, rel_path: str):
        """MC-RESULT-IMAGES-1 (2026-06-22): GET /api/file?path=<rel-path>

        File server for assets referenced by kanban task results (logos,
        screenshots, generated images, demo videos). Two access tiers:

        AUTHENTICATED (anywhere): if the request carries a valid admin token
        (same gate as PATCH endpoints), we serve any regular file under
        COMPANY_ROOT that passes the path-traversal / size / symlink checks.
        Use case: agent logs, source files, internal assets.

        PUBLIC (image/video only, restricted dirs): if NO token is provided
        (or the token is invalid), we still serve the file BUT only when ALL
        of the following are true:
          - File extension is in a hard-coded image/video MIME whitelist
            (png, jpg, jpeg, gif, webp, svg, avif, bmp, ico, mp4, webm, mov)
          - Path is under 01_projects/<project>/results/ OR
                  01_projects/<project>/public/  OR
                  01_projects/<project>/assets/
            (other dirs like /code/ or /tasks/ stay gated)
          - File is <= 25 MiB and is a regular file (not a dir/symlink)
          - Resolved path is contained within COMPANY_ROOT (no traversal)

        Why this design: <img src> tags in the result modal CANNOT send
        custom auth headers, so an auth-required endpoint makes all thumbnails
        render as broken images. The restricted-public tier covers the common
        case (asset deliverables in results/public/assets dirs) while keeping
        source code, configs, logs, and task files gated behind auth.

        Path-traversal protection, symlink checks, and the 25 MiB cap apply
        to BOTH tiers.
        """
        rel_path = (rel_path or "").strip()
        # Reject empty / absolute / traversal paths early.
        if not rel_path or rel_path.startswith("/") or ".." in rel_path.split("/"):
            return self._json({"error": "bad path", "path": rel_path}, 400)

        # Resolve against COMPANY_ROOT and confirm containment.
        try:
            target = (COMPANY_ROOT / rel_path).resolve()
        except Exception as e:
            return self._json({"error": "could not resolve path", "detail": str(e)}, 400)
        try:
            import os as _os
            if _os.path.commonpath([str(COMPANY_ROOT.resolve()), str(target)]) != str(COMPANY_ROOT.resolve()):
                return self._json({"error": "path escapes company root"}, 400)
        except Exception:
            return self._json({"error": "path escapes company root"}, 400)

        # Must be a regular file (not a dir, not a symlink to a dir).
        if target.is_symlink():
            try:
                link_target = target.resolve()
                if not link_target.is_file():
                    return self._json({"error": "not a regular file"}, 400)
            except Exception:
                return self._json({"error": "could not resolve symlink"}, 400)
        if not target.is_file():
            return self._json({"error": "not a regular file", "path": str(target)}, 400)

        # 25 MiB cap (applies to both tiers).
        try:
            size = target.stat().st_size
        except Exception as e:
            return self._json({"error": "stat failed", "detail": str(e)}, 500)
        if size > 25 * 1024 * 1024:
            return self._json({"error": "file too large", "size_bytes": size, "max_bytes": 25 * 1024 * 1024}, 413)

        # ---- Decide which tier this request falls into ----
        authed = is_authorized(self)
        if not authed:
            ext = target.suffix.lower().lstrip(".")
            # Image/video MIME whitelist (keep tight — these are types the
            # browser can render inline. Adding new types is a deliberate
            # choice because each type has a different risk profile.)
            PUBLIC_EXTS = {"png", "jpg", "jpeg", "gif", "webp", "svg", "avif",
                           "bmp", "ico", "mp4", "webm", "mov"}
            if ext not in PUBLIC_EXTS:
                return self._json(auth_required_error(), 401)
            # Path must be under 01_projects/<project>/<safe-dir>/
            # safe-dir = results | public | assets
            try:
                rel = target.relative_to(COMPANY_ROOT)
            except ValueError:
                return self._json({"error": "path not under company root"}, 400)
            parts = rel.parts  # e.g. ('01_projects', 'diy-hub-v1', 'results', 'foo.png')
            if len(parts) < 4 or parts[0] != "01_projects" or parts[2] not in ("results", "public", "assets"):
                return self._json(auth_required_error(), 401)

        # Content-Type via mimetypes (stdlib).
        ctype, _enc = mimetypes.guess_type(str(target))
        if not ctype:
            ctype = "application/octet-stream"

        try:
            body = target.read_bytes()
        except Exception as e:
            return self._json({"error": "read failed", "detail": str(e)}, 500)

        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # Safe to cache — files on disk don't change frequently, and the
        # browser will refetch when the kanban modal reopens.
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            # Client disconnected mid-stream — nothing useful we can do.
            pass
        return None

    def do_GET(self):
        try:
            p = urllib.parse.urlparse(self.path)
            path = p.path
            qs = urllib.parse.parse_qs(p.query)

            if path in ("/", "/mission-control.html", "/index.html"):
                return self._static("mission-control.html")

            # MC-KANBAN-MOVE-1 (2026-06-16): standalone Kanban page
            if path == "/kanban":
                return self._static("kanban.html")

            if path == "/api/health":
                v = get_version()
                return self._json({
                    "status": "ok",
                    "version": v["version"],
                    "commit": v["commit"],
                    "uptime_sec": int(time.time() - START_TIME),
                })

            if path == "/api/version":
                v = get_version()
                # Stage 16: live per-request detection, with last-known-good
                # surfaced separately for debugging. `lan_ip` remains a string
                # so the existing dashboard contract is preserved.
                _live_ip = get_lan_ip()
                return self._json({
                    **v,
                    "uptime_sec": int(time.time() - START_TIME),
                    "started_at": datetime.fromtimestamp(START_TIME, tz=timezone.utc).isoformat(),
                    "lan_ip": _live_ip,
                    "lan_ip_fallback": _last_known_lan_ip,
                    "lan_ip_auto": _LAN_IP_OK,
                    "port": PORT,
                })

            if path == "/api/data/overview":
                return self._json(data_overview())
            if path == "/api/data/agents":
                return self._json(data_agents())
            if path == "/api/heartbeat":
                # MC-LIVE-REFRESH-1 (2026-06-18): GET /api/heartbeat returns
                # the most-recent heartbeat per agent. Independent from
                # /api/data/agents so a frontend can poll just for liveness
                # cheaply (this endpoint reads at most 3 small files).
                return self._json(read_heartbeats())
            if path == "/api/data/tasks":
                # Stage 12: demo hidden by default. Use ?include=demo to opt in.
                # Backward compat: legacy ?filter=demo|real still respected.
                qs_p = urllib.parse.parse_qs(p.query)
                include_demo = "demo" in qs_p.get("include", [])
                _legacy = (qs_p.get("filter", [None])[0] or "").strip().lower()
                if _legacy == "demo":
                    include_demo = True
                elif _legacy == "real":
                    include_demo = False  # explicit real → keep demo hidden
                return self._json(data_tasks(include_demo=include_demo))
            if path == "/api/data/projects":
                return self._json(data_projects())
            if path == "/api/data/provider":
                return self._json(data_provider())
            if path == "/api/data/logs":
                return self._json(data_logs())
            if path == "/api/data/github":
                # Section 9, added 2026-06-16 (FORGE/NOFI directive)
                return self._json(data_github())
            if path == "/api/data/events":
                # Stage 14: serve the last 50 events from events.jsonl
                qs_e = urllib.parse.parse_qs(p.query)
                try:
                    limit = int((qs_e.get("limit", [50])[0] or "50"))
                except (TypeError, ValueError):
                    limit = 50
                limit = max(1, min(limit, 200))
                return self._json(data_events(limit=limit))
            if path == "/api/data/orders":
                # Stage 19: list pending/in_progress fix_order events
                return self._json(data_orders())
            if path == "/api/data/kanban":
                # MC-KANBAN-1: 6-column board + 3-agent lanes
                qs_k = urllib.parse.parse_qs(p.query)
                include_archived = "true" in (x.lower() for x in qs_k.get("include_archived", []))
                return self._json(data_kanban(include_archived=include_archived))
            if path.startswith("/api/data/kanban/task/"):
                # MC-KANBAN-5 (2026-06-17): GET /api/data/kanban/task/:id/result
                # returns the full "## Result" section body for the modal popup.
                # Other /api/data/kanban/task/:id* GETs return 405 (PATCH only).
                if path.endswith("/result"):
                    task_id = path[len("/api/data/kanban/task/"):-len("/result")]
                    status, payload = get_kanban_task_result(task_id)
                    return self._json(payload, status)
                # PATCH only — GET returns 405
                return self._json({
                    "error": "method not allowed; use PATCH",
                    "allowed": ["PATCH"],
                    "path": path,
                }, 405)

            # ---- MC-MEMORY-GRAPH-1 (2026-06-17): Memory Graph page + API ----
            if path == "/memory-graph":
                # Serve the new vanilla-JS page (same pattern as /kanban).
                return self._static("memory-graph.html")

            # ---- MC-MEMORY-GRAPH-2 (2026-06-17): serve vendored 3D libs ----
            # The 3D page loads three.min.js and 3d-force-graph.min.js via
            # relative paths; the browser resolves them to /vendor/... and we
            # must serve them from the on-disk vendor/ directory. Files only,
            # no path traversal.
            if path.startswith("/vendor/"):
                rel = path[len("/vendor/"):]
                # Reject any traversal attempts.
                if ".." in rel.split("/") or rel.startswith("/"):
                    return self._json({"error": "bad path", "path": path}, 400)
                return self._static("vendor/" + rel)

            if path == "/api/memory-graph" or path == "/api/memory-graph/":
                status, payload = _mg_api.get_graph(self)
                return self._json(payload, status)

            if path.startswith("/api/memory-graph/events/recent"):
                # GET /api/memory-graph/events/recent?n=20
                status, payload = _mg_api.get_events_recent(self)
                return self._json(payload, status)

            if path == "/api/memory-graph/stream":
                # MC-MEMORY-GRAPH-3A-BACKEND §6: SSE disabled. The UI polls
                # /api/memory-graph every 5s. Returning 410 explicitly so
                # clients that still try the old endpoint fail fast.
                status, payload = _mg_api.get_stream_disabled(self)
                return self._json(payload, status)

            # MC-RESULT-IMAGES-1 (2026-06-22): serve company-root-relative
            # files (assets referenced by kanban result bodies). Auth-gated.
            if path == "/api/file":
                return self._serve_company_file(qs.get("path", [""])[0])

            return self._json({"error": "not found", "path": path}, 404)

        except Exception as e:
            return self._json({"error": "server error", "detail": str(e)}, 500)

    def do_POST(self):
        """Stage 17→19: POST /api/data/order — append a structured
        fix_order event to events.jsonl (nofitech-event/v1 schema). Open
        endpoint, no auth, no secrets logged. 400 on bad JSON / missing
        warning_text, 200 on success with {ok, event_id, ts, order_id,
        status, requires_chat_confirmation, recommended_fix}. The Stage 17
        `ok` and `event_id` fields are preserved for backward compat.

        MC-KANBAN-1: POST /api/data/kanban/task — create a new task file
        from the UI. Returns 201 on success, 400 on bad input.

        MC-MEMORY-GRAPH-1 (2026-06-17): POST /api/memory-graph/events —
        ingest one event object OR an array of events. Body caps at 64 KiB.
        All payloads are redacted server-side before persistence.
        POST /api/memory-graph/reset — admin reset; requires header
        X-MC-Admin: yes OR a body of {confirm: true}.
        """
        try:
            p = urllib.parse.urlparse(self.path)

            # ---- MC-LIVE-REFRESH-1 (2026-06-18): heartbeat writer ----
            # POST /api/heartbeat with body {"agent": "thor|forge|argus"}.
            # Default agent = "thor" if missing/blank. NO AUTH (LAN write,
            # not sensitive — the file just bumps mtime on a dotfile). The
            # 4 KiB body cap is more than enough for {"agent":"..."} and
            # guards against accidental large payloads.
            if p.path == "/api/heartbeat":
                try:
                    length = int(self.headers.get("Content-Length") or "0")
                except (TypeError, ValueError):
                    length = 0
                if length < 0 or length > 4 * 1024:
                    return self._json({"error": "missing or oversized body"}, 400)
                raw = self.rfile.read(length) if length > 0 else b"{}"
                try:
                    payload = json.loads(raw.decode("utf-8") or "{}")
                except (UnicodeDecodeError, json.JSONDecodeError) as e:
                    return self._json({"error": "invalid JSON", "detail": str(e)}, 400)
                if not isinstance(payload, dict):
                    return self._json({"error": "body must be a JSON object"}, 400)
                agent_id = payload.get("agent") or "thor"
                try:
                    result = write_heartbeat(agent_id)
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
                return self._json(result, 200)

            # ---- MC-MEMORY-GRAPH-3A-BACKEND: events ingest (auth + module) ----
            if p.path == "/api/memory-graph/events":
                status, body = _mg_api.post_events(self)
                return self._json(body, status)

            # ---- MC-MEMORY-GRAPH-3A-BACKEND: admin reset (auth + module) ----
            if p.path == "/api/memory-graph/reset":
                status, body = _mg_api.post_reset(self)
                return self._json(body, status)

            # ---- MC-LIVE-MEMORY-GRAPH-1 (2026-06-19): admin destructive reset.
            # NOT wired to the UI; kept for explicit ops use.
            if p.path == "/api/memory-graph/admin-reset":
                status, body = _mg_api.post_admin_reset(self)
                return self._json(body, status)

            # ---- MC-MEMORY-GRAPH-REBUILD-1 (2026-06-18): admin rebuild ----
            # Wipe + full re-import from disk in one step. NOFI complained
            # that reset left the graph empty and there was no UI way to
            # repopulate it. This endpoint is the missing piece.
            if p.path == "/api/memory-graph/rebuild":
                status, body = _mg_api.post_rebuild(self)
                return self._json(body, status)

            if p.path == "/api/data/kanban/task":
                # MC-MEMORY-GRAPH-3A-BACKEND §1: auth gate on writes.
                if not is_authorized(self):
                    return self._json(auth_required_error(), 403)
                # Read the body (Content-Length, capped to 16 KiB to be safe)
                try:
                    length = int(self.headers.get("Content-Length") or "0")
                except (TypeError, ValueError):
                    length = 0
                if length <= 0 or length > 16 * 1024:
                    return self._json({"error": "missing or oversized body"}, 400)
                raw = self.rfile.read(length)
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as e:
                    return self._json({"error": "invalid JSON", "detail": str(e)}, 400)
                if not isinstance(payload, dict):
                    return self._json({"error": "body must be a JSON object"}, 400)
                status, body = create_kanban_task(payload)
                return self._json(body, status)

            # ---- MC-FIX-ORDER-ACTIONS (2026-07-15):
            # POST /api/data/order/decision — append a decision event
            # (dispatched | approved | rejected) for an existing order.
            # Body: {order_id, decision, ts, requested_by, note?}
            # Returns {ok, decision_event_id, ts, order_id, decision}
            # or 400 on bad input / 404 if no matching pending order.
            if p.path == "/api/data/order/decision":
                if not is_authorized(self):
                    return self._json(auth_required_error(), 403)
                try:
                    length = int(self.headers.get("Content-Length") or "0")
                except (TypeError, ValueError):
                    length = 0
                if length <= 0 or length > 8 * 1024:
                    return self._json({"error": "missing or oversized body"}, 400)
                raw = self.rfile.read(length)
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as e:
                    return self._json({"error": "invalid JSON", "detail": str(e)}, 400)
                if not isinstance(payload, dict):
                    return self._json({"error": "body must be a JSON object"}, 400)
                order_id   = (payload.get("order_id")   or "").strip()
                decision   = (payload.get("decision")   or "").strip().lower()
                requested_by = (payload.get("requested_by") or "nofi").strip()
                note       = (payload.get("note")       or "").strip()
                if not order_id or decision not in ("dispatch", "approve", "reject"):
                    return self._json(
                        {"error": "order_id required; decision must be dispatch|approve|reject"},
                        400,
                    )
                status_map = {
                    "dispatch": "in_progress",
                    "approve":  "approved",
                    "reject":   "rejected",
                }
                new_status = status_map[decision]
                ts = datetime.now(timezone.utc).isoformat()
                event_id = f"order-decision-{int(time.time())}-{uuid.uuid4().hex[:8]}"
                p_jsonl = COMPANY_ROOT / "00_company_os" / "events.jsonl"
                line = {
                    "ts":                 ts,
                    "actor":              requested_by,
                    "event_type":         "order_decision",
                    "project":            "mission-control",
                    "task_id":            "",
                    "title":              f"ORDER DECISION: {decision.upper()} {order_id}",
                    "message":             note or f"NOFI chose {decision} via dashboard button",
                    "status":             new_status,
                    "source_file":        "00_company_os/events.jsonl",
                    "schema":             "nofitech-event/v1",
                    "order_id":           order_id,
                    "decision":           decision,
                    "decision_target_status": new_status,
                    "requested_by":       requested_by,
                    "execution_locked_reason":
                        "NOFI directive 2026-06-11 — order decisions are recorded, "
                        "Thor still requires chat confirmation before any auto-execute",
                }
                with p_jsonl.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(line, ensure_ascii=False) + "\n")
                return self._json({
                    "ok": True,
                    "decision_event_id": event_id,
                    "ts": ts,
                    "order_id": order_id,
                    "decision": decision,
                    "status": new_status,
                }, 200)

            if p.path != "/api/data/order":
                return self._json({"error": "not found", "path": p.path}, 404)

            # MC-MEMORY-GRAPH-3A-BACKEND §1: auth gate on writes.
            if not is_authorized(self):
                return self._json(auth_required_error(), 403)

            # Read the body (Content-Length, capped to 16 KiB to be safe)
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except (TypeError, ValueError):
                length = 0
            if length <= 0 or length > 16 * 1024:
                return self._json({"error": "missing or oversized body"}, 400)
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                return self._json({"error": "invalid JSON", "detail": str(e)}, 400)
            if not isinstance(payload, dict):
                return self._json({"error": "body must be a JSON object"}, 400)

            try:
                result = _append_fix_order_event(payload)
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            return self._json(result, 200)

        except Exception as e:
            return self._json({"error": "server error", "detail": str(e)}, 500)

    def do_PATCH(self):
        """MC-KANBAN-1+2: PATCH /api/data/kanban/task/:id — update task's
        `kanban_status` on disk (separate from project-native `status`).
        Body: { "status": "<kanban_status>" }. Returns 200 on success with the full
        updated board, 400 on bad status, 404 on unknown task_id.

        MC-KANBAN-RUNNING-NOW-1 (2026-06-17): allowed statuses are now
            ("triage", "todo", "ready", "running_now", "blocked", "done", "archived")
        The old "running" status is no longer accepted (use "ready" for claimed/waiting
        or "running_now" for actively being worked on).

        MC-KANBAN-ASSIGN-1 (2026-06-17): PATCH /api/data/kanban/task/:id/assign
        — update task's `assigned_to` (Format A) or `owner` row (Format B).
        Body: { "assignee": "thor"|"forge"|"argus"|"" }. Returns 200 on
        success with the full updated board, 400 on bad assignee, 404 on
        unknown task_id. Empty `assignee` removes the field (unassign).

        MC-RESULT-VISIBLE-1 (2026-06-22): the same endpoint now also accepts
        two OPTIONAL fields — `result` (string) and `result_metadata`
        (object with optional `by`, `status`, `date`). When `result` is
        present AND `status == "done"`, the server upserts a `## Result`
        section into the task file via `kanban_parser.upsert_result_section`,
        then appends a `result_recorded` line to events.jsonl so the
        result is searchable even before the card UI re-renders. The
        endpoint signature is BACKWARD COMPATIBLE — PATCH without
        `result` behaves exactly as before. Response gains an extra
        `result_persisted` (true/false) field plus a `result_reason` on
        failure so callers know whether the result landed.
        """
        try:
            p = urllib.parse.urlparse(self.path)
            prefix = "/api/data/kanban/task/"
            if not p.path.startswith(prefix):
                return self._json({"error": "not found", "path": p.path}, 404)

            # MC-MEMORY-GRAPH-3A-BACKEND §1: auth gate on PATCH writes.
            if not is_authorized(self):
                return self._json(auth_required_error(), 403)

            # MC-KANBAN-ASSIGN-1: /assign sub-route. Must be checked BEFORE
            # the bare /:id route below, so the suffix doesn't get mistaken
            # for a task_id.
            if p.path.endswith("/assign"):
                task_id = p.path[len(prefix):-len("/assign")].strip()
                if not task_id or "/" in task_id:
                    return self._json({"error": "task_id is required in path"}, 400)
                # Read body (capped to 4 KiB — only need {"assignee": "..."})
                try:
                    length = int(self.headers.get("Content-Length") or "0")
                except (TypeError, ValueError):
                    length = 0
                if length < 0 or length > 4 * 1024:
                    return self._json({"error": "missing or oversized body"}, 400)
                raw = self.rfile.read(length) if length > 0 else b"{}"
                try:
                    payload = json.loads(raw.decode("utf-8") or "{}")
                except (UnicodeDecodeError, json.JSONDecodeError) as e:
                    return self._json({"error": "invalid JSON", "detail": str(e)}, 400)
                if not isinstance(payload, dict):
                    return self._json({"error": "body must be a JSON object"}, 400)
                status, body = assign_kanban_task(task_id, payload)
                return self._json(body, status)

            # Original MC-KANBAN-2: PATCH /api/data/kanban/task/:id (status)
            task_id = p.path[len(prefix):].strip()
            if not task_id or "/" in task_id:
                return self._json({"error": "task_id is required in path"}, 400)
            # Read body (capped to 4 KiB — only need {"status": "..."})
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except (TypeError, ValueError):
                length = 0
            if length < 0 or length > 4 * 1024:
                return self._json({"error": "missing or oversized body"}, 400)
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                return self._json({"error": "invalid JSON", "detail": str(e)}, 400)
            if not isinstance(payload, dict):
                return self._json({"error": "body must be a JSON object"}, 400)
            new_status = payload.get("status") or ""
            status, body = patch_kanban_task(task_id, new_status)
            # MC-RESULT-VISIBLE-1 (2026-06-22): if the caller included a
            # `result` and the transition is to done, persist the result
            # section to the task file and emit a result_recorded event.
            # Both fields are optional — PATCH with only `status` is
            # unchanged in behavior. We only run this on success (status
            # 200) so a failed status update doesn't leave a phantom
            # result on disk.
            result_persisted = False
            result_reason = None
            result_text = payload.get("result")
            result_metadata = payload.get("result_metadata") if isinstance(payload.get("result_metadata"), dict) else None
            if status == 200 and isinstance(result_text, str) and result_text.strip() and new_status == "done":
                try:
                    ok_res, reason_res = kanban_parser.upsert_result_section(
                        task_id, result_text, result_metadata, COMPANY_ROOT
                    )
                    result_persisted = bool(ok_res)
                    result_reason = reason_res
                    if ok_res:
                        # Append a result_recorded event so the result is
                        # searchable in events.jsonl even before the card
                        # UI reloads.
                        teaser = result_text.strip()
                        if len(teaser) > 200:
                            teaser = teaser[:197] + "..."
                        ev_meta = result_metadata or {}
                        ev_line = {
                            "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                            "event_type": "result_recorded",
                            "actor": (ev_meta.get("by") or "unknown"),
                            "project": "mission-control",
                            "task_id": task_id,
                            "result_teaser": teaser,
                            "log": None,
                        }
                        ev_path = COMPANY_ROOT / "00_company_os" / "events.jsonl"
                        try:
                            with ev_path.open("a", encoding="utf-8") as f:
                                f.write(json.dumps(ev_line, ensure_ascii=False) + "\n")
                        except Exception as ee:
                            # Don't fail the whole PATCH because the event
                            # log is read-only or full — but expose the
                            # error in result_reason so callers can log it.
                            result_reason = f"result written to task file but event append failed: {ee}"
                except Exception as ex:
                    result_persisted = False
                    result_reason = f"upsert raised: {ex}"
            # Annotate the response with whether the result landed. We
            # mutate the response body dict (it's a fresh dict from
            # patch_kanban_task) so callers can inspect result_persisted.
            if isinstance(body, dict):
                body["result_persisted"] = result_persisted
                if result_reason and not result_persisted:
                    body["result_reason"] = result_reason
            return self._json(body, status)
        except Exception as e:
            return self._json({"error": "server error", "detail": str(e)}, 500)


class ReuseTCPServer(socketserver.ThreadingTCPServer):
    """MC-MEMORY-GRAPH-3A-BACKEND §5: threaded TCP server.

    ThreadingTCPServer spawns a fresh thread per request so a slow SSE
    client (or any single request) can never block the rest of the API.
    Combined with daemon_threads = True below, the server shuts down
    cleanly on Ctrl-C.
    """
    allow_reuse_address = True
    daemon_threads = True


def main():
    os.chdir(HERE)
    lan_note = "" if _LAN_IP_OK else " (auto-detect failed, using loopback)"
    _v = get_version()
    print(f"NofiTech Mission Control {_v['version']} ({_v['commit']})")
    print(f"  project:  {PROJECT_ROOT}")
    print(f"  company:  {COMPANY_ROOT}")
    print(f"  serving:  http://0.0.0.0:{PORT}/  (LAN access: http://{HOST_IP}:{PORT}/{lan_note})")
    with ReuseTCPServer((HOST, PORT), Handler) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    main()
