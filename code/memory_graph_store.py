#!/usr/bin/env python3
"""
memory_graph_store.py — SQLite-backed memory graph for Mission Control.

MC-MEMORY-GRAPH-3A-BACKEND (2026-06-17). Stdlib-only.

Replaces the previous JSON-file store with a SQLite database in WAL mode.

Schema:
  nodes   (id PK, kind, label, summary, status, importance, confidence,
           tags JSON, metadata JSON, source, created, updated)
  edges   (id PK, source, target, kind, weight, metadata JSON, created)
  events  (seq PK auto, ts, type, actor, task_id, payload JSON)

Compatibility:
  - On first startup, if `memory-graph.sqlite3` doesn't exist AND
    `memory-graph.json` does, the JSON snapshot is imported into the
    nodes/edges tables. The event log `memory-graph-events.jsonl` is
    appended to the events table.
  - After migration, JSON files are NEVER written to again. JSON reads
    only happen as one-time import or as a defensive fallback.

Threading:
  - All writes go through an internal threading.RLock. The handler runs
    on ThreadingTCPServer threads, so this serialises concurrent writes
    within one process.

Public API:
  - init_store(data_dir) → opens/creates the DB, runs migration if needed.
  - load_graph() → {nodes, edges, last_updated, node_count, edge_count,
                     metadata, ...} (preserves the existing JSON shape).
  - ingest_event(event) → applies one event, returns {ok, ...}.
  - append_event_log(event) → writes a row to events.
  - recent_events(n) → list of last n event rows.
  - reset() → wipes nodes/edges/events.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


log = logging.getLogger("mc.mg_store")

# --- Validation tables ---------------------------------------------------

MG_VALID_NODE_KINDS = {
    "goal", "task", "memory", "decision", "tool", "file",
    "error", "concept", "entity", "session", "message",
    "status", "endpoint",
}

MG_VALID_EVENT_TYPES = {
    "node.upsert", "edge.upsert", "memory.snapshot",
    "node.delete", "edge.delete",
}

_ID_RE = re.compile(r"^[A-Za-z0-9._\-]{1,200}$")


# --- Helpers --------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp01(x: Any, default: float = 0.5) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    if v != v:  # NaN
        return default
    return max(0.0, min(1.0, v))


# --- Validation -----------------------------------------------------------

def validate_node(data: Any) -> tuple[dict, list[str]]:
    """Clean + validate a node dict. Returns (cleaned, errors).

    Rules per spec:
      - id: required, str, 1-200 chars, [A-Za-z0-9._-]
      - kind: required, str, allowed set. Unknown → 'concept' (logged).
      - label: optional str ≤ 500 chars
      - summary: optional str ≤ 5000 chars
      - status: optional str ≤ 100 chars
      - importance: float, clamped 0..1
      - confidence: float, clamped 0..1
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return ({"id": "", "kind": "concept"}, ["node must be a JSON object"])

    cleaned: dict[str, Any] = {}

    nid = (data.get("id") or "").strip() if isinstance(data.get("id"), str) else ""
    if not nid:
        errors.append("node.id is required")
    elif not _ID_RE.match(nid):
        errors.append("node.id must be 1-200 chars of [A-Za-z0-9._-]")
    cleaned["id"] = nid

    nkind = (data.get("kind") or "concept")
    if not isinstance(nkind, str):
        nkind = "concept"
    nkind = nkind.strip().lower()
    if nkind not in MG_VALID_NODE_KINDS:
        log.warning("node %r: unknown kind %r → defaulting to 'concept'", nid, nkind)
        nkind = "concept"
    cleaned["kind"] = nkind

    label = data.get("label")
    if label is None:
        label = ""
    label = str(label)[:500]
    cleaned["label"] = label

    summary = data.get("summary")
    if summary is None:
        summary = ""
    summary = str(summary)[:5000]
    cleaned["summary"] = summary

    status = data.get("status") or "active"
    if not isinstance(status, str):
        status = "active"
    status = status.strip()[:100]
    cleaned["status"] = status

    cleaned["importance"] = _clamp01(data.get("importance"), 0.5)
    cleaned["confidence"] = _clamp01(data.get("confidence"), 0.5)

    tags = data.get("tags")
    if isinstance(tags, list):
        cleaned["tags"] = [str(t) for t in tags if t is not None]
    else:
        cleaned["tags"] = []

    md = data.get("metadata")
    cleaned["metadata"] = md if isinstance(md, dict) else {}

    # Pass-through optional fields used by the existing ingest path.
    for opt in ("assignee", "owner", "project", "path", "url", "source"):
        if opt in data and data[opt] is not None:
            cleaned[opt] = data[opt]

    cleaned["created"] = data.get("created") or _now_iso()
    cleaned["updated"] = _now_iso()
    return cleaned, errors


