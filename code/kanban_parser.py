#!/usr/bin/env python3
"""
kanban_parser.py — parse NofiTech project task files into a kanban board dict.

MC-KANBAN-1 (2026-06-16): Hermes Agent Kanban tab in Mission Control.
MC-KANBAN-2 (2026-06-16): Extend parser to read BOTH formats — YAML frontmatter
                          (Format A) AND markdown `| Field | Value |` table (Format B).
                          PATCH now writes `kanban_status` (separate field) instead
                          of overwriting the project-native `status` field.

3-agent team: Thor (CEO/Orchestrator), Forge (Builder/Engineer), Argus (QA/Tester).

Source of truth: 01_projects/*/tasks/*.md — same files the existing
/api/data/tasks endpoint reads. We do NOT use the external `hermes kanban`
CLI or ~/.hermes/kanban.db (those may not exist on this machine).

Format A (YAML frontmatter) — used by mission-control's MC-* task files:
    ---
    task_id: MC-KANBAN-1
    status: in_progress
    ...
    ---

Format B (markdown table) — used by 50/52 diy-hub-v1 task files:
    | Field | Value |
    |---|---|
    | **id** | DIY-011 |
    | **status** | in_progress |
    | **owner** | Thor (after NOFI direct bug report) |
    ...

Status mapping (project file status → kanban status):
  triage       → triage
  in_progress  → running
  complete /
  done         → done
  blocked      → blocked
  pending /
  approved     → ready
  archived     → archived   (default hidden)
  todo         → todo
"""
from __future__ import annotations

import functools
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any

# MC-ATOMIC-WRITES-1 (2026-07-09): serialize all task-file mutations. The
# server is a ThreadingTCPServer, so two concurrent PATCHes (or a PATCH
# racing the result upsert) would otherwise interleave their
# read-modify-write cycles and silently drop one update. RLock so a locked
# mutator can call another locked mutator without deadlocking.
_WRITE_LOCK = threading.RLock()


def _locked(fn):
    """Run fn while holding the module-wide task-file write lock."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _WRITE_LOCK:
            return fn(*args, **kwargs)
    return wrapper


def atomic_write_text(path: Path, text: str) -> None:
    """Write via a sibling .tmp file + os.replace so a concurrent reader
    (the board scanner, the dispatch crons) never sees a half-written file.
    The .tmp name never matches the *.md task-file globs, so a scan that
    lands mid-write simply doesn't see the file being replaced."""
    tmp = path.parent / (path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)

# Allowed kanban column ids (also used by the PATCH endpoint to validate input)
# MC-KANBAN-RUNNING-NOW-1 (2026-06-17): renamed column 'running' -> 'running_now'.
# 'ready' is the new home for tasks that were 'in_progress' (claimed/waiting).
# 'running_now' is strictly for tasks actively being worked on by an agent.
ALLOWED_STATUSES = ("triage", "todo", "ready", "running_now", "blocked", "done", "archived")

# Map project-file status strings → kanban status
STATUS_MAP = {
    "triage": "triage",
    "todo": "todo",
    "ready": "ready",
    "in_progress": "ready",         # CHANGED from "running" — claimed/waiting, not actively running
    "in-progress": "ready",         # CHANGED from "running" — same as in_progress
    "running": "ready",             # Legacy alias — old "running" status now means "ready"
    "running_now": "running_now",   # NEW — strictly for tasks actively being worked on
    "in_work": "running_now",       # NEW alias
    "active": "running_now",        # NEW alias
    "blocked": "blocked",
    "pending": "ready",             # unchanged
    "approved": "ready",            # unchanged
    "complete": "done",
    "done": "done",
    "archived": "archived",
    "assigned": "ready",            # legacy
    "open": "todo",                 # legacy
    "verification": "running_now",  # CHANGED from "running" — in-verification == actively running
    "failed": "blocked",            # fail visually reads as blocked
}

# 3-agent team (locked charter v3.0, 2026-06-10)
AGENTS = [
    {"id": "thor",  "name": "Thor",  "emoji": "⚡", "role": "CEO / Orchestrator",
     "color": "var(--thor-color)"},
    {"id": "forge", "name": "Forge", "emoji": "🔨", "role": "Builder / Engineer",
     "color": "var(--forge-color)"},
    {"id": "argus", "name": "Argus", "emoji": "👁️", "role": "QA / Tester",
     "color": "var(--argus-color)"},
]
AGENT_IDS = [a["id"] for a in AGENTS]


