#!/usr/bin/env python3
"""
kanban_service.py — Kanban read / write logic, isolated from HTTP.

MC-MEMORY-GRAPH-3A-BACKEND (2026-06-17). Stdlib-only (with the existing
code/kanban_parser.py for parse + format-A/B patching).

All public functions return (http_status, payload_dict) so the HTTP layer
can pass them straight to its JSON responder.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Reuse the existing parser.
import kanban_parser  # noqa: E402


# Allowed kanban column ids (matches MC-KANBAN-RUNNING-NOW-1).
KANBAN_VALID_STATUSES = {
    "triage", "todo", "ready", "running_now",
    "blocked", "done", "archived",
}
KANBAN_LEGACY_STATUS_MAP = {"running": "running_now"}

# Allowed assignees for the /assign endpoint.
KANBAN_VALID_ASSIGNEES = {"thor", "forge", "argus", ""}


def _company_root() -> Path:
    """01_projects/mission-control/code/ → ~/NofiTech-Ind/."""
    return Path(__file__).resolve().parent.parent.parent


def _project_root() -> Path:
    """01_projects/mission-control/code/ → 01_projects/mission-control/."""
    return Path(__file__).resolve().parent.parent


# --- Read ----------------------------------------------------------------

def data_kanban(include_archived: bool = False) -> dict:
    """Full board grouped by status + 3-agent lanes."""
    return kanban_parser.build_board(_company_root(), include_archived=include_archived)


def get_kanban_task_result(task_id: str) -> tuple[int, dict]:
    """GET /api/data/kanban/task/:id/result — return the Result section body."""
    tf = _find_task_file(task_id)
    if tf is None:
        return 404, {"error": "task not found", "task_id": task_id}
    try:
        text = tf.read_text(encoding="utf-8")
    except Exception as e:
        return 500, {"error": f"could not read task: {e}"}
    meta, body = kanban_parser.parse_frontmatter(text)
    m = re.search(r"(?ms)^##\s+Result\s*\n(.*?)(?:\n##\s|\Z)", body)
    result = m.group(1).strip() if m else ""
    return 200, {
        "task_id": task_id,
        "path": str(tf.relative_to(_company_root())),
        "result": result,
        "meta": meta,
    }


# --- Write ---------------------------------------------------------------

def patch_kanban_task(task_id: str, new_status: str) -> tuple[int, dict]:
    """PATCH /api/data/kanban/task/:id — update task's kanban_status."""
    new_status = (new_status or "").strip().lower()
    if not new_status:
        return 400, {"error": "status is required"}
    new_status = KANBAN_LEGACY_STATUS_MAP.get(new_status, new_status)
    if new_status not in KANBAN_VALID_STATUSES:
        return 400, {
            "error": f"invalid status {new_status!r}",
            "allowed": sorted(KANBAN_VALID_STATUSES),
        }
    ok, reason, tf = kanban_parser.update_task_status(
        task_id, new_status, _company_root()
    )
    if not ok or tf is None:
        status = 404 if "not found" in reason else 400
        return status, {"error": reason, "task_id": task_id}

    # Best-effort memory graph emit.
    try:
        import memory_graph_api  # local import to avoid cycles
        meta, _ = kanban_parser.parse_frontmatter(tf.read_text(encoding="utf-8"))
        memory_graph_api.emit_kanban_memory_event(
            task_id=task_id,
            new_status=new_status,
            project=tf.parent.parent.name,
            label=meta.get("title") or task_id,
        )
    except Exception:
        pass
    return 200, {
        "ok": True,
        "task_id": task_id,
        "kanban_status": new_status,
        "board": data_kanban(include_archived=True),
    }