def validate_edge(data: Any) -> tuple[dict, list[str]]:
    """Clean + validate an edge dict. Returns (cleaned, errors).

    Rules:
      - source: required, str, [A-Za-z0-9._-]
      - target: required, str, [A-Za-z0-9._-]
      - kind:   optional str
      - weight: float, clamped 0..1
      - id:     stable `edge-<source>-<target>-<kind>` if absent
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return ({"id": "", "source": "", "target": ""}, ["edge must be a JSON object"])

    src = (data.get("source") or "")
    if not isinstance(src, str):
        src = str(src)
    src = src.strip()
    if not src:
        errors.append("edge.source is required")

    tgt = (data.get("target") or "")
    if not isinstance(tgt, str):
        tgt = str(tgt)
    tgt = tgt.strip()
    if not tgt:
        errors.append("edge.target is required")

    kind = (data.get("kind") or "relates_to")
    if not isinstance(kind, str):
        kind = "relates_to"
    kind = kind.strip() or "relates_to"

    weight = _clamp01(data.get("weight"), 0.5)

    eid = (data.get("id") or "").strip()
    if not isinstance(data.get("id"), str):
        eid = ""
    eid = eid.strip()
    if not eid:
        eid = f"edge-{src}-{tgt}-{kind}"

    metadata = data.get("metadata")
    md = metadata if isinstance(metadata, dict) else {}

    cleaned = {
        "id": eid,
        "source": src,
        "target": tgt,
        "kind": kind,
        "weight": weight,
        "metadata": md,
        "created": data.get("created") or _now_iso(),
    }
    return cleaned, errors


# --- SQLite store ---------------------------------------------------------

class MemoryGraphStore:
    """Thread-safe SQLite store for the memory graph."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS nodes (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        label TEXT,
        summary TEXT,
        status TEXT,
        importance REAL DEFAULT 0.5,
        confidence REAL DEFAULT 0.5,
        tags TEXT,
        metadata TEXT,
        source TEXT,
        created TEXT,
        updated TEXT
    );
    CREATE TABLE IF NOT EXISTS edges (
        id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        target TEXT NOT NULL,
        kind TEXT,
        weight REAL DEFAULT 0.5,
        metadata TEXT,
        created TEXT
    );
    CREATE TABLE IF NOT EXISTS events (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        type TEXT NOT NULL,
        actor TEXT,
        task_id TEXT,
        payload TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
    CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);
    CREATE INDEX IF NOT EXISTS idx_events_task_id ON events(task_id);
    """

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "memory-graph.sqlite3"
        self.json_path = self.data_dir / "memory-graph.json"
        self.jsonl_path = self.data_dir / "memory-graph-events.jsonl"
        self.sample_path = self.data_dir / "sample-graph.json"
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            isolation_level=None,  # autocommit; we manage transactions
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(self.SCHEMA)
        self._migrated = False

    # ----- migration -----------------------------------------------------

    def migrate_from_json_if_needed(self) -> bool:
        """If the SQLite DB is empty AND a JSON snapshot exists, import it.

        Returns True if anything was migrated.
        """
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM nodes")
            (n_count,) = cur.fetchone()
            if n_count > 0:
                self._migrated = True
                return False

            imported = False
            graph = self._load_json_snapshot_for_migration()
            if graph is None:
                # Try the sample seed as a first-run population.
                graph = self._load_sample_for_migration()
                if graph is not None:
                    log.info("Imported sample-graph.json as first-run seed")
            if graph is not None:
                for n in graph.get("nodes") or []:
                    if isinstance(n, dict) and n.get("id"):
                        self._upsert_node_row(n)
                for e in graph.get("edges") or []:
                    if isinstance(e, dict) and e.get("id"):
                        self._upsert_edge_row(e)
                imported = True

            # Import the JSONL event log if present.
            if self.jsonl_path.is_file():
                try:
                    txt = self.jsonl_path.read_text(encoding="utf-8", errors="replace")
                    for ln in txt.splitlines():
                        ln = ln.strip()
                        if not ln:
                            continue
                        try:
                            obj = json.loads(ln)
                        except Exception:
                            continue
                        if not isinstance(obj, dict):
                            continue
                        self._insert_event_row(
                            ts=obj.get("ts") or _now_iso(),
                            etype=obj.get("type") or "unknown",
                            actor=obj.get("actor"),
                            task_id=obj.get("task_id"),
                            payload=obj,
                        )
                except Exception as e:
                    log.warning("JSONL import failed: %s", e)

            self._migrated = True
            return imported

    def _load_json_snapshot_for_migration(self) -> dict | None:
        if not self.json_path.is_file():
            return None
        try:
            return json.loads(self.json_path.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("Could not read %s: %s", self.json_path, e)
            return None

    def _load_sample_for_migration(self) -> dict | None:
        if not self.sample_path.is_file():
            return None
        try:
            return json.loads(self.sample_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    # ----- low-level row helpers -----------------------------------------

    def _upsert_node_row(self, n: dict) -> None:
        try:
            self._conn.execute(
                """
                INSERT INTO nodes (id, kind, label, summary, status,
                                   importance, confidence, tags, metadata,
                                   source, created, updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  kind=excluded.kind,
                  label=excluded.label,
                  summary=excluded.summary,
                  status=excluded.status,
                  importance=excluded.importance,
                  confidence=excluded.confidence,
                  tags=excluded.tags,
                  metadata=excluded.metadata,
                  source=COALESCE(excluded.source, nodes.source),
                  updated=excluded.updated
                """,
                (
                    n.get("id", ""),
                    n.get("kind", "concept"),
                    n.get("label", ""),
                    n.get("summary", ""),
                    n.get("status", "active"),
                    _clamp01(n.get("importance"), 0.5),
                    _clamp01(n.get("confidence"), 0.5),
                    json.dumps(n.get("tags") or [], ensure_ascii=False),
                    json.dumps(n.get("metadata") or {}, ensure_ascii=False),
                    n.get("source"),
                    n.get("created") or _now_iso(),
                    n.get("updated") or _now_iso(),
                ),
            )
        except Exception as e:
            log.warning("upsert_node_row failed for %r: %s", n.get("id"), e)

    def _upsert_edge_row(self, e: dict) -> None:
        try:
            self._conn.execute(
                """
                INSERT INTO edges (id, source, target, kind, weight,
                                   metadata, created)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  weight=excluded.weight,
                  metadata=excluded.metadata
                """,
                (
                    e.get("id", ""),
                    e.get("source", ""),
                    e.get("target", ""),
                    e.get("kind", "relates_to"),
                    _clamp01(e.get("weight"), 0.5),
                    json.dumps(e.get("metadata") or {}, ensure_ascii=False),
                    e.get("created") or _now_iso(),
                ),
            )
        except Exception as e:
            log.warning("upsert_edge_row failed for %r: %s", e.get("id"), e)

    def _insert_event_row(self, *, ts: str, etype: str, actor: str | None,
                          task_id: str | None, payload: dict) -> None:
        try:
            self._conn.execute(
                "INSERT INTO events (ts, type, actor, task_id, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (ts, etype, actor, task_id,
                 json.dumps(payload, ensure_ascii=False)),
            )
        except Exception as e:
            log.warning("insert_event_row failed: %s", e)

    # ----- public API ----------------------------------------------------

    def load_graph(self) -> dict:
        """Return the full graph in the shape the API contract requires.

        Includes the legacy `node_count` / `edge_count` fields and the
        `metadata` block that the frontend reads.
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, kind, label, summary, status, importance, "
                "confidence, tags, metadata, source, created, updated "
                "FROM nodes ORDER BY id"
            )
            nodes: list[dict] = []
            for row in cur.fetchall():
                (nid, kind, label, summary, status, importance, confidence,
                 tags_json, metadata_json, source, created, updated) = row
                try:
                    tags = json.loads(tags_json) if tags_json else []
                except Exception:
                    tags = []
                try:
                    metadata = json.loads(metadata_json) if metadata_json else {}
                except Exception:
                    metadata = {}
                nd = {
                    "id": nid,
                    "kind": kind,
                    "label": label or "",
                    "summary": summary or "",
                    "status": status or "active",
                    "importance": importance if importance is not None else 0.5,
                    "confidence": confidence if confidence is not None else 0.5,
                    "tags": tags,
                    "metadata": metadata,
                    "created": created,
                    "updated": updated,
                }
                if source:
                    nd["source"] = source
                nodes.append(nd)

            cur = self._conn.execute(
                "SELECT id, source, target, kind, weight, metadata, created "
                "FROM edges ORDER BY id"
            )
            edges: list[dict] = []
            for row in cur.fetchall():
                eid, src, tgt, kind, weight, metadata_json, created = row
                try:
                    metadata = json.loads(metadata_json) if metadata_json else {}
                except Exception:
                    metadata = {}
                edges.append({
                    "id": eid,
                    "source": src,
                    "target": tgt,
                    "kind": kind or "relates_to",
                    "weight": weight if weight is not None else 0.5,
                    "metadata": metadata,
                    "created": created,
                })

            # Last updated = max(updated) over nodes, else now.
            cur = self._conn.execute(
                "SELECT MAX(updated) FROM nodes"
            )
            row = cur.fetchone()
            last_updated = row[0] if row and row[0] else _now_iso()

            return {
                "nodes": nodes,
                "edges": edges,
                "node_count": len(nodes),
                "edge_count": len(edges),
                "last_updated": last_updated,
                "metadata": {
                    "name": "Mission Control Memory Graph",
                    "schema_version": "1.0.0",
                    "source": "sqlite-wal",
                },
            }

    def repair_graph(self) -> int:
        """Create placeholder concept nodes for any edge endpoint that's
        missing. Returns the number of placeholders created."""
        with self._lock:
            cur = self._conn.execute("SELECT id FROM nodes")
            existing = {r[0] for r in cur.fetchall()}
            cur = self._conn.execute("SELECT DISTINCT source FROM edges "
                                     "UNION SELECT DISTINCT target FROM edges")
            referenced = {r[0] for r in cur.fetchall()}
            missing = referenced - existing
            for mid in missing:
                self._upsert_node_row({
                    "id": mid,
                    "kind": "concept",
                    "label": mid,
                    "summary": "(auto-created placeholder)",
                    "status": "active",
                    "importance": 0.3,
                    "confidence": 0.3,
                    "tags": ["placeholder"],
                    "source": "repair",
                    "created": _now_iso(),
                    "updated": _now_iso(),
                })
            return len(missing)

    def ingest_event(self, event: dict) -> dict:
        """Apply one event to the store. Returns {ok, type, applied}.

        Mirrors the previous JSON implementation's behaviour: node.upsert
        merges by id; edge.upsert is idempotent on stable edge id;
        memory.snapshot replaces the whole graph; deletes cascade.
        """
        if not isinstance(event, dict):
            raise ValueError("event must be a JSON object")
        etype = (event.get("type") or "").strip()
        if etype not in MG_VALID_EVENT_TYPES:
            raise ValueError(f"unknown event type: {etype!r}")

        applied = False
        with self._lock:
            if etype == "node.upsert":
                node = event.get("node")
                cleaned, errs = validate_node(node)
                if errs:
                    return {"ok": False, "type": etype, "errors": errs}
                self._upsert_node_row(cleaned)
                applied = True
            elif etype == "edge.upsert":
                edge = event.get("edge")
                cleaned, errs = validate_edge(edge)
                if errs:
                    return {"ok": False, "type": etype, "errors": errs}
                # Dangling-edge tolerance: auto-create placeholder nodes.
                cur = self._conn.execute(
                    "SELECT 1 FROM nodes WHERE id=?", (cleaned["source"],)
                )
                if not cur.fetchone():
                    self._upsert_node_row({
                        "id": cleaned["source"], "kind": "concept",
                        "label": cleaned["source"],
                        "summary": "(auto-created placeholder)",
                        "tags": ["placeholder"], "source": "edge-autofill",
                    })
                cur = self._conn.execute(
                    "SELECT 1 FROM nodes WHERE id=?", (cleaned["target"],)
                )
                if not cur.fetchone():
                    self._upsert_node_row({
                        "id": cleaned["target"], "kind": "concept",
                        "label": cleaned["target"],
                        "summary": "(auto-created placeholder)",
                        "tags": ["placeholder"], "source": "edge-autofill",
                    })
                self._upsert_edge_row(cleaned)
                applied = True
            elif etype == "memory.snapshot":
                snap = event.get("graph")
                if not isinstance(snap, dict):
                    raise ValueError("memory.snapshot requires 'graph' object")
                self._conn.execute("DELETE FROM nodes")
                self._conn.execute("DELETE FROM edges")
                for n in (snap.get("nodes") or []):
                    if isinstance(n, dict):
                        cleaned, errs = validate_node(n)
                        if not errs:
                            self._upsert_node_row(cleaned)
                for e in (snap.get("edges") or []):
                    if isinstance(e, dict):
                        cleaned, errs = validate_edge(e)
                        if not errs:
                            self._upsert_edge_row(cleaned)
                applied = True
            elif etype == "node.delete":
                nid = (event.get("id") or "").strip()
                if not nid:
                    raise ValueError("node.delete requires 'id'")
                cur = self._conn.execute("DELETE FROM nodes WHERE id=?", (nid,))
                applied = cur.rowcount > 0
                self._conn.execute(
                    "DELETE FROM edges WHERE source=? OR target=?", (nid, nid)
                )
            elif etype == "edge.delete":
                eid = (event.get("id") or "").strip()
                if not eid:
                    raise ValueError("edge.delete requires 'id'")
                cur = self._conn.execute("DELETE FROM edges WHERE id=?", (eid,))
                applied = cur.rowcount > 0

            if applied:
                self._insert_event_row(
                    ts=_now_iso(),
                    etype=etype,
                    actor=(event.get("actor") if isinstance(event.get("actor"), str) else None),
                    task_id=(event.get("task_id") if isinstance(event.get("task_id"), str) else None),
                    payload=event,
                )
        return {"ok": applied, "type": etype, "applied": applied}

    def append_event_log(self, event: dict) -> None:
        """Append a row to the events table (best-effort)."""
        with self._lock:
            self._insert_event_row(
                ts=_now_iso(),
                etype=(event.get("type") or "log"),
                actor=None,
                task_id=None,
                payload=event,
            )

    def recent_events(self, n: int = 20) -> list[dict]:
        n = max(1, min(int(n), 200))
        with self._lock:
            cur = self._conn.execute(
                "SELECT ts, type, actor, task_id, payload "
                "FROM events ORDER BY seq DESC LIMIT ?",
                (n,),
            )
            out: list[dict] = []
            for ts, etype, actor, task_id, payload_json in cur.fetchall():
                try:
                    payload = json.loads(payload_json) if payload_json else {}
                except Exception:
                    payload = {"_raw": payload_json}
                out.append({
                    "ts": ts,
                    "type": etype,
                    "actor": actor,
                    "task_id": task_id,
                    "payload": payload,
                })
            out.reverse()
            return out

    def reset(self, *, reseed: bool = True) -> dict:
        """Wipe nodes + edges + events, then re-seed from sample-graph.json.

        Returns the new (post-reset) graph shape. If ``reseed`` is False
        the database is left empty (used for tests). The reset operation
        itself is recorded as a single 'graph_reset' event so the audit
        trail shows when it happened (and by whom, if caller passes actor).
        """
        with self._lock:
            self._conn.execute("DELETE FROM nodes")
            self._conn.execute("DELETE FROM edges")
            self._conn.execute("DELETE FROM events")
            if reseed:
                graph = self._load_sample_for_migration()
                if graph is not None:
                    for n in graph.get("nodes") or []:
                        if isinstance(n, dict) and n.get("id"):
                            self._upsert_node_row(n)
                    for e in graph.get("edges") or []:
                        if isinstance(e, dict) and e.get("id"):
                            self._upsert_edge_row(e)
                # Record the reset as a single event so the Recent Events
                # panel shows "graph was reset at X" instead of going silent.
                self.append_event_log({
                    "type": "graph_reset",
                    "actor": "thor",
                    "note": "Reset to clean sample (17 nodes / 25 edges)",
                    "node_count": self._node_count(),
                    "edge_count": self._edge_count(),
                })
        return self.load_graph()

    def _node_count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM nodes")
        (n,) = cur.fetchone()
        return n

    def _edge_count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM edges")
        (n,) = cur.fetchone()
        return n

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


# --- Module-level singleton ------------------------------------------------

_STORE: MemoryGraphStore | None = None


def init_store(data_dir: Path) -> MemoryGraphStore:
    global _STORE
    if _STORE is None:
        _STORE = MemoryGraphStore(data_dir)
        _STORE.migrate_from_json_if_needed()
    return _STORE


def get_store() -> MemoryGraphStore:
    if _STORE is None:
        raise RuntimeError("memory_graph_store not initialised — call init_store() first")
    return _STORE
