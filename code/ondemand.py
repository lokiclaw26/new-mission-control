#!/usr/bin/env python3
"""
ondemand.py — on-demand command interpreter for NofiTech Ind.

MC-022-ON-DEMAND-1 (2026-06-17). Stdlib only.

When NOFI says "thor, work on X" (in chat), or clicks "Execute" on a
pending order, or invokes the CLI, this module:

  1. Creates a real task file under tasks/ with id MC-AUTO-<timestamp>.
  2. Appends `ondemand_dispatched` + `task_assigned` + `work_started`
     events to events.jsonl.
  3. Optionally moves the task straight to `running_now` on the kanban
     (PATCH /api/data/kanban/task/:id) with the assigned_to agent.
  4. Returns the task_id + path.

Dedup: dispatching the same topic string within 60s returns the
EXISTING task_id, not a new one (in-process cache; the task file is
the source of truth on restart).
"""
from __future__ import annotations

import json
import re
import time
import hashlib
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Tuple

DUBAI = timezone(timedelta(hours=4))
HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent  # 01_projects/mission-control
COMPANY_ROOT = PROJECT_ROOT.parent.parent  # NofiTech-Ind
TASKS_DIR = PROJECT_ROOT / "tasks"
EVENTS_FILE = COMPANY_ROOT / "00_company_os" / "events.jsonl"

KANBAN_SERVER = "http://127.0.0.1:8767"  # loopback
# We still need the admin token for writes — the server's safety policy
# requires it on every write endpoint regardless of source. Read from
# the project's standard env file.
def _admin_token() -> Optional[str]:
    import os
    candidates = [
        os.environ.get("MC_ADMIN_TOKEN"),
        Path.home() / ".hermes" / "scripts" / ".env.mc",
        COMPANY_ROOT / "01_projects" / "mission-control" / "code" / "start-mc.sh",
    ]
    for c in candidates:
        if not c:
            continue
        try:
            if isinstance(c, Path) and c.is_file():
                txt = c.read_text(encoding="utf-8", errors="replace")
                m = re.search(r"MC_ADMIN_TOKEN=[\"']?([^\"'\s]+)", txt)
                if m:
                    return m.group(1)
            elif isinstance(c, str) and c:
                return c
        except Exception:
            continue
    return None

# In-process dedup cache. Maps (topic_sha1, agent) → (task_id, ts).
_dedup: dict = {}
DEDUP_WINDOW_SEC = 60

VALID_AGENTS = ("thor", "forge", "argus")


def _now_iso() -> str:
    return datetime.now(DUBAI).isoformat()


def _id_safe(s: str) -> str:
    """Same rules as the importer: [A-Za-z0-9._-] only."""
    out = re.sub(r"[^A-Za-z0-9._-]+", "-", (s or "").strip())
    out = re.sub(r"-+", "-", out).strip("-")
    return (out or "x")[:200]


def _topic_hash(topic: str) -> str:
    return hashlib.sha1(topic.strip().lower().encode("utf-8")).hexdigest()[:12]


def _append_event(event: dict) -> None:
    """Append a single event line to events.jsonl. Best-effort, never crash."""
    try:
        EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with EVENTS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:  # pragma: no cover
        # Loud, but never break the dispatcher.
        print(f"[ondemand] events.jsonl write failed: {e}", flush=True)


def _kanban_patch(task_id: str, new_status: str, assignee: Optional[str] = None) -> bool:
    """Best-effort PATCH to the running kanban server. Requires admin token."""
    payload: dict = {"status": new_status}
    if assignee:
        payload["kanban_status"] = new_status
    try:
        url = f"{KANBAN_SERVER}/api/data/kanban/task/{urllib.parse.quote(task_id)}"
        headers = {"Content-Type": "application/json"}
        token = _admin_token()
        if token:
            headers["X-MC-Admin-Token"] = token
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="PATCH",
        )
        with urllib.request.urlopen(req, timeout=4) as r:
            return 200 <= r.status < 300
    except Exception as e:
        print(f"[ondemand] kanban PATCH failed for {task_id}: {e}", flush=True)
        return False