def assign_kanban_task(task_id: str, payload: dict) -> tuple[int, dict]:
    """PATCH /api/data/kanban/task/:id/assign — update assignee.

    The existing kanban_parser doesn't ship an assign helper, so we do a
    minimal in-place edit that mirrors the format-A/_patch_format_a logic.
    """
    if not isinstance(payload, dict):
        return 400, {"error": "body must be a JSON object"}
    raw = (payload.get("assignee") or "").strip().lower()
    if raw not in KANBAN_VALID_ASSIGNEES:
        return 400, {
            "error": f"invalid assignee {raw!r}",
            "allowed": sorted(a for a in KANBAN_VALID_ASSIGNEES if a),
        }
    tf = _find_task_file(task_id)
    if tf is None:
        return 404, {"error": "task not found", "task_id": task_id}
    try:
        text = tf.read_text(encoding="utf-8")
    except Exception as e:
        return 500, {"error": f"could not read task: {e}"}
    meta, body = kanban_parser.parse_frontmatter(text)
    fmt = kanban_parser.detect_format(text)
    if fmt == "A":
        new_text = _set_frontmatter_field(text, "assigned_to", raw)
    elif fmt == "B":
        new_text = _set_table_field(text, "owner", raw)
    else:
        # Unknown format — try A then B.
        new_text = _set_frontmatter_field(text, "assigned_to", raw)
    try:
        tf.write_text(new_text, encoding="utf-8")
    except Exception as e:
        return 500, {"error": f"could not write task: {e}"}
    return 200, {
        "ok": True,
        "task_id": task_id,
        "assignee": raw,
        "board": data_kanban(include_archived=True),
    }


def create_kanban_task(payload: dict) -> tuple[int, dict]:
    """POST /api/data/kanban/task — create a new task file from the UI."""
    if not isinstance(payload, dict):
        return 400, {"error": "body must be a JSON object"}
    project = (payload.get("project") or "").strip()
    title = (payload.get("title") or "").strip()
    description = (payload.get("description") or "").strip()
    priority = (payload.get("priority") or "normal").strip().lower()
    assignee = (payload.get("assignee") or "").strip().lower()
    if not project or not title:
        return 400, {"error": "project and title are required"}
    if priority not in {"low", "normal", "high", "critical"}:
        priority = "normal"
    if assignee not in KANBAN_VALID_ASSIGNEES:
        assignee = ""
    project_dir = _company_root() / "01_projects" / project
    if not project_dir.is_dir():
        return 400, {"error": f"project {project!r} does not exist"}
    tasks_dir = project_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    base = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").upper()[:60] or "TASK"
    base = f"{project.upper()}-{base}"
    task_id = base
    suffix = 0
    while (tasks_dir / f"{task_id}.md").is_file():
        suffix += 1
        task_id = f"{base}-{suffix}"

    now = datetime.now(timezone.utc).isoformat()
    fm_lines = [
        "---",
        f"task_id: {task_id}",
        f"title: {title}",
        f"project: {project}",
        "status: triage",
        "kanban_status: triage",
        f"priority: {priority}",
        "data_source: real",
        f"created: {now}",
        f"updated: {now}",
        "created_by: ui",
    ]
    if assignee:
        fm_lines.append(f"assigned_to: {assignee}")
    fm_lines.append("---\n")
    body = f"# {title}\n\n{description or '_(no description)_'}\n"
    text = "\n".join(fm_lines) + "\n" + body
    out_path = tasks_dir / f"{task_id}.md"
    try:
        out_path.write_text(text, encoding="utf-8")
    except Exception as e:
        return 500, {"error": f"could not write task: {e}"}
    return 201, {
        "ok": True,
        "task_id": task_id,
        "path": str(out_path.relative_to(_company_root())),
        "board": data_kanban(include_archived=True),
    }


def post_order(payload: dict) -> tuple[int, dict]:
    """POST /api/data/order — append a fix_order event to events.jsonl."""
    if not isinstance(payload, dict):
        return 400, {"error": "body must be a JSON object"}
    warning_text = (payload.get("warning_text") or "").strip()
    if not warning_text:
        return 400, {"error": "warning_text is required"}
    warning_source = (payload.get("warning_source") or "ui").strip()
    severity = (payload.get("severity") or "warn").strip().lower()
    if severity not in {"info", "warn", "error"}:
        severity = "warn"

    order_id = "ord-" + uuid.uuid4().hex[:12]
    ts = datetime.now(timezone.utc).isoformat()
    recommended_fix = _build_recommended_fix(warning_text, warning_source)

    event = {
        "schema": "nofitech-event/v1",
        "event_id": "evt-" + uuid.uuid4().hex[:12],
        "ts": ts,
        "actor": (payload.get("actor") or "thor").strip() or "thor",
        "type": "fix_order",
        "warning_text": warning_text[:1000],
        "warning_source": warning_source[:100],
        "severity": severity,
        "order_id": order_id,
        "status": "pending",
        "requires_chat_confirmation": True,
        "recommended_fix": recommended_fix,
    }
    events_path = _project_root() / "data" / "events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return 200, {
        "ok": True,
        "event_id": event["event_id"],
        "ts": ts,
        "order_id": order_id,
        "status": "pending",
        "requires_chat_confirmation": True,
        "recommended_fix": recommended_fix,
    }


