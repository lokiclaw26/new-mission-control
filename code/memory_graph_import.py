#!/usr/bin/env python3
"""
memory_graph_import.py — Ingest NofiTech/Hermes source files into the
GLOBAL memory graph with stable namespaced IDs.

MC-MEMORY-GRAPH-4-GLOBAL (2026-06-17). Stdlib only.

Sources (idempotent, dedup on namespaced IDs):

  - 00_company_os/events.jsonl
  - 00_company_os/memory-log.md + memory-log-*.md
  - 00_company_os/04_agents/state.json
  - 00_company_os/04_agents/events.jsonl (if present)
  - 00_company_os/04_agents/logs/**/*.md
  - 01_projects/*/status.md
  - 01_projects/*/tasks/*.md
  - 01_projects/mission-control/data/memory-graph.json (legacy)
  - mission-control kanban task files (via existing parser)
  - ~/.hermes/cron/output/*/summary.md  (optional — never fail on missing)

CLI:
  python3 code/memory_graph_import.py --full-rebuild
  python3 code/memory_graph_import.py --incremental

Namespaced IDs (prefixes — exactly these strings):
  company:nofitech
  project:<id>
  task:<id>
  agent:<name>          (thor, forge, argus)
  event:<event_id>      (event's task_id or sha1(payload)[:12])
  file:<repo_relative_path>
  decision:<sha1[:12]>
  error:<sha1[:12]>
  session:<YYYY-MM-DD>
  tool:<name>

Edge kinds (exactly these strings):
  contains, assigned_to, created_by, updated_by, emitted_event,
  references_file, depends_on, blocked_by, resolved_by, caused_by,
  uses_tool, produced_artifact, belongs_to_project, happened_in_session

Safety:
  - Allowlisted paths only (HERMES_ALLOWED_ROOTS).
  - Refuse to walk anything else.
  - Redact every string value before writing.
  - No third-party deps; stdlib only.

This module does NOT call any HTTP layer. It is invoked:
  - from the CLI (--full-rebuild / --incremental)
  - from serve.py on startup (incremental only)
  - from tests
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Make sibling modules importable when run as a script.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from memory_graph_global import (  # noqa: E402
    GlobalMemoryGraphStore,
    init_global_store,
    get_global_store,
    assert_safe_path,
    global_db_path,
)
from security import redact_secrets  # noqa: E402

log = logging.getLogger("mc.mg_import")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

# NOFITECH_ROOT env var overrides the production default so tests and CI
# can run on any machine; unset (the production server) keeps the old path.
REPO_ROOT = Path(os.environ.get("NOFITECH_ROOT") or "/home/nofidofi/NofiTech-Ind")
COMPANY_OS = REPO_ROOT / "00_company_os"
PROJECTS_DIR = REPO_ROOT / "01_projects"
HERMES_CRON = Path.home() / ".hermes" / "cron" / "output"

VALID_NODE_KINDS = {
    "goal", "task", "memory", "decision", "tool", "file",
    "error", "concept", "entity", "session", "message",
    "status", "endpoint", "agent", "project", "event", "company",
}

VALID_EDGE_KINDS = {
    "contains", "assigned_to", "created_by", "updated_by",
    "emitted_event", "references_file", "depends_on", "blocked_by",
    "resolved_by", "caused_by", "uses_tool", "produced_artifact",
    "belongs_to_project", "happened_in_session",
}

KNOWN_AGENTS = ("thor", "forge", "argus")

# --- ID helpers ----------------------------------------------------------


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", errors="replace")).hexdigest()


def _id_safe(s: str) -> str:
    """Coerce arbitrary text into a [A-Za-z0-9._-]{1,200} id segment."""
    if not s:
        return "x"
    out = re.sub(r"[^A-Za-z0-9._\-]+", "-", s.strip())
    out = re.sub(r"-+", "-", out).strip("-")
    return (out or "x")[:200]


def _rel_to_repo(p: Path, root: Path | None = None) -> str:
    try:
        rp = p.resolve()
        rr = (root or REPO_ROOT).resolve()
        return str(rp.relative_to(rr))
    except ValueError:
        return str(p)


# --- Frontmatter / markdown helpers --------------------------------------


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Very small YAML-ish frontmatter parser.

    Supports:
      - key: value
      - key: "quoted value"
      - key: [a, b, c]  (inline list)
      - key: true/false
    No nested mappings. Returns (parsed, body).
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    head = m.group(1)
    body = text[m.end():]
    out: dict[str, Any] = {}
    for line in head.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1]
        elif v.startswith("'") and v.endswith("'"):
            v = v[1:-1]
        elif v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            if inner:
                items = [x.strip().strip('"\'') for x in inner.split(",")]
                out[k] = [x for x in items if x]
            else:
                out[k] = []
        elif v.lower() == "true":
            out[k] = True
        elif v.lower() == "false":
            out[k] = False
        else:
            out[k] = v
    return out, body


def _parse_md_table(text: str) -> dict:
    """Parse a | Field | Value | markdown table. Returns {key: value}."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue  # separator row
        key = cells[0].strip("* ").strip()
        val = cells[1].strip()
        if key:
            out[key] = val
    return out