def dispatch(
    topic: str,
    *,
    agent: str = "forge",
    source: str = "chat",
    priority: str = "normal",
    project: str = "mission-control",
    move_to_running: bool = True,
) -> Tuple[str, Path]:
    """Create a real task from a free-text topic and kick it off.

    Returns: (task_id, task_path)
    Raises: ValueError on invalid input.
    """
    if not isinstance(topic, str) or not topic.strip():
        raise ValueError("topic must be a non-empty string")
    agent = (agent or "forge").strip().lower()
    if agent not in VALID_AGENTS:
        raise ValueError(f"agent must be one of {VALID_AGENTS}, got {agent!r}")
    topic = topic.strip()

    # Dedup window
    key = (_topic_hash(topic), agent)
    cached = _dedup.get(key)
    if cached and (time.time() - cached[1]) < DEDUP_WINDOW_SEC:
        existing_id, _ = cached
        existing_path = TASKS_DIR / f"{existing_id}.md"
        if existing_path.is_file():
            return existing_id, existing_path
        # Stale cache entry — fall through to recreate.

    # Build task id
    ts_short = datetime.now(DUBAI).strftime("%Y%m%d%H%M%S")
    task_id = f"MC-AUTO-{ts_short}-{key[0][:6].upper()}"
    task_path = TASKS_DIR / f"{task_id}.md"
    now = _now_iso()

    # Render task file (Format A — YAML frontmatter + minimal body).
    title = topic[:200]
    safe_topic = topic.replace('"', '\\"')
    body = f"""---
id: {task_id}
title: {title}
project: {project}
created_by: thor
assigned_to: {agent}
status: in_progress
priority: {priority}
created_at: {now}
updated_at: {now}
current_stage: build
blocker: ""
data_source: ondemand
description: "On-demand task created by Thor (ondemand.dispatch). Topic: {safe_topic}"
source: ondemand.{source}
kanban_status: running_now
---

# {title}

## Why
On-demand task from Thor. Topic from {source}: {safe_topic}

## Acceptance
- (to be filled by assignee)

## Notes
- Created automatically by ondemand.dispatch at {now}
- Dedup key: {key[0]}
- Source: {source}
- Assignee: {agent}
"""
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    task_path.write_text(body, encoding="utf-8")

    # Append events.jsonl
    common = {
        "ts": now,
        "actor": "thor",
        "project": project,
        "task_id": task_id,
        "title": title,
        "source": f"ondemand.{source}",
    }
    _append_event({**common, "event_type": "ondemand_dispatched",
                   "message": f"On-demand dispatch from {source}",
                   "status": "dispatched",
                   "agent": agent,
                   "topic": topic})
    _append_event({**common, "event_type": "task_assigned",
                   "message": f"Assigned to {agent} via ondemand",
                   "status": "assigned",
                   "agent": agent})
    _append_event({**common, "event_type": "work_started",
                   "message": f"Auto-started (ondemand {source})",
                   "status": "in_progress",
                   "agent": agent})

    # Push to running_now on the live kanban
    if move_to_running:
        _kanban_patch(task_id, "running_now", assignee=agent)

    # Cache for dedup
    _dedup[key] = (task_id, time.time())
    return task_id, task_path


def parse_chat_command(message: str) -> Optional[Tuple[str, str, str]]:
    """Parse a NOFI chat message. Returns (cmd, target, agent?) or None.

    Supported patterns (NOFI is the only sender):
      "thor, work on <topic>"
      "thor, execute pending order <id>"
      "thor, do <topic>"
    """
    if not isinstance(message, str):
        return None
    text = message.strip()
    m = re.match(
        r"^thor,?\s+(?:work\s+on|do|execute(?:\s+pending\s+order)?)\s+(.+?)\s*$",
        text, flags=re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return None
    target = m.group(1).strip().rstrip(".!?")
    if not target:
        return None
    cmd = "execute_pending_order" if "pending order" in text.lower() else "work_on"
    return cmd, target, "forge"


# --- CLI ---------------------------------------------------------------

def _cli(argv: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(description="On-demand command interpreter")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dispatch", help="Dispatch a topic to an agent")
    d.add_argument("topic")
    d.add_argument("--agent", default="forge", choices=VALID_AGENTS)
    d.add_argument("--source", default="cli")
    d.add_argument("--priority", default="normal")
    d.add_argument("--no-kanban-push", action="store_true",
                   help="Create the task file but don't PATCH the kanban")
    sub.add_parser("parse", help="Parse a chat command and print the result").add_argument("message")
    args = p.parse_args(argv)
    if args.cmd == "dispatch":
        tid, path = dispatch(
            args.topic, agent=args.agent, source=args.source,
            priority=args.priority,
            move_to_running=not args.no_kanban_push,
        )
        print(json.dumps({"ok": True, "task_id": tid, "path": str(path)}))
        return 0
    if args.cmd == "parse":
        result = parse_chat_command(args.message)
        print(json.dumps({"ok": result is not None, "parsed": result}))
        return 0 if result is not None else 2
    return 1


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))