# --- helpers -------------------------------------------------------------

def _find_task_file(task_id: str) -> Path | None:
    """Search 01_projects/*/tasks/<task_id>.md and 00_company_os/*/tasks/."""
    if not task_id or "/" in task_id or ".." in task_id:
        return None
    roots = [
        _company_root() / "01_projects",
        _company_root() / "00_company_os",
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for td in root.glob("*/tasks"):
            if not td.is_dir():
                continue
            candidate = td / f"{task_id}.md"
            if candidate.is_file():
                return candidate
    return None


def _set_frontmatter_field(text: str, key: str, value: str) -> str:
    """Set or insert a YAML frontmatter line `key: value`. Remove if empty."""
    header, body_lines, _ = kanban_parser._split_frontmatter(text)
    if not header:
        # No frontmatter — inject one.
        if value:
            new_fm = [f"{key}: {value}"]
        else:
            return text
        return "---\n" + "\n".join(new_fm) + "\n---\n" + text

    pat = re.compile(rf"^(\s*{re.escape(key)}\s*:\s*)(.*?)(\s*(?:#.*)?)$")
    new_header: list[str] = []
    found = False
    for line in header:
        m = pat.match(line)
        if m:
            found = True
            if value:
                new_header.append(f"{m.group(1)}{value}{m.group(3)}")
            # else: drop the line
        else:
            new_header.append(line)
    if not found and value:
        new_header.append(f"{key}: {value}")
    body = "\n".join(body_lines)
    return "---\n" + "\n".join(new_header) + "\n---\n" + body + ("\n" if body and not body.endswith("\n") else "")


def _set_table_field(text: str, key: str, value: str) -> str:
    """Set or insert a row `| **<key>** | <value> |` in a Format B table.

    Empty value removes the row. No-op if no table is present.
    """
    lines = text.splitlines()
    table_header_idx = None
    for i, ln in enumerate(lines):
        if re.match(r"^\|\s*(?:\*\*)?[Ff]ield(?:\*\*)?\s*\|\s*(?:\*\*)?[Vv]alue(?:\*\*)?\s*\|", ln):
            table_header_idx = i
            break
    if table_header_idx is None:
        return text  # no table; nothing to do
    sep_idx = table_header_idx + 1
    row_pat = re.compile(rf"^\|\s*(?:\*\*)?\s*{re.escape(key)}\s*(?:\*\*)?\s*\|\s*([^|]*?)\s*\|", re.IGNORECASE)
    data_start = sep_idx + 1 if sep_idx < len(lines) and re.match(r"^\|[\s\-:|]+\|$", lines[sep_idx]) else sep_idx
    end = data_start
    found = False
    for j in range(data_start, len(lines)):
        ln = lines[j]
        if not ln.lstrip().startswith("|"):
            end = j
            break
        m = row_pat.match(ln)
        if m:
            found = True
            if value:
                lines[j] = f"| **{key}** | {value} |"
            else:
                lines[j] = ""  # mark for removal
        end = j + 1
    if not found and value:
        # insert after first row (data_start).
        lines.insert(data_start, f"| **{key}** | {value} |")
    # Compact: drop blank lines we marked for removal.
    return "\n".join(ln for ln in lines if ln != "")


def _build_recommended_fix(warning_text: str, warning_source: str) -> str:
    txt = warning_text.lower()
    src = warning_source.lower()
    if "kanban" in src or "kanban" in txt:
        return "Open the Kanban tab and triage the listed tasks."
    if "log" in src or "warn" in txt:
        return "Inspect the most recent agent logs and resolve the warning."
    if "blocked" in txt:
        return "Unblock the listed tasks or escalate to the assignee."
    return "Investigate the warning and either resolve or document why."