# --- Importer ------------------------------------------------------------


class MemoryGraphImporter:
    """Drives the import.

    Dedup is enforced by the store's primary-key constraints: every
    `upsert_node` / `upsert_edge` is a no-op on duplicate IDs. The
    importer itself keeps a small `_seen_files` set so we don't re-read
    the same file on incremental runs.
    """

    def __init__(self, store: GlobalMemoryGraphStore | None = None,
                 repo_root: Path = REPO_ROOT):
        self.store = store or init_global_store()
        self.repo_root = Path(repo_root)
        self._seen_files: set[str] = set()
        self._stats = {
            "files_seen": 0,
            "files_ingested": 0,
            "files_skipped": 0,
            "nodes_upserted": 0,
            "edges_upserted": 0,
            "events_appended": 0,
        }
        # Always ensure company root + known agents exist.
        self._ensure_company_agents()

    # ----- root/agent scaffolding --------------------------------------

    def _ensure_company_agents(self) -> None:
        self.store.upsert_node({
            "id": "company:nofitech",
            "kind": "company",
            "label": "NofiTech Ind.",
            "summary": "Root company node for the NofiTech Ind. / Hermes Agent memory graph.",
            "importance": 1.0,
            "confidence": 1.0,
            "status": "active",
            "tags": ["company", "nofitech"],
            "source": "importer-bootstrap",
        })
        for a in KNOWN_AGENTS:
            self.store.upsert_node({
                "id": f"agent:{a}",
                "kind": "agent",
                "label": a.capitalize(),
                "summary": f"Agent node for {a} (importer-known).",
                "importance": 0.8,
                "confidence": 0.9,
                "status": "active",
                "tags": ["agent", a],
                "source": "importer-bootstrap",
                "agent": a,
            })
            self.store.upsert_edge({
                "id": f"edge-company:nofitech-agent:{a}-contains",
                "source": "company:nofitech",
                "target": f"agent:{a}",
                "kind": "contains",
                "weight": 0.9,
                "metadata": {"via": "importer-bootstrap"},
            })
            self._stats["edges_upserted"] += 1
        self._stats["nodes_upserted"] += 1 + len(KNOWN_AGENTS)

    def _rel(self, p: Path) -> str:
        """Resolve `p` to a path relative to *this* importer's repo_root."""
        return _rel_to_repo(p, self.repo_root)

    # ----- main entry points -------------------------------------------

    def full_rebuild(self) -> dict:
        """Wipe + re-ingest everything. Idempotent on subsequent runs."""
        log.info("FULL REBUILD starting")
        self.store.reset()
        self._seen_files.clear()
        self._ensure_company_agents()  # reset wiped; re-add.
        self._ingest_all_sources()
        self._audit_event("full_rebuild", stats=self._stats)
        log.info("FULL REBUILD done: %s", self._stats)
        return self._stats

    def incremental(self) -> dict:
        """Re-ingest sources; rely on the store's PK constraints to dedup."""
        log.info("INCREMENTAL ingest starting")
        self._ingest_all_sources()
        self._audit_event("incremental", stats=self._stats)
        log.info("INCREMENTAL done: %s", self._stats)
        return self._stats

    # ----- source dispatcher -------------------------------------------

    def _ingest_all_sources(self) -> None:
        # Honour the configured repo_root (lets tests use a tmp dir).
        company_os = self.repo_root / "00_company_os"
        projects_dir = self.repo_root / "01_projects"
        # 1. Company OS events.jsonl
        self._ingest_company_events_jsonl(company_os / "events.jsonl")
        # 2. memory-log.md + memory-log-*.md
        if (company_os / "memory-log.md").is_file():
            self._ingest_memory_log(company_os / "memory-log.md")
        for p in sorted(company_os.glob("memory-log-*.md")):
            self._ingest_memory_log(p)
        # 3. Agents state.json
        if (company_os / "04_agents" / "state.json").is_file():
            self._ingest_agents_state(company_os / "04_agents" / "state.json")
        # 4. Agents events.jsonl (if present)
        self._ingest_company_events_jsonl(
            company_os / "04_agents" / "events.jsonl", source_label="agent-events"
        )
        # 5. Agent logs/**/*.md
        logs_dir = company_os / "04_agents" / "logs"
        if logs_dir.is_dir():
            for p in sorted(logs_dir.rglob("*.md")):
                self._ingest_agent_log(p)
        # 6. 01_projects/*/status.md
        if projects_dir.is_dir():
            for p in sorted(projects_dir.glob("*/status.md")):
                self._ingest_project_status(p)
            # 7. 01_projects/*/tasks/*.md
            for p in sorted(projects_dir.glob("*/tasks/*.md")):
                self._ingest_task_file(p)
        # 8. mission-control legacy JSON snapshot
        legacy_json = (
            projects_dir / "mission-control" / "data" / "memory-graph.json"
        )
        if legacy_json.is_file():
            self._ingest_legacy_json_snapshot(legacy_json)
        # 9. kanban task files — re-use the same parser for tasks that
        # didn't match the simple frontmatter / table formats.
        self._ingest_kanban_tasks()
        # 10. Optional: ~/.hermes/cron/output/*/summary.md (never fail).
        try:
            if HERMES_CRON.is_dir():
                for p in sorted(HERMES_CRON.glob("*/summary.md")):
                    if assert_safe_path(p):
                        self._ingest_cron_summary(p)
        except Exception as e:
            log.warning("hermes cron output walk skipped: %s", e)

    # ----- per-source ingesters ----------------------------------------

    def _ingest_company_events_jsonl(self, path: Path, source_label: str = "events") -> None:
        if not path.is_file():
            return
        rel = self._rel(path) if path.is_relative_to(REPO_ROOT) else str(path)
        if not assert_safe_path(path):
            log.warning("refusing to read %s (outside allowlist)", path)
            return
        self._seen_files.add(str(path))
        self._stats["files_seen"] += 1
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(ev, dict):
                        continue
                    self._ingest_event_object(ev, source=source_label, source_path=rel)
                    self._stats["files_ingested"] += 1
        except Exception as e:
            log.warning("could not read %s: %s", path, e)

    def _ingest_event_object(self, ev: dict, *, source: str, source_path: str) -> None:
        # Redact first — persisted data is always safe.
        ev = redact_secrets(ev)
        ts = ev.get("ts") or ev.get("timestamp") or _now_iso()
        actor = ev.get("actor")
        task_id = ev.get("task_id")
        project = ev.get("project")
        event_type = ev.get("event_type") or ev.get("type") or "log"
        # Stable event ID.
        seed = task_id or json.dumps(ev, sort_keys=True, ensure_ascii=False)
        eid = f"event:{_id_safe(task_id) if task_id else _sha1(seed)[:12]}"
        # Ensure event node.
        self.store.upsert_node({
            "id": eid,
            "kind": "event",
            "label": f"{event_type} · {task_id or '—'}",
            "summary": (ev.get("message") or ev.get("title") or ev.get("note") or "")[:1500],
            "importance": 0.4,
            "confidence": 0.9,
            "status": str(ev.get("status") or "logged"),
            "tags": ["event", source, event_type],
            "source": source_path,
            "project": project,
            "agent": actor if isinstance(actor, str) else None,
            "created": ts,
        })
        self._stats["nodes_upserted"] += 1
        # Ensure project node + edge.
        if isinstance(project, str) and project:
            self._ensure_project_node(project)
            self.store.upsert_edge({
                "id": f"edge-project:{_id_safe(project)}-{eid}-emitted_event",
                "source": f"project:{_id_safe(project)}",
                "target": eid,
                "kind": "emitted_event",
                "weight": 0.5,
                "metadata": {"event_type": event_type, "source": source_path},
            })
            self._stats["edges_upserted"] += 1
        # Ensure task node + edge.
        if isinstance(task_id, str) and task_id:
            self._ensure_task_node(task_id, project=project)
            self.store.upsert_edge({
                "id": f"edge-task:{_id_safe(task_id)}-{eid}-emitted_event",
                "source": f"task:{_id_safe(task_id)}",
                "target": eid,
                "kind": "emitted_event",
                "weight": 0.7,
                "metadata": {"event_type": event_type},
            })
            self.store.upsert_edge({
                "id": f"edge-event:{_id_safe(task_id) or _sha1(seed)[:12]}-task:{_id_safe(task_id)}-emitted_event",
                "source": eid,
                "target": f"task:{_id_safe(task_id)}",
                "kind": "emitted_event",
                "weight": 0.5,
                "metadata": {"relation": "event_for_task"},
            })
            self._stats["edges_upserted"] += 2
        # Actor edge (agent -> event).
        if isinstance(actor, str) and actor:
            self._ensure_agent_node(actor)
            self.store.upsert_edge({
                "id": f"edge-agent:{_id_safe(actor)}-{eid}-emitted_event",
                "source": f"agent:{_id_safe(actor)}",
                "target": eid,
                "kind": "emitted_event",
                "weight": 0.6,
                "metadata": {"role": "actor"},
            })
            self._stats["edges_upserted"] += 1
        # Log it.
        self.store.append_event(
            event_type=event_type if isinstance(event_type, str) else "log",
            actor=actor if isinstance(actor, str) else None,
            task_id=task_id if isinstance(task_id, str) else None,
            project=project if isinstance(project, str) else None,
            agent=actor if isinstance(actor, str) else None,
            source=source_path,
            payload=ev,
        )
        self._stats["events_appended"] += 1

    def _ingest_memory_log(self, path: Path) -> None:
        if not assert_safe_path(path):
            log.warning("refusing to read %s (outside allowlist)", path)
            return
        self._stats["files_seen"] += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            log.warning("could not read %s: %s", path, e)
            return
        rel = self._rel(path)
        # Split on `### NNN. Title` headings.
        blocks = re.split(r"(?m)^###\s+(\d+)\.\s+(.*)$", text)
        # blocks = [pre, n1, t1, body1, n2, t2, body2, ...]
        if len(blocks) < 4:
            return
        date_guess = _extract_date_from_text(text) or _now_iso()
        for i in range(1, len(blocks), 3):
            try:
                num = blocks[i].strip()
                title = blocks[i + 1].strip()
                body = blocks[i + 2] if i + 2 < len(blocks) else ""
            except IndexError:
                break
            decision_id = f"decision:{_sha1(rel + '|' + num + '|' + title)[:12]}"
            summary = _first_meaningful_line(body)
            self.store.upsert_node({
                "id": decision_id,
                "kind": "decision",
                "label": f"#{num} · {title}",
                "summary": redact_secrets(summary)[:1500],
                "importance": 0.6,
                "confidence": 0.9,
                "status": "logged",
                "tags": ["decision", "memory-log"],
                "source": rel,
                "created": date_guess,
            })
            self._stats["nodes_upserted"] += 1
            # File references the decision.
            self.store.upsert_node({
                "id": f"file:{rel}",
                "kind": "file",
                "label": rel,
                "summary": f"Memory log file {rel}",
                "importance": 0.3,
                "status": "active",
                "tags": ["file"],
                "source": rel,
            })
            self._stats["nodes_upserted"] += 1
            self.store.upsert_edge({
                "id": f"edge-file:{_id_safe(rel)}-{decision_id}-references_file",
                "source": decision_id,
                "target": f"file:{rel}",
                "kind": "references_file",
                "weight": 0.5,
            })
            self._stats["edges_upserted"] += 1
        self._stats["files_ingested"] += 1

    def _ingest_agents_state(self, path: Path) -> None:
        if not assert_safe_path(path):
            log.warning("refusing to read %s (outside allowlist)", path)
            return
        self._stats["files_seen"] += 1
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception as e:
            log.warning("could not read %s: %s", path, e)
            return
        rel = self._rel(path)
        if not isinstance(data, dict):
            return
        agents = data.get("agents") or {}
        for name, info in agents.items():
            if not isinstance(info, dict):
                continue
            self._ensure_agent_node(name)
            # Update with current state.
            self.store.upsert_node({
                "id": f"agent:{_id_safe(name)}",
                "kind": "agent",
                "label": name.capitalize(),
                "summary": f"Agent {name} — {info.get('status', '?')} — "
                           f"current: {info.get('current_assignment') or '—'}",
                "importance": 0.8,
                "confidence": 0.95,
                "status": str(info.get("status") or "active"),
                "tags": ["agent", name],
                "source": rel,
                "agent": name,
                "created": str(info.get("last_activity") or _now_iso()),
            })
            self._stats["nodes_upserted"] += 1
        self._stats["files_ingested"] += 1

    def _ingest_agent_log(self, path: Path) -> None:
        if not assert_safe_path(path):
            log.warning("refusing to read %s (outside allowlist)", path)
            return
        self._stats["files_seen"] += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            log.warning("could not read %s: %s", path, e)
            return
        rel = self._rel(path)
        fm, _ = _parse_frontmatter(text)
        agent = fm.get("agent") or path.stem.split("-")[0]
        task_id = fm.get("task_id")
        status = fm.get("status") or "logged"
        date_dir = None
        try:
            # logs/2026-06-17/<name>.md
            date_dir = path.parent.name
        except Exception:
            date_dir = None
        self._ensure_agent_node(agent)
        # File node.
        self.store.upsert_node({
            "id": f"file:{rel}",
            "kind": "file",
            "label": rel,
            "summary": f"Agent log {rel}",
            "importance": 0.4,
            "status": "active",
            "tags": ["file", "agent-log"],
            "source": rel,
        })
        self._stats["nodes_upserted"] += 1
        # Edge: agent → file (created_by)
        self.store.upsert_edge({
            "id": f"edge-agent:{_id_safe(agent)}-file:{_id_safe(rel)}-created_by",
            "source": f"agent:{_id_safe(agent)}",
            "target": f"file:{rel}",
            "kind": "created_by",
            "weight": 0.7,
        })
        self._stats["edges_upserted"] += 1
        # Session rollup if date_dir matches YYYY-MM-DD.
        if date_dir and re.match(r"^\d{4}-\d{2}-\d{2}$", date_dir):
            sid = f"session:{date_dir}"
            self.store.upsert_node({
                "id": sid,
                "kind": "session",
                "label": f"Session {date_dir}",
                "summary": f"Daily session rollup for {date_dir}",
                "importance": 0.5,
                "confidence": 0.9,
                "status": "active",
                "tags": ["session"],
                "source": "00_company_os/04_agents/logs/",
                "created": f"{date_dir}T00:00:00+00:00",
            })
            self._stats["nodes_upserted"] += 1
            self.store.upsert_edge({
                "id": f"edge-file:{_id_safe(rel)}-{sid}-happened_in_session",
                "source": f"file:{rel}",
                "target": sid,
                "kind": "happened_in_session",
                "weight": 0.5,
            })
            self._stats["edges_upserted"] += 1
        # Task link.
        if task_id and isinstance(task_id, str):
            self._ensure_task_node(task_id)
            self.store.upsert_edge({
                "id": f"edge-agent:{_id_safe(agent)}-task:{_id_safe(task_id)}-assigned_to",
                "source": f"agent:{_id_safe(agent)}",
                "target": f"task:{_id_safe(task_id)}",
                "kind": "assigned_to",
                "weight": 0.7,
            })
            self._stats["edges_upserted"] += 1
            self.store.upsert_edge({
                "id": f"edge-task:{_id_safe(task_id)}-file:{_id_safe(rel)}-references_file",
                "source": f"task:{_id_safe(task_id)}",
                "target": f"file:{rel}",
                "kind": "references_file",
                "weight": 0.5,
            })
            self._stats["edges_upserted"] += 1
        self._stats["files_ingested"] += 1

    def _ingest_project_status(self, path: Path) -> None:
        if not assert_safe_path(path):
            log.warning("refusing to read %s (outside allowlist)", path)
            return
        self._stats["files_seen"] += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            log.warning("could not read %s: %s", path, e)
            return
        rel = self._rel(path)
        fm, body = _parse_frontmatter(text)
        # Some projects use status.md with table format, some with frontmatter.
        meta = dict(fm)
        if not meta:
            meta = _parse_md_table(text)
        project_id = meta.get("id") or path.parent.name
        if not project_id:
            return
        self._ensure_project_node(project_id, meta=meta)
        # Status node.
        sid = f"task:status-{_id_safe(project_id)}"
        self.store.upsert_node({
            "id": sid,
            "kind": "status",
            "label": f"{project_id} status",
            "summary": redact_secrets(
                (meta.get("next_action") or _first_meaningful_line(body) or "")[:1500]
            ),
            "importance": 0.5,
            "status": str(meta.get("status") or "active"),
            "tags": ["status", "project"],
            "source": rel,
            "project": str(project_id),
            "created": str(meta.get("updated") or _now_iso()),
        })
        self._stats["nodes_upserted"] += 1
        # Project → status edge.
        self.store.upsert_edge({
            "id": f"edge-project:{_id_safe(project_id)}-{sid}-contains",
            "source": f"project:{_id_safe(project_id)}",
            "target": sid,
            "kind": "contains",
            "weight": 0.7,
        })
        self._stats["edges_upserted"] += 1
        # File edge.
        self.store.upsert_node({
            "id": f"file:{rel}",
            "kind": "file",
            "label": rel,
            "summary": f"Project status file {rel}",
            "importance": 0.3,
            "status": "active",
            "tags": ["file"],
            "source": rel,
        })
        self._stats["nodes_upserted"] += 1
        self.store.upsert_edge({
            "id": f"edge-project:{_id_safe(project_id)}-file:{_id_safe(rel)}-references_file",
            "source": f"project:{_id_safe(project_id)}",
            "target": f"file:{rel}",
            "kind": "references_file",
            "weight": 0.4,
        })
        self._stats["edges_upserted"] += 1
        self._stats["files_ingested"] += 1

    def _ingest_task_file(self, path: Path) -> None:
        if not assert_safe_path(path):
            log.warning("refusing to read %s (outside allowlist)", path)
            return
        self._stats["files_seen"] += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            log.warning("could not read %s: %s", path, e)
            return
        rel = self._rel(path)
        fm, body = _parse_frontmatter(text)
        meta = dict(fm)
        if not meta or "id" not in meta:
            t = _parse_md_table(text)
            meta.update(t)
        task_id = meta.get("id") or meta.get("task_id") or path.stem
        if not task_id:
            return
        project = meta.get("project") or path.parent.parent.name
        agent = meta.get("agent") or meta.get("assigned_to") or meta.get("owner")
        title = meta.get("title") or path.stem
        status = meta.get("status") or "active"
        priority = meta.get("priority")
        # Ensure task node.
        self._ensure_task_node(task_id, project=project, meta=meta)
        # Update with title + status.
        self.store.upsert_node({
            "id": f"task:{_id_safe(task_id)}",
            "kind": "task",
            "label": str(title),
            "summary": redact_secrets(
                (meta.get("description") or _first_meaningful_line(body) or "")[:1500]
            ),
            "importance": 0.7,
            "confidence": 0.9,
            "status": str(status),
            "tags": ["task", f"project:{project}"] + (
                [f"priority:{priority}"] if priority else []
            ),
            "source": rel,
            "project": str(project) if project else None,
            "agent": str(agent) if agent else None,
            "created": str(meta.get("created") or _now_iso()),
        })
        self._stats["nodes_upserted"] += 1
        # Project contains task.
        if project:
            self._ensure_project_node(project)
            self.store.upsert_edge({
                "id": f"edge-project:{_id_safe(project)}-task:{_id_safe(task_id)}-contains",
                "source": f"project:{_id_safe(project)}",
                "target": f"task:{_id_safe(task_id)}",
                "kind": "contains",
                "weight": 0.8,
            })
            self._stats["edges_upserted"] += 1
        # Agent assigned to task.
        if agent and isinstance(agent, str):
            self._ensure_agent_node(agent)
            self.store.upsert_edge({
                "id": f"edge-agent:{_id_safe(agent)}-task:{_id_safe(task_id)}-assigned_to",
                "source": f"agent:{_id_safe(agent)}",
                "target": f"task:{_id_safe(task_id)}",
                "kind": "assigned_to",
                "weight": 0.7,
            })
            self._stats["edges_upserted"] += 1
        # File node + reference.
        self.store.upsert_node({
            "id": f"file:{rel}",
            "kind": "file",
            "label": rel,
            "summary": f"Task file {rel}",
            "importance": 0.3,
            "status": "active",
            "tags": ["file"],
            "source": rel,
        })
        self._stats["nodes_upserted"] += 1
        self.store.upsert_edge({
            "id": f"edge-task:{_id_safe(task_id)}-file:{_id_safe(rel)}-references_file",
            "source": f"task:{_id_safe(task_id)}",
            "target": f"file:{rel}",
            "kind": "references_file",
            "weight": 0.5,
        })
        self._stats["edges_upserted"] += 1
        self._stats["files_ingested"] += 1

    def _ingest_kanban_tasks(self) -> None:
        """Re-run on the projects' task files; the existing per-file
        ingester already covers them. This is a no-op extension hook for
        the future kanban service integration (see kanban_parser.py)."""
        return

    def _ingest_legacy_json_snapshot(self, path: Path) -> None:
        if not assert_safe_path(path):
            log.warning("refusing to read %s (outside allowlist)", path)
            return
        self._stats["files_seen"] += 1
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception as e:
            log.warning("could not read %s: %s", path, e)
            return
        rel = self._rel(path)
        nodes = data.get("nodes") if isinstance(data, dict) else None
        edges = data.get("edges") if isinstance(data, dict) else None
        if not isinstance(nodes, list) or not isinstance(edges, list):
            return
        # Translate legacy non-namespaced ids to namespaced form where
        # we can guess the kind. Unrecognised kinds stay as concept
        # nodes — they remain in the graph but the user-facing filters
        # default to 'task'/'agent'/'project' which won't show them.
        for n in nodes:
            if not isinstance(n, dict) or not n.get("id"):
                continue
            old_id = n["id"]
            kind = (n.get("kind") or "concept").lower()
            new_id = _translate_legacy_id(old_id, kind)
            if new_id is None:
                continue
            meta = dict(n.get("metadata") or {})
            meta["legacy_id"] = old_id
            n2 = dict(n)
            n2["id"] = new_id
            n2["kind"] = _coerce_kind(kind)
            n2["source"] = rel
            n2["metadata"] = meta
            n2 = redact_secrets(n2)
            self.store.upsert_node(n2)
            self._stats["nodes_upserted"] += 1
        for e in edges:
            if not isinstance(e, dict):
                continue
            src = _translate_legacy_id(e.get("source", ""), guess_kind="")
            tgt = _translate_legacy_id(e.get("target", ""), guess_kind="")
            if not src or not tgt:
                continue
            self.store.upsert_edge({
                "id": f"edge-{src}-{tgt}-{e.get('kind', 'relates_to')}",
                "source": src,
                "target": tgt,
                "kind": e.get("kind") or "relates_to",
                "weight": e.get("weight", 0.5),
                "metadata": {**(e.get("metadata") or {}), "from_legacy": True},
            })
            self._stats["edges_upserted"] += 1
        self._stats["files_ingested"] += 1

    def _ingest_cron_summary(self, path: Path) -> None:
        if not assert_safe_path(path):
            return
        self._stats["files_seen"] += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return
        rel = str(path)  # outside repo, use absolute
        sid = f"file:{rel}"
        self.store.upsert_node({
            "id": sid,
            "kind": "file",
            "label": path.name,
            "summary": redact_secrets(_first_meaningful_line(text))[:500],
            "importance": 0.2,
            "status": "active",
            "tags": ["file", "cron-summary"],
            "source": rel,
        })
        self._stats["nodes_upserted"] += 1
        self._stats["files_ingested"] += 1

    # ----- shared helpers ----------------------------------------------

    def _ensure_project_node(self, project: str, meta: dict | None = None) -> None:
        meta = meta or {}
        pid = f"project:{_id_safe(project)}"
        self.store.upsert_node({
            "id": pid,
            "kind": "project",
            "label": meta.get("title") or project,
            "summary": redact_secrets(
                (meta.get("next_action") or f"Project {project}")[:1500]
            ),
            "importance": 0.6,
            "confidence": 0.9,
            "status": str(meta.get("status") or "active"),
            "tags": ["project", f"id:{project}"],
            "source": "importer",
            "project": str(project),
            "created": str(meta.get("created") or _now_iso()),
        })
        # Company contains project.
        self.store.upsert_edge({
            "id": f"edge-company:nofitech-{pid}-contains",
            "source": "company:nofitech",
            "target": pid,
            "kind": "contains",
            "weight": 0.9,
        })

    def _ensure_task_node(self, task_id: str, project: str | None = None,
                          meta: dict | None = None) -> None:
        meta = meta or {}
        tid = f"task:{_id_safe(task_id)}"
        self.store.upsert_node({
            "id": tid,
            "kind": "task",
            "label": meta.get("title") or task_id,
            "summary": redact_secrets(
                (meta.get("description") or f"Task {task_id}")[:1500]
            ),
            "importance": 0.6,
            "confidence": 0.8,
            "status": str(meta.get("status") or "active"),
            "tags": ["task"],
            "source": "importer",
            "project": str(project) if project else None,
            "created": str(meta.get("created") or _now_iso()),
        })

    def _ensure_agent_node(self, agent: str) -> None:
        aid = f"agent:{_id_safe(agent)}"
        self.store.upsert_node({
            "id": aid,
            "kind": "agent",
            "label": str(agent).capitalize(),
            "summary": f"Agent {agent}",
            "importance": 0.7,
            "confidence": 0.8,
            "status": "active",
            "tags": ["agent", str(agent)],
            "source": "importer",
            "agent": str(agent),
        })

    def _audit_event(self, kind: str, *, stats: dict) -> None:
        self.store.append_event(
            event_type=kind,
            actor="importer",
            task_id=None,
            project=None,
            agent=None,
            source="memory_graph_import.py",
            payload={"stats": dict(stats)},
        )