# ---- frontmatter parsing (stdlib only) ----
def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (meta_dict, body_str). Tolerant of missing / malformed frontmatter.
    Values are stripped of surrounding quotes. Lists (YAML-flow or bracketed) are
    split on commas. Single-item lists are returned as a list of one."""
    if not text or not text.startswith("---\n"):
        return {}, text or ""
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    fm = text[4:end]
    body = text[end + 5:]
    meta: dict = {}
    for line in fm.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        # strip surrounding quotes
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
            v = v[1:-1]
        # list forms: [a, b, c]  or  a, b, c
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            v = [x.strip().strip('"').strip("'") for x in inner.split(",") if x.strip()] if inner else []
        elif "," in v and not re.search(r"[A-Z]:", v):
            # heuristic: comma-separated only if it looks like a list, not e.g. an ISO date
            # ISO dates have a single T and no comma — this is safe
            parts = [x.strip().strip('"').strip("'") for x in v.split(",") if x.strip()]
            if len(parts) > 1:
                v = parts
        meta[k] = v
    return meta, body


# ---- Format B (markdown table) parsing ----
_TABLE_HEADER_RE = re.compile(r"^\|\s*Field\s*\|\s*Value\s*\|\s*$", re.IGNORECASE | re.MULTILINE)
_TABLE_SEP_RE    = re.compile(r"^\|\s*-{2,}\s*\|\s*-{2,}\s*\|\s*$", re.MULTILINE)
_TABLE_ROW_RE    = re.compile(r"^\|\s*(?P<key>\*\*[^*]+\*\*|\w[^|]*?)\s*\|\s*(?P<val>.*?)\s*\|\s*$")


def _coerce_str(v: Any) -> str:
    """Format B: coerce any value to a string (per spec)."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return str(v)


def parse_markdown_table(text: str) -> tuple[dict, str]:
    """Format B: extract `| **field** | value |` rows.

    Returns (table_dict, body_str). Empty dict if no table found.
    Keys are normalised to lowercase; surrounding `**` markers are stripped.
    """
    if not text:
        return {}, ""
    # find the table header `| Field | Value |`
    m = _TABLE_HEADER_RE.search(text)
    if not m:
        return {}, text
    # walk lines starting at the header + 1 (the separator) + 1 (first data row)
    lines = text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if _TABLE_HEADER_RE.match(line):
            header_idx = i
            break
    if header_idx is None:
        return {}, text
    # next non-blank line should be the separator
    data_start = header_idx + 1
    if data_start < len(lines) and _TABLE_SEP_RE.match(lines[data_start]):
        data_start += 1
    out: dict = {}
    body_start = None
    for j in range(data_start, len(lines)):
        ln = lines[j]
        if not ln.lstrip().startswith("|"):
            # end of table
            body_start = j
            break
        rm = _TABLE_ROW_RE.match(ln)
        if not rm:
            body_start = j
            break
        raw_key = rm.group("key").strip()
        # strip surrounding ** ... **
        if raw_key.startswith("**") and raw_key.endswith("**") and len(raw_key) >= 4:
            key = raw_key[2:-2].strip().lower()
        else:
            key = raw_key.strip().lower()
        val = _coerce_str(rm.group("val").strip())
        if key:
            out[key] = val
    if body_start is None:
        body_start = len(lines)
    body = "\n".join(lines[body_start:])
    return out, body


def detect_format(text: str) -> str:
    """Return "A" (YAML frontmatter), "B" (markdown table), or "" (neither)."""
    if not text:
        return ""
    has_frontmatter = text.startswith("---\n") and "\n---\n" in text[4:]
    has_table = bool(_TABLE_HEADER_RE.search(text))
    if has_frontmatter and has_table:
        return "A"  # both → prefer A, with a warning emitted by the caller
    if has_frontmatter:
        return "A"
    if has_table:
        return "B"
    return ""


def _as_str(v: Any) -> str:
    """Coerce a meta value to a string. Lists (e.g. title parsed as list because
    of parenthetical commas) are joined with ', '. Non-string scalars are str()'d.
    Returns "" for None."""
    if v is None:
        return ""
    if isinstance(v, list):
        return ", ".join(_as_str(x) for x in v if x is not None and str(x) != "")
    return str(v)


def _strip_parens(name: str) -> str:
    """Remove parenthetical explanations from an owner string.
    "Thor (after NOFI direct bug report)" → "Thor"
    "Forge" → "Forge"
    """
    if not name:
        return ""
    return re.sub(r"\s*\([^)]*\)", "", name).strip()