# --- misc helpers --------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first_meaningful_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#") or line.startswith("---"):
            continue
        return line
    return ""


def _extract_date_from_text(text: str) -> str | None:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            ).isoformat()
        except ValueError:
            return None
    return None


def _coerce_kind(kind: str) -> str:
    k = (kind or "concept").lower()
    return k if k in VALID_NODE_KINDS else "concept"


def _translate_legacy_id(old_id: str, kind: str | None = None,
                         guess_kind: str = "") -> str | None:
    """Translate a legacy (non-namespaced) id into a stable namespaced
    id. Returns None if we can't safely translate.

    Heuristics:
      - Already namespaced (contains ':') → keep.
      - 'agent-*' → 'agent:<x>'.
      - Starts with 'task' or matches MC-* or DIY-* → 'task:<x>'.
      - Otherwise return None (skip — better than polluting the graph).
    """
    if not old_id:
        return None
    if ":" in old_id:
        return old_id
    low = old_id.lower()
    if low.startswith("agent-"):
        rest = old_id[len("agent-"):]
        return f"agent:{_id_safe(rest)}"
    if kind and kind.lower() == "agent":
        return f"agent:{_id_safe(old_id)}"
    if low.startswith("task-") or re.match(r"^(MC|DIY|RL)-", old_id):
        return f"task:{_id_safe(old_id)}"
    if kind and kind.lower() == "task":
        return f"task:{_id_safe(old_id)}"
    if kind and kind.lower() in ("entity", "concept") and guess_kind:
        return f"{guess_kind}:{_id_safe(old_id)}"
    return None


# --- CLI -----------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="NofiTech memory graph importer")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--full-rebuild", action="store_true",
                   help="Wipe + re-ingest all sources")
    g.add_argument("--incremental", action="store_true",
                   help="Re-ingest (idempotent)")
    p.add_argument("--db", type=str, default=None,
                   help="Override the global DB path (testing)")
    p.add_argument("--repo", type=str, default=None,
                   help="Override the repo root (testing)")
    p.add_argument("--quiet", action="store_true", help="Less log output")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)
    db_path = Path(args.db).expanduser().resolve() if args.db else None
    repo_root = Path(args.repo).expanduser().resolve() if args.repo else REPO_ROOT
    if db_path is not None:
        # Allow override (used by tests against tmp dirs).
        if not assert_safe_path(db_path):
            print(f"refusing to open DB outside allowlist: {db_path}", file=sys.stderr)
            return 2
        store = GlobalMemoryGraphStore(db_path)
    else:
        store = init_global_store()
    importer = MemoryGraphImporter(store=store, repo_root=repo_root)
    if args.full_rebuild:
        stats = importer.full_rebuild()
    else:
        stats = importer.incremental()
    print(json.dumps({"ok": True, "stats": stats}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