def _normalize_assignee_freeform(raw) -> str | None:
    """Normalize Format B `owner` field: lowercase, strip parens, then
    try to map to one of the 3 known agents. Returns the agent id or None.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # strip parenthetical
    s = _strip_parens(s)
    s = s.strip().strip(".,;:").lower()
    if not s:
        return None
    # first token / first word is usually the agent name
    first = re.split(r"[\s,/&]+", s)[0]
    if first in AGENT_IDS:
        return first
    # handle "thor" inside "thor+argus" or "thor / argus"
    for aid in AGENT_IDS:
        if aid in s.split() or aid in re.split(r"[\s,/&+]+", s):
            return aid
    return None


def _normalize_assignee(raw) -> str | None:
    """Frontmatter `assigned_to` may be a string ("forge"), a list (["forge", "argus"]),
    or comma-separated. Kanban needs a single primary assignee per card; we use
    the first agent in the list that matches the 3-agent team, else None."""
    if raw is None:
        return None
    if isinstance(raw, list):
        items = [str(x).strip().lower() for x in raw]
    else:
        s = str(raw).strip()
        if s.startswith("[") and s.endswith("]"):
            s = s[1:-1]
        items = [x.strip().strip('"').strip("'").lower() for x in s.split(",") if x.strip()]
    for item in items:
        if item in AGENT_IDS:
            return item
    return None


def _pick_assignee(*candidates) -> str | None:
    """MC-PARSER-AGENT-FIELD-1 (2026-06-17): try each candidate in order
    (highest precedence first) and return the first normalized agent id.

    Candidates are typically frontmatter keys like `("assigned_to", "assignee", "agent")`
    for Format A or `("owner", "assignee", "agent")` for Format B. A candidate
    is "present" if its meta value is non-None and non-empty (after str/strip).
    If none yields a known agent id, returns None (→ card shows "unassigned").
    """
    for raw in candidates:
        if raw is None:
            continue
        if isinstance(raw, str) and not raw.strip():
            continue
        if isinstance(raw, (list, tuple)) and not raw:
            continue
        result = _normalize_assignee(raw)
        if result is not None:
            return result
    return None


def _normalize_status(raw: str) -> str:
    return STATUS_MAP.get((raw or "").strip().lower(), "triage")


# ---- MC-KANBAN-5: Result section extraction (2026-06-17) ----
# Parses the structured "## Result" section from a task body. Returns
# (teaser, metadata_dict) where teaser is the first ~150 chars of the
# rendered result text (markdown stripped to a single line for the card
# teaser) and metadata contains {date, by, status} extracted from the
# "**Date:**", "**By:**", "**Status:**" header lines. Returns (None, None)
# if the body has no Result section.
_RESULT_HEADER_RE = re.compile(r"^##\s+Result\s*$\n", re.MULTILINE)
_DATE_LINE_RE = re.compile(r"^\*\*Date:\*\*\s*(.+?)\s*$", re.MULTILINE)
_BY_LINE_RE = re.compile(r"^\*\*By:\*\*\s*(.+?)\s*$", re.MULTILINE)
_STATUS_LINE_RE = re.compile(r"^\*\*Status:\*\*\s*(.+?)\s*$", re.MULTILINE)


def _extract_result_section(body: str) -> tuple[str | None, dict | None]:
    """Extract the structured `## Result` section from a task body.

    Returns (teaser, metadata). teaser is a single-line summary (<= 160 chars)
    suitable for showing on the kanban card. metadata has keys {date, by, status}.
    Returns (None, None) when there is no Result section.
    """
    if not body:
        return None, None
    m = _RESULT_HEADER_RE.search(body)
    if not m:
        return None, None
    # Slice the result section: from the header line to the next "## " heading
    # (or end of body). Append sub-entries (`### Result entry — ...`) to the
    # slice so multiple entries show up in the teaser.
    start = m.end()
    rest = body[start:]
    next_h = re.search(r"^##\s+", rest, re.MULTILINE)
    section = rest if not next_h else rest[: next_h.start()]

    # Pull metadata from the first `**Date:**/By/Status` block in the section.
    date_m = _DATE_LINE_RE.search(section)
    by_m = _BY_LINE_RE.search(section)
    status_m = _STATUS_LINE_RE.search(section)
    metadata = {
        "date": (date_m.group(1).strip() if date_m else ""),
        "by": (by_m.group(1).strip() if by_m else ""),
        "status": (status_m.group(1).strip() if status_m else ""),
    }

    # Build a teaser: take the section text, drop the **Date/By/Status** lines,
    # collapse newlines, trim to ~160 chars. This is the snippet shown on the
    # card BEFORE the user clicks "View Result".
    teaser_lines = []
    for line in section.splitlines():
        s = line.strip()
        if not s:
            continue
        # skip the metadata header lines
        if s.startswith("**Date:**") or s.startswith("**By:**") or s.startswith("**Status:**"):
            continue
        # skip sub-entries heading (e.g. "### Result entry — 2026-...")
        if s.startswith("### Result entry"):
            continue
        # skip horizontal rules
        if s == "---":
            continue
        teaser_lines.append(s)
    teaser_raw = " ".join(teaser_lines).strip()
    # Collapse multiple spaces and strip stray markdown punctuation
    teaser_raw = re.sub(r"\s+", " ", teaser_raw)
    if len(teaser_raw) > 160:
        teaser_raw = teaser_raw[:157].rstrip() + "..."
    return (teaser_raw or None), (metadata if (metadata["date"] or metadata["by"] or metadata["status"]) else None)


def _read_text(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        if path.stat().st_size > 256 * 1024:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


# ---- primary task scan ----
def _iter_task_files(company_root: Path) -> list[Path]:
    """Return all *.md files under 01_projects/*/tasks/ and 00_company_os/*/tasks/
    that have EITHER a YAML frontmatter block OR a markdown table (Filter empty
    placeholders)."""
    out: list[Path] = []
    roots = [company_root / "01_projects"]
    roots.append(company_root / "00_company_os")
    for root in roots:
        if not root.is_dir():
            continue
        for td in root.glob("*/tasks"):
            if not td.is_dir():
                continue
            for tf in sorted(td.glob("*.md")):
                txt = _read_text(tf)
                if not txt:
                    continue
                fmt = detect_format(txt)
                if fmt:
                    out.append(tf)
    return out


# ---- per-file task extraction (returns the unified dict) ----
def _task_from_format_a(tf: Path, company_root: Path) -> dict | None:
    """Format A: YAML frontmatter."""
    txt = _read_text(tf)
    if not txt:
        return None
    meta, body = parse_frontmatter(txt)
    task_id = (meta.get("task_id") or tf.stem).strip()
    if not task_id:
        return None
    status_raw = (meta.get("status") or "").strip().lower()
    kanban_status_raw = (meta.get("kanban_status") or "").strip().lower()
    kanban_status = kanban_status_raw or _normalize_status(status_raw)
    # MC-KANBAN-RUNNING-NOW-1: legacy `kanban_status: running` now means "ready"
    # (the old "running" column id is gone — use "ready" for claimed/waiting).
    if kanban_status == "running":
        kanban_status = "ready"
    priority = _as_str(meta.get("priority") or "normal").strip().lower()
    created = _as_str(meta.get("created") or meta.get("created_at") or "").strip() or None
    # MC-PARSER-AGENT-FIELD-1: precedence assigned_to > assignee > agent
    # (assigned_to is canonical; assignee is what the wrapper currently writes;
    # agent is the legacy field used by older task files like MC-007-token-budget).
    assignee = _pick_assignee(
        meta.get("assigned_to"),
        meta.get("assignee"),
        meta.get("agent"),
    )
    current_assignment = _as_str(meta.get("current_assignment") or "").strip() or None
    if not current_assignment:
        # fallback: per spec — default to task_id itself
        current_assignment = task_id
    title = _as_str(meta.get("title") or tf.stem).strip()
    approval_status = _as_str(meta.get("approval_status") or "").strip().lower() or None
    approval_required_raw = _as_str(meta.get("approval_required") or "").strip().lower()
    approval_required = approval_required_raw in ("true", "1", "yes", "on")
    created_by = _as_str(meta.get("created_by") or "").strip() or None
    project = _as_str(meta.get("project") or tf.parent.parent.name).strip()
    body_first_line = ""
    for line in (body or "").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            body_first_line = s[:120]
            break
    # MC-KANBAN-5: extract structured `## Result` section (if any)
    result_teaser, result_metadata = _extract_result_section(body or "")
    has_result = bool(result_teaser) or (
        _as_str(meta.get("has_result") or "").strip().lower() in ("true", "1", "yes")
    )
    return {
        "task_id": task_id,
        "title": title,
        "project": project,
        "status": status_raw or "triage",         # RAW, project-native
        "kanban_status": kanban_status,
        "priority": priority,
        "created": created,
        "created_by": created_by,
        "assigned_to": assignee,
        "current_assignment": current_assignment,
        "approval_required": approval_required,
        "approval_status": approval_status,
        "source_format": "A",
        "source_file": str(tf.relative_to(company_root)),
        "warnings": [],
        "extra": {},
        "preview": body_first_line,
        "has_result": has_result,
        "result_teaser": result_teaser,
        "result_metadata": result_metadata,
    }


def _task_from_format_b(tf: Path, company_root: Path) -> dict | None:
    """Format B: markdown `| Field | Value |` table."""
    txt = _read_text(tf)
    if not txt:
        return None
    table, body = parse_markdown_table(txt)
    warnings: list[str] = []
    task_id = (table.get("id") or "").strip()
    if not task_id:
        warnings.append("Format B: missing 'id' row — skipping file")
        return {
            "task_id": "",
            "title": tf.stem,
            "project": tf.parent.parent.name,
            "status": None,
            "kanban_status": None,
            "priority": None,
            "created": None,
            "created_by": None,
            "assigned_to": None,
            "current_assignment": None,
            "approval_required": False,
            "approval_status": None,
            "source_format": "B",
            "source_file": str(tf.relative_to(company_root)),
            "warnings": warnings,
            "extra": {},
            "preview": "",
            "_skip": True,
        }
    status_raw = (table.get("status") or "").strip().lower()
    kanban_status_raw = (table.get("kanban_status") or "").strip().lower()
    kanban_status = kanban_status_raw or _normalize_status(status_raw)
    # MC-KANBAN-RUNNING-NOW-1: legacy `kanban_status: running` now means "ready"
    if kanban_status == "running":
        kanban_status = "ready"
    priority = (table.get("priority") or "normal").strip().lower()
    created = (table.get("created_at") or "").strip() or None
    owner_raw = table.get("owner")
    # MC-PARSER-AGENT-FIELD-1: precedence owner > assignee > agent
    # (owner is the canonical Format B field; assignee/agent are fallbacks
    # for files that may use the same field names as Format A).
    assignee = _pick_assignee(
        owner_raw,
        table.get("assignee"),
        table.get("agent"),
    )
    if not assignee:
        # Fall back to the freeform normalizer for owner only (handles
        # parentheticals like "Thor (after NOFI direct bug report)" that the
        # raw lookup would miss because the value isn't a clean agent id).
        assignee = _normalize_assignee_freeform(owner_raw)
    title = (table.get("title") or tf.stem).strip()
    project = (table.get("project") or tf.parent.parent.name).strip()
    extra: dict = {}
    if table.get("started_at"):
        extra["started_at"] = table["started_at"]
    if table.get("due"):
        extra["due"] = table["due"]
    if table.get("depends_on"):
        extra["depends_on_raw"] = table["depends_on"]
    if table.get("phase"):
        extra["phase"] = table["phase"]
    if table.get("scope"):
        extra["scope"] = table["scope"]
    body_first_line = ""
    for line in (body or "").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            body_first_line = s[:120]
            break
    # MC-KANBAN-5: extract structured `## Result` section (if any)
    result_teaser, result_metadata = _extract_result_section(body or "")
    has_result = bool(result_teaser) or (
        (table.get("has_result") or "").strip().lower() in ("true", "1", "yes")
    )
    return {
        "task_id": task_id,
        "title": title,
        "project": project,
        "status": status_raw or "triage",         # RAW, preserved as-is
        "kanban_status": kanban_status,
        "priority": priority,
        "created": created,
        "created_by": None,                       # not in Format B
        "assigned_to": assignee,
        "current_assignment": task_id,            # fallback per spec
        "approval_required": False,
        "approval_status": None,
        "source_format": "B",
        "source_file": str(tf.relative_to(company_root)),
        "warnings": warnings,
        "extra": extra,
        "preview": body_first_line,
        "has_result": has_result,
        "result_teaser": result_teaser,
        "result_metadata": result_metadata,
    }


def _card_from_task_file(tf: Path, company_root: Path) -> dict | None:
    """Dispatch to the right format parser; return a unified card dict.
    Returns None for files with NEITHER format. Returns a card with
    `_skip: True` for Format B files missing required fields."""
    txt = _read_text(tf)
    if not txt:
        return None
    fmt = detect_format(txt)
    if not fmt:
        return None
    if fmt == "A":
        card = _task_from_format_a(tf, company_root)
    else:
        card = _task_from_format_b(tf, company_root)
    if card is None:
        return None
    # If both formats present, Format A wins; warn
    if fmt == "A":
        has_table = bool(_TABLE_HEADER_RE.search(txt))
        if has_table:
            card["warnings"].append("File has BOTH YAML frontmatter and a markdown table — using frontmatter")
    if card.get("_skip"):
        return card
    return card


# ---- public board builder ----
def build_board(company_root: Path, include_archived: bool = False) -> dict:
    """Build the full kanban board dict. Filters archived unless include_archived
    is True. Always returns all 6 columns (some may be empty)."""
    columns = ["triage", "todo", "ready", "running_now", "blocked", "done", "archived"]
    cols = {c: [] for c in columns}

    # Per-status counts (BEFORE archived filter — caller decides visibility)
    all_cards: list[dict] = []
    all_warnings: list[str] = []
    format_a_count = 0
    format_b_count = 0
    skipped = 0
    for tf in _iter_task_files(company_root):
        card = _card_from_task_file(tf, company_root)
        if card is None:
            continue
        if card.get("_skip"):
            skipped += 1
            all_warnings.extend(card.get("warnings", []))
            continue
        # collect warnings
        for w in card.get("warnings", []):
            all_warnings.append(f"[{card.get('source_file')}] {w}")
        all_cards.append(card)
        if card.get("source_format") == "A":
            format_a_count += 1
        else:
            format_b_count += 1
        # use kanban_status for column assignment (per Part 3 spec)
        col_id = card.get("kanban_status") or _normalize_status(card.get("status") or "")
        if col_id not in cols:
            col_id = "running_now"  # unknown → running_now (MC-KANBAN-RUNNING-NOW-1)
        cols[col_id].append(card)

    # Counts
    by_status = {c: len(cols[c]) for c in columns}
    by_assignee = {a: 0 for a in AGENT_IDS}
    for c in all_cards:
        if c["assigned_to"] in by_assignee:
            by_assignee[c["assigned_to"]] += 1

    # Sort cards inside each column by created desc (most recent first)
    def _created_key(card: dict) -> str:
        return card.get("created") or ""
    for c in columns:
        cols[c].sort(key=_created_key, reverse=True)

    # Build the visible columns list (excludes archived unless asked)
    visible_statuses = list(columns)
    if not include_archived:
        visible_statuses = [c for c in visible_statuses if c != "archived"]

    column_meta = {
        "triage":  {"id": "triage",  "label": "Triage"},
        "todo":    {"id": "todo",    "label": "Todo"},
        "ready":   {"id": "ready",   "label": "Ready"},
        "running_now": {"id": "running_now", "label": "Running Now"},  # NEW (MC-KANBAN-RUNNING-NOW-1)
        "blocked": {"id": "blocked", "label": "Blocked"},
        "done":    {"id": "done",    "label": "Done"},
        "archived":{"id": "archived","label": "Archived"},
    }
    out_columns = []
    for c in visible_statuses:
        col = {
            "id": c,
            "label": column_meta[c]["label"],
            "count": by_status[c],
            "tasks": cols[c],
        }
        if c == "running_now":
            lanes = []
            for a in AGENTS:
                lane_tasks = [card for card in cols["running_now"] if card.get("assigned_to") == a["id"]]
                lanes.append({
                    "assignee": a["id"],
                    "name": a["name"],
                    "emoji": a["emoji"],
                    "count": len(lane_tasks),
                    "tasks": lane_tasks,
                })
            # also catch any running_now tasks that don't match the 3-agent team
            assigned_ids = set(AGENT_IDS)
            orphan = [card for card in cols["running_now"] if card.get("assigned_to") not in assigned_ids]
            if orphan:
                lanes.append({
                    "assignee": "unassigned",
                    "name": "Unassigned",
                    "emoji": "❓",
                    "count": len(orphan),
                    "tasks": orphan,
                })
            col["lanes"] = lanes
        out_columns.append(col)

    return {
        "columns": out_columns,
        "agents": AGENTS,
        "summary": {
            "total": len(all_cards),
            "visible": sum(by_status[c] for c in visible_statuses),
            "by_status": by_status,
            "by_assignee": by_assignee,
            "by_format": {"A": format_a_count, "B": format_b_count},
            "skipped": skipped,
        },
        "warnings": all_warnings,
        "include_archived": include_archived,
    }


# ---- file mutation (PATCH) ----
def _split_frontmatter(text: str) -> tuple[list[str], list[str], str]:
    """Return (header_lines, body_lines, trailing) where header_lines is the
    list of lines INSIDE the frontmatter (no --- markers), body_lines is the
    post-frontmatter body, and trailing is whatever comes after the body.

    If there is no frontmatter, return ([], text.splitlines(), '')."""
    if not text or not text.startswith("---\n"):
        return [], text.splitlines() if text else [], ""
    end = text.find("\n---\n", 4)
    if end < 0:
        # malformed — treat whole file as body
        return [], text.splitlines(), ""
    fm = text[4:end]
    body = text[end + 5:]
    return fm.splitlines(), body.splitlines(), ""


# ---- Format A PATCH: write kanban_status to frontmatter, cascade to status when done ----
@_locked
def _patch_format_a(path: Path, new_status: str) -> tuple[bool, str]:
    """Update the YAML frontmatter of `path` to set `kanban_status: <new_status>`.
    Also cascades: if new_status == "done", also set `status: done` in the
    same frontmatter. This is the data-layer half of MC-KANBAN-DONE-PILL-1:
    before this fix, dragging a card to Done only updated `kanban_status`,
    leaving the project-native `status: in_progress` field untouched — so
    every API consumer that read `status` saw a "still in progress" card in
    the Done column. Cascading on done is safe because Done is terminal —
    no agent should ever need to read `status=in_progress` on a task that's
    already been shipped. Other transitions (ready, running_now, blocked,
    triage) do NOT cascade — those are user-only/cosmetic and the project
    status carries real signal that must be preserved.
    """
    txt = path.read_text(encoding="utf-8")
    header, body, _ = _split_frontmatter(txt)
    cascade_to_done = (new_status == "done")
    if not header:
        # No frontmatter — inject a minimal one (this shouldn't happen for Format A,
        # but be defensive)
        new_fm = [
            f"kanban_status: {new_status}",
        ]
        if cascade_to_done:
            new_fm.append("status: done")
        out = "---\n" + "\n".join(new_fm) + "\n---\n" + "\n".join(body) + ("\n" if body and not body[-1] else "")
        if not out.endswith("\n"):
            out += "\n"
        atomic_write_text(path, out)
        return True, "injected kanban_status" + (" + cascaded status=done" if cascade_to_done else "") + " (no frontmatter was present)"
    # Update / insert the kanban_status line; cascade to status line if done
    new_header = []
    ks_replaced = False
    status_replaced = False
    for line in header:
        m = re.match(r'^(\s*kanban_status\s*:\s*)(.*?)(\s*(?:#.*)?)$', line)
        if m:
            new_header.append(f"{m.group(1)}{new_status}{m.group(3)}")
            ks_replaced = True
            continue
        if cascade_to_done:
            m2 = re.match(r'^(\s*status\s*:\s*)(.*?)(\s*(?:#.*)?)$', line)
            if m2:
                new_header.append(f"{m2.group(1)}done{m2.group(3)}")
                status_replaced = True
                continue
        new_header.append(line)
    if not ks_replaced:
        new_header.append(f"kanban_status: {new_status}")
    if cascade_to_done and not status_replaced:
        new_header.append("status: done")
    out = "---\n" + "\n".join(new_header) + "\n---\n" + "\n".join(body)
    if not out.endswith("\n"):
        out += "\n"
    atomic_write_text(path, out)
    return True, "ok" + (" (cascaded status=done)" if cascade_to_done else "")


# ---- Format B PATCH: insert/update kanban_status row in the table ----
_TABLE_ROW_KV_RE = re.compile(r"^\|\s*(?P<key>\*\*[^*]+\*\*|\w[^|]*?)\s*\|\s*(?P<val>.*?)\s*\|\s*$")


@_locked
def _patch_format_b(path: Path, new_status: str) -> tuple[bool, str]:
    """Update the markdown table in `path` to set `| **kanban_status** | <new_status> |`.
    If the row already exists, replace its value.
    If not, insert a new row RIGHT AFTER the `| **status** | ... |` row.
    MC-KANBAN-DONE-PILL-1: if new_status == "done", also update the
    `| **status** | ... |` row to "done" in the same write — cascades the
    project status to match the kanban column. Other transitions leave the
    project status untouched.
    """
    txt = path.read_text(encoding="utf-8")
    lines = txt.splitlines()
    cascade_to_done = (new_status == "done")
    # find the table header `| Field | Value |` (or `| field | value |`)
    header_idx = None
    for i, line in enumerate(lines):
        if _TABLE_HEADER_RE.match(line):
            header_idx = i
            break
    if header_idx is None:
        return False, "Format B table header not found"

    # walk the table rows, find status row + kanban_status row
    data_start = header_idx + 1
    if data_start < len(lines) and _TABLE_SEP_RE.match(lines[data_start]):
        data_start += 1
    status_row_idx = None
    kanban_row_idx = None
    for j in range(data_start, len(lines)):
        ln = lines[j]
        if not ln.lstrip().startswith("|"):
            break
        m = _TABLE_ROW_KV_RE.match(ln)
        if not m:
            break
        raw_key = m.group("key").strip()
        if raw_key.startswith("**") and raw_key.endswith("**") and len(raw_key) >= 4:
            key = raw_key[2:-2].strip().lower()
        else:
            key = raw_key.strip().lower()
        if key == "status":
            status_row_idx = j
        elif key == "kanban_status":
            kanban_row_idx = j

    if kanban_row_idx is not None:
        # UPDATE the existing kanban_status row
        ln = lines[kanban_row_idx]
        # Re-build: preserve the leading `|`, the `**kanban_status**` key, and the trailing `|`
        m = _TABLE_ROW_KV_RE.match(ln)
        if not m:
            return False, "could not parse existing kanban_status row"
        # Determine the exact key rendering the file used: `**kanban_status**` or `**Kanban_status**`
        raw_key = m.group("key").strip()
        new_row = f"| {raw_key} | {new_status} |"
        lines[kanban_row_idx] = new_row
    else:
        # INSERT a new kanban_status row right after the status row
        if status_row_idx is None:
            # no status row at all — find the first data row and insert before it
            insert_at = data_start
        else:
            insert_at = status_row_idx + 1
        new_row = f"| **kanban_status** | {new_status} |"
        lines.insert(insert_at, new_row)
        # status row may have shifted; rebuild its index
        if status_row_idx is not None:
            status_row_idx = status_row_idx + 1  # insertion shifted it down by 1

    # MC-KANBAN-DONE-PILL-1: cascade to status row if new_status == done
    if cascade_to_done and status_row_idx is not None:
        # Re-parse the status row (its index may have shifted if we inserted kanban_status)
        # Walk again to find the current status row index
        current_status_idx = None
        for j in range(data_start, len(lines)):
            ln = lines[j]
            if not ln.lstrip().startswith("|"):
                break
            mm = _TABLE_ROW_KV_RE.match(ln)
            if not mm:
                break
            raw_key = mm.group("key").strip()
            key = raw_key[2:-2].strip().lower() if (raw_key.startswith("**") and raw_key.endswith("**") and len(raw_key) >= 4) else raw_key.strip().lower()
            if key == "status":
                current_status_idx = j
                break
        if current_status_idx is not None:
            ln = lines[current_status_idx]
            mm = _TABLE_ROW_KV_RE.match(ln)
            if mm:
                raw_key = mm.group("key").strip()
                lines[current_status_idx] = f"| {raw_key} | done |"

    out = "\n".join(lines)
    if not out.endswith("\n"):
        out += "\n"
    atomic_write_text(path, out)
    return True, "ok" + (" (cascaded status=done)" if cascade_to_done else "")


# ---- MC-RESULT-VISIBLE-1 (2026-06-22): upsert `## Result` section in body ----
def _format_result_block(result_text: str, metadata: dict | None) -> str:
    """Build the canonical `## Result` section body.

    Layout (blank line between header and result text):
        ## Result
        **Date:** <metadata.date or now>
        **By:** <metadata.by or 'unknown'>
        **Status:** <metadata.status or 'success'>

        <result_text>
    """
    md = metadata or {}
    date = (md.get("date") or "").strip()
    by = (md.get("by") or "").strip() or "unknown"
    status = (md.get("status") or "").strip() or "success"
    if not date:
        from datetime import datetime, timezone
        date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    body = (result_text or "").rstrip()
    # Header lines + blank line + result body
    return f"## Result\n**Date:** {date}\n**By:** {by}\n**Status:** {status}\n\n{body}\n"


@_locked
def upsert_result_section(task_id: str, result_text: str, metadata: dict | None,
                          company_root: Path) -> tuple[bool, str]:
    """Upsert a `## Result` section into the task file matching `task_id`.

    Behavior:
      - Locates the task file using the same matching logic as update_task_status
        (stem, exact filename, frontmatter task_id, Format B id row).
      - Reads the file, splits frontmatter from body using _split_frontmatter
        (so YAML frontmatter and Format B markdown tables are both preserved
        exactly — only the body section is touched).
      - If a `## Result` section already exists in the body, replaces its
        contents in place (from the `## Result` header up to the next `## `
        heading or end of body).
      - Otherwise, inserts the new section before the next `## ` heading after
        the body's start, or appends to end of body if no further `## `
        heading exists.
      - Writes the file back atomically.

    Returns (ok, reason). On success reason="ok". On failure reason explains
    why (e.g. "task_id not found: 'XYZ'").
    """
    target: Path | None = None
    for tf in _iter_task_files(company_root):
        if tf.stem == task_id or tf.name == f"{task_id}.md":
            target = tf
            break
        txt = _read_text(tf)
        if not txt:
            continue
        meta, _ = parse_frontmatter(txt)
        if (meta.get("task_id") or "").strip() == task_id:
            target = tf
            break
        table, _ = parse_markdown_table(txt)
        if (table.get("id") or "").strip() == task_id:
            target = tf
            break
    if target is None:
        return False, f"task_id not found: {task_id!r}"

    txt = target.read_text(encoding="utf-8")
    header, body, _ = _split_frontmatter(txt)

    new_block = _format_result_block(result_text, metadata)

    # Find existing `## Result` header in the body. Use the same regex the
    # reader uses (_RESULT_HEADER_RE) so we match exactly.
    m = _RESULT_HEADER_RE.search("\n".join(body))
    if m:
        # Slice from m.start() (within the joined body) to the next `## ` heading
        joined = "\n".join(body)
        start = m.start()
        rest = joined[m.end():]
        next_h = re.search(r"^##\s+", rest, re.MULTILINE)
        end = m.end() + (next_h.start() if next_h else len(rest))
        new_body_str = joined[:start].rstrip() + "\n\n" + new_block + joined[end:].lstrip("\n")
    else:
        # No existing Result section — insert before the next `## ` heading,
        # or append at end of body.
        joined = "\n".join(body)
        next_h = re.search(r"^##\s+", joined, re.MULTILINE)
        if next_h:
            # Insert just before this heading. Keep the heading on its own
            # line by ensuring a blank line separator.
            head, tail = joined[: next_h.start()], joined[next_h.start():]
            head = head.rstrip()
            new_body_str = head + "\n\n" + new_block + "\n" + tail
        else:
            # No more headings — append at end of body
            joined = joined.rstrip()
            new_body_str = joined + "\n\n" + new_block

    # Reassemble header + body. Preserve frontmatter exactly as we read it
    # (header lines came from _split_frontmatter with no --- markers).
    out = "---\n" + "\n".join(header) + "\n---\n" + new_body_str
    if not out.endswith("\n"):
        out += "\n"
    atomic_write_text(target, out)
    return True, "ok"


@_locked
def update_task_status(task_id: str, new_status: str, company_root: Path) -> tuple[bool, str, Path | None]:
    """Update the `kanban_status` field of the task file matching `task_id`.
    Preserves the project-native `status` field. Returns (ok, reason, file_path).

    Rejects:
      - unknown status (returns ok=False, reason='unknown status')
      - unknown task_id (returns ok=False, reason='task not found')
    """
    if new_status not in ALLOWED_STATUSES:
        return False, f"unknown status: {new_status!r}", None
    target: Path | None = None
    for tf in _iter_task_files(company_root):
        if tf.stem == task_id or tf.name == f"{task_id}.md":
            target = tf
            break
        # also try matching by Format A frontmatter task_id or Format B id
        txt = _read_text(tf)
        if not txt:
            continue
        meta, _ = parse_frontmatter(txt)
        if (meta.get("task_id") or "").strip() == task_id:
            target = tf
            break
        table, _ = parse_markdown_table(txt)
        if (table.get("id") or "").strip() == task_id:
            target = tf
            break
    if target is None:
        return False, f"task_id not found: {task_id!r}", None
    # Re-detect format
    txt = target.read_text(encoding="utf-8")
    fmt = detect_format(txt)
    if fmt == "A":
        ok, reason = _patch_format_a(target, new_status)
    elif fmt == "B":
        ok, reason = _patch_format_b(target, new_status)
    else:
        # File no longer matches a known format (edge case) — try A then B
        ok_a, reason_a = _patch_format_a(target, new_status)
        if ok_a:
            return True, reason_a, target
        ok, reason = _patch_format_b(target, new_status)
    return ok, reason, target


# ---- file creation (POST) ----
@_locked
def create_task_file(task_id: str, title: str, assignee: str, priority: str,
                     company_root: Path) -> tuple[bool, str, Path | None]:
    """Create a new task file at 01_projects/mission-control/tasks/<task_id>.md
    with the standard frontmatter. Returns (ok, reason, path)."""
    if assignee not in AGENT_IDS:
        return False, f"unknown assignee: {assignee!r}", None
    safe_id = re.sub(r"[^A-Za-z0-9_.\-]", "-", task_id).strip("-") or f"MC-{int(__import__('time').time())}"
    project_tasks = company_root / "01_projects" / "mission-control" / "tasks"
    project_tasks.mkdir(parents=True, exist_ok=True)
    target = project_tasks / f"{safe_id}.md"
    if target.exists():
        return False, f"file already exists: {target}", None
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    fm_lines = [
        f"task_id: {safe_id}",
        f"title: {title}",
        "project: mission-control",
        "status: triage",
        f"priority: {priority or 'normal'}",
        f"created: {now_iso}",
        "created_by: thor",
        f"assigned_to: [{assignee}]",
        f"current_assignment: {safe_id}",
        "approval_required: true",
        "approval_status: pending",
    ]
    body = f"\n# {title}\n\n(Body TBD — created via Mission Control Kanban UI on {now_iso}.)\n"
    atomic_write_text(target, "---\n" + "\n".join(fm_lines) + "\n---\n" + body)
    return True, "ok", target


# ---- CLI (for debugging) ----
def _main():
    import json
    company_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent.parent
    include_archived = "--archived" in sys.argv
    board = build_board(company_root, include_archived=include_archived)
    print(json.dumps(board, indent=2, default=str)[:6000])


if __name__ == "__main__":
    _main()
