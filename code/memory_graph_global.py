#!/usr/bin/env python3
"""
memory_graph_global.py — Global Hermes Agent / NofiTech memory graph.

MC-MEMORY-GRAPH-4-GLOBAL (2026-06-17).

Authoritative storage now lives at a global path:
    00_company_os/memory/memory-graph.sqlite3

This module is a thin wrapper over the same SQLite WAL schema the
project-local `memory_graph_store.MemoryGraphStore` uses, but it opens
the global DB and exposes SCOPED queries:

    - load_scoped(scope, project, agent, kind, since, until, importance)
        scope ∈ {all, project, agent, kind, session}
        (kind is a comma-separated multi-value; project/agent are single)

    - node_count / edge_count
    - repair_graph() (auto-create placeholders for missing endpoints)

The legacy `data/memory-graph.sqlite3` is left intact and tagged
"legacy" — no double writes. If the global DB doesn't exist yet,
this module initialises it (idempotent) and seeds it from the legacy
JSON snapshot (data/memory-graph.json) and the sample seed, then the
importer fills the rest on top.

Namespaced stable IDs are produced by the importer (see
`memory_graph_import.py`); the store itself is content-agnostic and
accepts any [A-Za-z0-9._-]{1,200} id, matching the existing schema.

The existing `memory_graph_store.py` public API is NOT touched. The
existing `MemoryGraphAPI` is what HTTP handlers call; we change it to
read from this global store when the request comes in.

Stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("mc.mg_global")

# --- Allowed path roots for safety checks -----------------------------
_REPO_ROOT = Path("/home/nofidofi/NofiTech-Ind")
_ALLOWED_ROOTS = (
    _REPO_ROOT,
    Path.home() / ".hermes" / "cron" / "output",
)


# --- Path resolution ---------------------------------------------------

def global_dir() -> Path:
    """Return the absolute path to the global memory directory.

    Override via env: ``HERMES_GLOBAL_MEMORY_DIR``.
    """
    override = (os.environ.get("HERMES_GLOBAL_MEMORY_DIR") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (_REPO_ROOT / "00_company_os" / "memory").resolve()


def global_db_path() -> Path:
    """Return the absolute path to the global SQLite file."""
    return global_dir() / "memory-graph.sqlite3"


def legacy_db_path() -> Path | None:
    """Return the legacy project-local SQLite path, if it exists.

    The legacy file is left on disk for backward compatibility (it's
    still a read-only cache for the Mission Control UI, if anything
    reads it). Returns ``None`` if the path does not exist.
    """
    candidate = _REPO_ROOT / "01_projects" / "mission-control" / "data" / "memory-graph.sqlite3"
    if candidate.is_file():
        return candidate
    return None


def assert_safe_path(p: Path) -> bool:
    """Return True iff `p` is inside an allowlisted root.

    Use this on every read/write before touching a file. The importer
    and any other source-crawler must call this for every path.
    """
    try:
        rp = p.resolve()
    except Exception:
        return False
    for root in _ALLOWED_ROOTS:
        try:
            rp.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


# --- Store -------------------------------------------------------------

class GlobalMemoryGraphStore:
    """Thread-safe SQLite store for the GLOBAL memory graph.

    Same schema as the legacy store; separate on-disk file. All writes
    go through an internal RLock. A repository-scoped helper to obtain
    a singleton lives at the bottom of this module.
    """

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
        project TEXT,
        agent TEXT,
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
        project TEXT,
        agent TEXT,
        source TEXT,
        payload TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);
    CREATE INDEX IF NOT EXISTS idx_nodes_project ON nodes(project);
    CREATE INDEX IF NOT EXISTS idx_nodes_agent ON nodes(agent);
    CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
    CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);
    CREATE INDEX IF NOT EXISTS idx_edges_kind ON edges(kind);
    CREATE INDEX IF NOT EXISTS idx_events_task_id ON events(task_id);
    CREATE INDEX IF NOT EXISTS idx_events_project ON events(project);
    CREATE INDEX IF NOT EXISTS idx_events_agent ON events(agent);
    """

    def __init__(self, db_path: Path | None = None, *, register: bool = True):
        self.db_path = (db_path or global_db_path())
        # Safety: the global DB must live under an allowlisted root.
        if not assert_safe_path(self.db_path):
            raise RuntimeError(
                f"refusing to open global DB outside allowlisted roots: {self.db_path}"
            )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            isolation_level=None,  # autocommit; we manage transactions
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(self.SCHEMA)
        self._maybe_bootstrap_from_legacy()
        # Track the most-recently-instantiated store so helpers like
        # `load_scoped_from_request` can find it without forcing a
        # caller to wire the singleton. We don't close previous
        # instances — that's the caller's responsibility.
        if register:
            global _STORE, _LAST_INSTANCE
            _STORE = self
            _LAST_INSTANCE = self

    # ----- bootstrap ----------------------------------------------------

    def _maybe_bootstrap_from_legacy(self) -> None:
        """One-time seed from the legacy project-local SQLite (if present
        and the global DB is empty).

        The legacy store is the source of truth for previously-collected
        data. We snapshot nodes+edges into the global DB so the rest of
        the system has a single read path. The legacy file is left in
        place and tagged "legacy" in the importer audit log.
        """
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM nodes")
            (n_count,) = cur.fetchone()
            if n_count > 0:
                return
            legacy = legacy_db_path()
            if legacy is None:
                return
            try:
                lc = sqlite3.connect(str(legacy))
                rows = lc.execute(
                    "SELECT id, kind, label, summary, status, importance, "
                    "confidence, tags, metadata, source, created, updated "
                    "FROM nodes"
                ).fetchall()
                for row in rows:
                    try:
                        self._conn.execute(
                            "INSERT OR IGNORE INTO nodes (id, kind, label, "
                            "summary, status, importance, confidence, tags, "
                            "metadata, source, created, updated) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            row,
                        )
                    except Exception as e:
                        log.warning("legacy node copy failed for %r: %s", row[0], e)
                erows = lc.execute(
                    "SELECT id, source, target, kind, weight, metadata, created "
                    "FROM edges"
                ).fetchall()
                for row in erows:
                    try:
                        self._conn.execute(
                            "INSERT OR IGNORE INTO edges (id, source, target, "
                            "kind, weight, metadata, created) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                            row,
                        )
                    except Exception as e:
                        log.warning("legacy edge copy failed for %r: %s", row[0], e)
                lc.close()
            except Exception as e:
                log.warning("legacy snapshot seed failed: %s", e)

    # ----- low-level helpers -------------------------------------------

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _clamp01(x: Any, default: float = 0.5) -> float:
        try:
            v = float(x)
        except (TypeError, ValueError):
            return default
        if v != v:
            return default
        return max(0.0, min(1.0, v))

    def upsert_node(self, n: dict) -> bool:
        """Insert/replace one node. Idempotent on `id`."""
        if not isinstance(n, dict):
            return False
        nid = (n.get("id") or "").strip()
        if not nid:
            return False
        with self._lock:
            try:
                self._conn.execute(
                    """
                    INSERT INTO nodes (id, kind, label, summary, status,
                                       importance, confidence, tags, metadata,
                                       source, project, agent, created, updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                      project=COALESCE(excluded.project, nodes.project),
                      agent=COALESCE(excluded.agent, nodes.agent),
                      updated=COALESCE(NULLIF(excluded.updated, ''), nodes.updated)
                    """,
                    (
                        nid,
                        n.get("kind", "concept") or "concept",
                        (n.get("label") or "")[:500],
                        (n.get("summary") or "")[:5000],
                        (n.get("status") or "active"),
                        self._clamp01(n.get("importance"), 0.5),
                        self._clamp01(n.get("confidence"), 0.5),
                        json.dumps(n.get("tags") or [], ensure_ascii=False),
                        json.dumps(n.get("metadata") or {}, ensure_ascii=False),
                        n.get("source"),
                        n.get("project"),
                        n.get("agent"),
                        n.get("created") or self._now_iso(),
                        # updated: respect caller's value; when caller passes
                        # nothing, stamp the same ISO as `created` so that
                        # MAX(updated) reflects real ingest activity
                        # (MC-MEMORY-GRAPH-LASTUPDATED-FIX 2026-06-26).
                        (n.get("updated") or n.get("created") or self._now_iso()),
                    ),
                )
                return True
            except Exception as e:
                log.warning("upsert_node failed for %r: %s", nid, e)
                return False

    def upsert_edge(self, e: dict) -> bool:
        if not isinstance(e, dict):
            return False
        src = (e.get("source") or "").strip()
        tgt = (e.get("target") or "").strip()
        if not src or not tgt:
            return False
        eid = (e.get("id") or "").strip() or f"edge-{src}-{tgt}-{e.get('kind', 'relates_to')}"
        with self._lock:
            try:
                self._conn.execute(
                    """
                    INSERT INTO edges (id, source, target, kind, weight,
                                       metadata, created)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                      source=excluded.source,
                      target=excluded.target,
                      kind=excluded.kind,
                      weight=excluded.weight,
                      metadata=excluded.metadata
                    """,
                    (
                        eid,
                        src,
                        tgt,
                        e.get("kind", "relates_to"),
                        self._clamp01(e.get("weight"), 0.5),
                        json.dumps(e.get("metadata") or {}, ensure_ascii=False),
                        e.get("created") or self._now_iso(),
                    ),
                )
                return True
            except Exception as e:
                log.warning("upsert_edge failed for %r: %s", eid, e)
                return False

    def append_event(self, *, event_type: str, actor: str | None,
                     task_id: str | None, project: str | None,
                     agent: str | None, source: str | None,
                     payload: dict) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO events (ts, type, actor, task_id, project, "
                    "agent, source, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        self._now_iso(),
                        event_type or "log",
                        actor,
                        task_id,
                        project,
                        agent,
                        source,
                        json.dumps(payload, ensure_ascii=False),
                    ),
                )
            except Exception as e:
                log.warning("append_event failed: %s", e)

    def has_node(self, nid: str) -> bool:
        with self._lock:
            cur = self._conn.execute("SELECT 1 FROM nodes WHERE id=?", (nid,))
            return cur.fetchone() is not None

    def node_count(self) -> int:
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM nodes")
            (n,) = cur.fetchone()
            return int(n)

    def edge_count(self) -> int:
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM edges")
            (n,) = cur.fetchone()
            return int(n)

    def last_updated(self) -> str:
        # MC-MEMORY-GRAPH-LASTUPDATED-FIX (2026-06-26): fall back to MAX(created)
        # when MAX(updated) is empty/stale. The kanban-bridge upserts nodes
        # without setting `updated`, so MAX(updated) can lag by days even when
        # the graph is actively growing. MAX(created) is always populated by
        # the upsert SQL DEFAULT and reflects real ingest activity.
        with self._lock:
            cur = self._conn.execute(
                "SELECT MAX(updated), MAX(created) FROM nodes"
            )
            row = cur.fetchone()
            mx_upd = row[0] if row and row[0] else ""
            mx_new = row[1] if row and row[1] else ""
            # Pick whichever is newer; both are ISO 8601 so string compare works.
            chosen = mx_upd if mx_upd > mx_new else mx_new
            return chosen or self._now_iso()

    # ----- scoped queries ----------------------------------------------

    @staticmethod
    def _norm_iso(s: str | None) -> str | None:
        if not s:
            return None
        try:
            # Accept YYYY-MM-DD or full ISO. Return canonical ISO Z.
            if len(s) == 10:
                return s + "T00:00:00+00:00"
            return s
        except Exception:
            return None

    def _build_where(self, *, scope: str, project: str | None,
                     agent: str | None, kind: list[str] | None,
                     since: str | None, until: str | None,
                     importance: float | None,
                     project_match: str = "exact",
                     agent_match: str = "exact") -> tuple[str, list]:
        """Return (where_clause, params) for a node SELECT.

        `project_match`:
          - "exact": metadata.project == project OR id == "project:<project>"
          - "contains": metadata LIKE '%<project>%' OR label/summary LIKE
        `agent_match`:
          - "exact": metadata.agent == agent OR id == "agent:<agent>"
          - "contains": metadata LIKE '%<agent>%' OR label/summary LIKE
        """
        where: list[str] = []
        params: list = []
        if scope == "session":
            # Last 24h only.
            since = since or (
                datetime.fromtimestamp(
                    datetime.now(timezone.utc).timestamp() - 24 * 3600,
                    tz=timezone.utc,
                ).isoformat()
            )
        if project:
            if project_match == "exact":
                where.append(
                    "(project = ? OR id = ? OR (tags LIKE ? AND ? = ?))"
                )
                pid = f"project:{project}"
                tag_blob = f'%"{project}"%'
                params.extend([project, pid, tag_blob, project, project])
            else:
                where.append("(project LIKE ? OR id LIKE ? OR label LIKE ? OR summary LIKE ?)")
                pat = f"%{project}%"
                params.extend([pat, f"project:{project}", pat, pat])
        if agent:
            if agent_match == "exact":
                where.append(
                    "(agent = ? OR id = ? OR (tags LIKE ? AND ? = ?))"
                )
                aid = f"agent:{agent}"
                tag_blob = f'%"{agent}"%'
                params.extend([agent, aid, tag_blob, agent, agent])
            else:
                where.append("(agent LIKE ? OR id LIKE ? OR label LIKE ? OR summary LIKE ?)")
                pat = f"%{agent}%"
                params.extend([pat, f"agent:{agent}", pat, pat])
        if kind:
            placeholders = ",".join("?" for _ in kind)
            where.append(f"kind IN ({placeholders})")
            params.extend([k.strip().lower() for k in kind if k.strip()])
        if since:
            si = self._norm_iso(since)
            if si:
                where.append("updated >= ?")
                params.append(si)
        if until:
            ui = self._norm_iso(until)
            if ui:
                where.append("updated <= ?")
                params.append(ui)
        if importance is not None:
            try:
                imp = max(0.0, min(1.0, float(importance)))
            except (TypeError, ValueError):
                imp = 0.0
            where.append("importance >= ?")
            params.append(imp)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        return clause, params

    def load_scoped(self, *, scope: str = "all", project: str | None = None,
                    agent: str | None = None, kind: str | None = None,
                    since: str | None = None, until: str | None = None,
                    importance: float | None = None) -> dict:
        """Return a graph dict filtered by the given scope + filters.

        `scope` is one of: all, project, agent, kind, session.
        `kind` may be a comma-separated multi-value.
        `importance` is a 0..1 floor.
        """
        scope = (scope or "all").strip().lower()
        kind_list: list[str] = []
        if kind:
            kind_list = [k.strip() for k in kind.split(",") if k.strip()]
        # "scope" picks the primary filter, but the per-field filters
        # are still applied on top.
        scoped_project = project
        scoped_agent = agent
        scoped_kind = kind_list or None
        if scope == "project" and not scoped_project:
            scoped_project = "mission-control"  # default sentinel
        elif scope == "agent" and not scoped_agent:
            scoped_agent = "forge"
        elif scope == "kind" and not scoped_kind:
            scoped_kind = ["task"]
        elif scope == "session":
            # Last 24h; kind is left as-is.
            scoped_kind = scoped_kind or None

        node_where, node_params = self._build_where(
            scope=scope, project=scoped_project, agent=scoped_agent,
            kind=scoped_kind, since=since, until=until,
            importance=importance,
        )
        with self._lock:
            cur = self._conn.execute(
                "SELECT id, kind, label, summary, status, importance, "
                "confidence, tags, metadata, source, project, agent, "
                "created, updated FROM nodes "
                + node_where + " ORDER BY id",
                node_params,
            )
            nodes: list[dict] = []
            ids: set[str] = set()
            for row in cur.fetchall():
                (nid, kind, label, summary, status, importance, confidence,
                 tags_json, metadata_json, source, project_v, agent_v,
                 created, updated) = row
                ids.add(nid)
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
                    "kind": kind or "concept",
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
                if project_v:
                    nd["project"] = project_v
                if agent_v:
                    nd["agent"] = agent_v
                nodes.append(nd)

            # Edges: keep only those with both endpoints in the visible set.
            # We additionally filter on edge kind if any of the node kind
            # filters indicate so (edge.kind is not in our filter, so we
            # don't filter on it). Optional edge kind filter via metadata.
            if ids:
                placeholders = ",".join("?" for _ in ids)
                cur = self._conn.execute(
                    "SELECT id, source, target, kind, weight, metadata, created "
                    "FROM edges WHERE source IN (" + placeholders + ") "
                    "AND target IN (" + placeholders + ") ORDER BY id",
                    list(ids) + list(ids),
                )
            else:
                cur = self._conn.execute(
                    "SELECT id, source, target, kind, weight, metadata, created "
                    "FROM edges WHERE 0"
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

            last_updated = self.last_updated()
            scope_label = self._scope_label(scope, project, agent,
                                            kind_list, since, until)
            return {
                "nodes": nodes,
                "edges": edges,
                "node_count": len(nodes),
                "edge_count": len(edges),
                "last_updated": last_updated,
                "metadata": {
                    "name": "Hermes Agent Memory Graph",
                    "schema_version": "2.0.0",
                    "source": "sqlite-wal-global",
                    "scope": scope,
                    "scope_label": scope_label,
                    "project": scoped_project,
                    "agent": scoped_agent,
                    "kind": kind_list,
                    "since": since,
                    "until": until,
                    "importance": importance,
                },
            }

    @staticmethod
    def _scope_label(scope: str, project: str | None, agent: str | None,
                     kind_list: list[str] | None, since: str | None,
                     until: str | None) -> str:
        if scope == "all":
            return "Full Hermes Memory"
        if scope == "project":
            return f"Project: {project or 'mission-control'}"
        if scope == "agent":
            return f"Agent: {agent or 'forge'}"
        if scope == "kind":
            return f"Kind: {','.join(kind_list) if kind_list else 'task'}"
        if scope == "session":
            return "Recent Session (last 24h)"
        return f"Scope: {scope}"

    def repair_graph(self) -> int:
        """Create placeholder concept nodes for missing edge endpoints."""
        with self._lock:
            cur = self._conn.execute("SELECT id FROM nodes")
            existing = {r[0] for r in cur.fetchall()}
            cur = self._conn.execute(
                "SELECT DISTINCT source FROM edges "
                "UNION SELECT DISTINCT target FROM edges"
            )
            referenced = {r[0] for r in cur.fetchall()}
            missing = referenced - existing
            for mid in missing:
                self.upsert_node({
                    "id": mid,
                    "kind": "concept",
                    "label": mid,
                    "summary": "(auto-created placeholder)",
                    "status": "active",
                    "importance": 0.3,
                    "confidence": 0.3,
                    "tags": ["placeholder"],
                    "source": "global-repair",
                })
            return len(missing)

    def counts_by_kind(self) -> dict[str, int]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT kind, COUNT(*) FROM nodes GROUP BY kind ORDER BY 2 DESC"
            )
            return {r[0]: int(r[1]) for r in cur.fetchall()}

    # ----- bulk filesystem seed (MC-LIVE-MEMORY-GRAPH-1, 2026-06-19) ---

    def bulk_seed(self, *, repo_root: Path | None = None,
                  max_event_lines: int = 5000) -> dict:
        """One-shot filesystem walk that ingests the real NofiTech
        artifacts as nodes + edges.

        Idempotent: every upsert is a no-op on duplicate IDs.

        Sources:
          - 00_company_os/04_agents/*.md           -> agent nodes
          - 00_company_os/01_projects/*            -> project nodes
          - 01_projects/*/                         -> project nodes
          - 01_projects/*/tasks/*.md               -> task nodes
          - 00_company_os/02_tasks/                -> task nodes (alt)
          - 00_company_os/04_agents/events.jsonl   -> event nodes
          - 00_company_os/events.jsonl             -> event nodes
          - 00_company_os/05_knowledge/            -> knowledge nodes
          - 00_company_os/charter.md, activation-protocol.md,
            auto-kanban-rule.md, event-schema.md, task-schema.md,
            token-budget-mode.md, stage-12-plan.md,
            memory-log.md, memory-log-*.md          -> concept nodes
          - 00_company_os/04_agents/state.json     -> agent state
          - 00_company_os/04_agents/logs/**/*.md   -> log nodes

        Target: 100+ real nodes after one full run.

        Returns a stats dict with the counts.
        """
        from memory_graph_global import assert_safe_path  # local

        repo = Path(repo_root) if repo_root else Path("/home/nofidofi/NofiTech-Ind")
        if not assert_safe_path(repo):
            return {"error": f"refusing to walk outside allowlist: {repo}"}

        stats = {
            "agents": 0,
            "projects": 0,
            "tasks": 0,
            "events": 0,
            "knowledge": 0,
            "logs": 0,
            "company_files": 0,
            "edges": 0,
            "skipped": 0,
            "skipped_existing": 0,
        }

        # Ensure company + agent scaffolding exists.
        self.upsert_node({
            "id": "company:nofitech",
            "kind": "company",
            "label": "NofiTech Ind.",
            "summary": "Root company node for the NofiTech Ind. / Hermes Agent memory graph.",
            "importance": 1.0,
            "confidence": 1.0,
            "status": "active",
            "tags": ["company", "nofitech"],
            "source": "bulk_seed",
        })
        known_agents = ("thor", "forge", "argus")
        for a in known_agents:
            self.upsert_node({
                "id": f"agent:{a}",
                "kind": "agent",
                "label": a.capitalize(),
                "summary": f"Agent node for {a} (bulk_seed bootstrap).",
                "importance": 0.8,
                "confidence": 0.9,
                "status": "active",
                "tags": ["agent", a],
                "source": "bulk_seed",
                "agent": a,
            })
            self.upsert_edge({
                "id": f"edge-company:nofitech-agent:{a}-contains",
                "source": "company:nofitech",
                "target": f"agent:{a}",
                "kind": "contains",
                "weight": 0.9,
                "metadata": {"via": "bulk_seed"},
            })
            stats["agents"] += 1
            stats["edges"] += 1

        # ----- 1. agents/*.md -----
        agents_dir = repo / "00_company_os" / "04_agents"
        if agents_dir.is_dir():
            for md in sorted(agents_dir.glob("*.md")):
                try:
                    text = md.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    stats["skipped"] += 1
                    continue
                # Extract title from first H1 or filename
                name = md.stem
                title = name.capitalize()
                for line in text.splitlines():
                    if line.startswith("# "):
                        title = line[2:].strip()
                        break
                self.upsert_node({
                    "id": f"agent_md:{name}",
                    "kind": "file",
                    "label": f"{title} (agent file)",
                    "summary": (text[:500]).strip(),
                    "importance": 0.6,
                    "confidence": 0.9,
                    "status": "active",
                    "tags": ["agent", "file", name],
                    "source": f"00_company_os/04_agents/{md.name}",
                })
                # Link to the corresponding agent
                if name in known_agents:
                    self.upsert_edge({
                        "id": f"edge-agent:{name}-agent_md:{name}-references_file",
                        "source": f"agent:{name}",
                        "target": f"agent_md:{name}",
                        "kind": "references_file",
                        "weight": 0.7,
                    })
                    stats["edges"] += 1
                else:
                    self.upsert_edge({
                        "id": f"edge-company:nofitech-agent_md:{name}-contains",
                        "source": "company:nofitech",
                        "target": f"agent_md:{name}",
                        "kind": "contains",
                        "weight": 0.5,
                    })
                    stats["edges"] += 1
                stats["knowledge"] += 1

        # ----- 2. projects -----
        projects_seen: set[str] = set()

        def _project_node(proj_id: str, rel_path: str, *,
                          label: str | None = None,
                          summary: str | None = None) -> None:
            if proj_id in projects_seen:
                return
            projects_seen.add(proj_id)
            self.upsert_node({
                "id": f"project:{proj_id}",
                "kind": "project",
                "label": label or proj_id,
                "summary": summary or f"Project: {proj_id}",
                "importance": 0.7,
                "confidence": 0.9,
                "status": "active",
                "tags": ["project", proj_id],
                "source": rel_path,
                "project": proj_id,
            })
            self.upsert_edge({
                "id": f"edge-company:nofitech-project:{proj_id}-contains",
                "source": "company:nofitech",
                "target": f"project:{proj_id}",
                "kind": "contains",
                "weight": 0.8,
                "metadata": {"via": "bulk_seed"},
            })
            stats["projects"] += 1
            stats["edges"] += 1

        # 00_company_os/01_projects/*
        co_projects = repo / "00_company_os" / "01_projects"
        if co_projects.is_dir():
            for p in sorted(co_projects.iterdir()):
                if p.is_dir() and not p.name.startswith("."):
                    _project_node(p.name, f"00_company_os/01_projects/{p.name}/")

        # 01_projects/*
        top_projects = repo / "01_projects"
        if top_projects.is_dir():
            for p in sorted(top_projects.iterdir()):
                if p.is_dir() and not p.name.startswith("."):
                    # read status.md / plan.md / README.md for a summary if present
                    summary = None
                    for fname in ("status.md", "plan.md", "README.md"):
                        f = p / fname
                        if f.is_file():
                            try:
                                summary = f.read_text(encoding="utf-8", errors="replace")[:400]
                                break
                            except Exception:
                                pass
                    _project_node(p.name, f"01_projects/{p.name}/", summary=summary)

        # ----- 3. tasks -----
        def _task_id_safe(s: str) -> str:
            out = re.sub(r"[^A-Za-z0-9._\-]+", "-", (s or "").strip())
            out = re.sub(r"-+", "-", out).strip("-")
            return (out or "x")[:200]

        def _ingest_task_file(md: Path, default_project: str | None) -> None:
            try:
                text = md.read_text(encoding="utf-8", errors="replace")
            except Exception:
                stats["skipped"] += 1
                return
            # Try YAML frontmatter first (Format A)
            task_id = None
            project_id = default_project
            status = None
            priority = None
            title = md.stem
            assignee = None
            fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
            if fm_match:
                head = fm_match.group(1)
                for line in head.splitlines():
                    if ":" not in line:
                        continue
                    k, _, v = line.partition(":")
                    k = k.strip().lower()
                    v = v.strip().strip('"\'')
                    if k == "id" or k == "task_id":
                        task_id = v
                    elif k == "title":
                        title = v
                    elif k == "project":
                        project_id = v or project_id
                    elif k == "status" or k == "kanban_status":
                        status = v
                    elif k == "priority":
                        priority = v
                    elif k in ("assigned_to", "owner", "assignee"):
                        assignee = v.lower() if v else None
            else:
                # Try Format B markdown table
                for line in text.splitlines()[:30]:
                    line = line.strip()
                    if not line.startswith("|"):
                        continue
                    cells = [c.strip() for c in line.strip("|").split("|")]
                    if len(cells) < 2:
                        continue
                    if all(set(c) <= set("-: ") for c in cells):
                        continue
                    key = cells[0].strip("* ").strip().lower()
                    val = cells[1].strip()
                    if key in ("id", "task_id"):
                        task_id = val
                    elif key == "title":
                        title = val
                    elif key == "project":
                        project_id = val or project_id
                    elif key in ("status", "kanban_status"):
                        status = val
                    elif key == "priority":
                        priority = val
                    elif key in ("owner", "assigned_to", "assignee"):
                        assignee = val.lower() if val else None
            if not task_id:
                task_id = md.stem
            if not task_id:
                return
            # Canonical id: prefer the frontmatter `id` field; fall back
            # to the file stem. Always BARE (no path suffix) so the
            # bulk_seed walker uses the SAME id convention as the live
            # kanban-bridge. Re-runs are idempotent: if a node with this
            # bare id already exists (whether written by a prior seed or
            # by a live POST /api/kanban), we skip.
            nid = f"task:{_task_id_safe(task_id)}"
            rel = str(md.relative_to(repo)) if str(md).startswith(str(repo)) else str(md)
            if self.has_node(nid):
                stats["skipped_existing"] += 1
                return  # already ingested; idempotent on rerun
            self.upsert_node({
                "id": nid,
                "kind": "task",
                "label": title or task_id,
                "summary": text[:600].strip(),
                "importance": 0.6,
                "confidence": 0.85,
                "status": status or "active",
                "tags": ["task", project_id or "unknown", priority or "normal"],
                "source": rel,
                "project": project_id,
                "agent": assignee,
                "metadata": {
                    "task_id": task_id,
                    "priority": priority,
                    "assignee": assignee,
                },
            })
            stats["tasks"] += 1
            if project_id:
                _project_node(project_id, f"01_projects/{project_id}/")
                self.upsert_edge({
                    "id": f"edge-project:{_task_id_safe(project_id)}-{nid}-contains",
                    "source": f"project:{_task_id_safe(project_id)}",
                    "target": nid,
                    "kind": "contains",
                    "weight": 0.7,
                })
                stats["edges"] += 1
            if assignee and assignee in known_agents:
                self.upsert_edge({
                    "id": f"edge-{nid}-agent:{assignee}-assigned_to",
                    "source": nid,
                    "target": f"agent:{assignee}",
                    "kind": "assigned_to",
                    "weight": 0.8,
                })
                stats["edges"] += 1

        # 01_projects/*/tasks/*.md
        if top_projects.is_dir():
            for proj_dir in sorted(top_projects.iterdir()):
                if not proj_dir.is_dir() or proj_dir.name.startswith("."):
                    continue
                tasks_dir = proj_dir / "tasks"
                if tasks_dir.is_dir():
                    for md in sorted(tasks_dir.glob("*.md")):
                        _ingest_task_file(md, default_project=proj_dir.name)

        # 00_company_os/02_tasks/*  (alt location)
        co_tasks = repo / "00_company_os" / "02_tasks"
        if co_tasks.is_dir():
            for md in sorted(co_tasks.rglob("*.md")):
                _ingest_task_file(md, default_project=None)

        # ----- 4. events.jsonl -----
        def _ingest_events_jsonl(path: Path, source_label: str) -> None:
            if not path.is_file():
                return
            try:
                with path.open("r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except Exception:
                stats["skipped"] += 1
                return
            # Cap to max_event_lines most recent (file is usually small).
            lines = lines[-max_event_lines:]
            count = 0
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(ev, dict):
                    continue
                ts = ev.get("ts") or ev.get("timestamp") or ""
                actor = ev.get("actor")
                task_id = ev.get("task_id")
                project_id = ev.get("project")
                event_type = ev.get("event_type") or ev.get("type") or "log"
                # Stable id: hash on task_id + ts + type to dedup on rerun
                seed = f"{ts}|{task_id}|{event_type}|{actor}"
                eid_seed = hashlib.sha1(seed.encode("utf-8", errors="replace")).hexdigest()[:12]
                eid = f"event:{eid_seed}"
                if self.has_node(eid):
                    continue
                self.upsert_node({
                    "id": eid,
                    "kind": "event",
                    "label": f"{event_type} · {task_id or '—'}",
                    "summary": (ev.get("message") or ev.get("title") or
                                ev.get("note") or ev.get("text") or "")[:300],
                    "importance": 0.3,
                    "confidence": 0.7,
                    "status": str(ev.get("status") or "logged"),
                    "tags": ["event", source_label, event_type],
                    "source": str(path.relative_to(repo)) if str(path).startswith(str(repo)) else str(path),
                    "project": project_id,
                    "agent": actor if isinstance(actor, str) else None,
                    "created": ts,
                })
                count += 1
                if project_id:
                    _project_node(project_id, "")
                    self.upsert_edge({
                        "id": f"edge-project:{_task_id_safe(project_id)}-{eid}-emitted_event",
                        "source": f"project:{_task_id_safe(project_id)}",
                        "target": eid,
                        "kind": "emitted_event",
                        "weight": 0.5,
                    })
                    stats["edges"] += 1
                if task_id:
                    self.upsert_edge({
                        "id": f"edge-{eid}-task:{_task_id_safe(task_id)}-references_file",
                        "source": eid,
                        "target": f"task:{_task_id_safe(task_id)}",
                        "kind": "references_file",
                        "weight": 0.5,
                    })
                    stats["edges"] += 1
            stats["events"] += count

        _ingest_events_jsonl(repo / "00_company_os" / "04_agents" / "events.jsonl", "agent-events")
        _ingest_events_jsonl(repo / "00_company_os" / "events.jsonl", "company-events")

        # ----- 5. knowledge -----
        knowledge_dirs = [
            repo / "00_company_os" / "05_knowledge",
        ]
        for kdir in knowledge_dirs:
            if kdir.is_dir():
                for md in sorted(kdir.rglob("*.md")):
                    try:
                        text = md.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        stats["skipped"] += 1
                        continue
                    name = md.stem
                    title = name.replace("-", " ").replace("_", " ").title()
                    for line in text.splitlines():
                        if line.startswith("# "):
                            title = line[2:].strip()
                            break
                    nid = f"knowledge:{_task_id_safe(name)}"
                    rel = str(md.relative_to(repo)) if str(md).startswith(str(repo)) else str(md)
                    self.upsert_node({
                        "id": nid,
                        "kind": "memory",
                        "label": f"Knowledge: {title}",
                        "summary": text[:500].strip(),
                        "importance": 0.6,
                        "confidence": 0.85,
                        "status": "active",
                        "tags": ["knowledge", name],
                        "source": rel,
                    })
                    self.upsert_edge({
                        "id": f"edge-company:nofitech-{nid}-contains",
                        "source": "company:nofitech",
                        "target": nid,
                        "kind": "contains",
                        "weight": 0.5,
                    })
                    stats["knowledge"] += 1
                    stats["edges"] += 1

        # Top-level company OS docs (charter, schemas, etc.)
        company_docs = (
            "charter.md", "activation-protocol.md", "auto-kanban-rule.md",
            "event-schema.md", "task-schema.md", "token-budget-mode.md",
            "stage-12-plan.md", "memory-log.md",
        )
        for fname in company_docs:
            p = repo / "00_company_os" / fname
            if not p.is_file():
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                stats["skipped"] += 1
                continue
            name = p.stem
            title = name.replace("-", " ").title()
            for line in text.splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
            nid = f"company_doc:{_task_id_safe(name)}"
            self.upsert_node({
                "id": nid,
                "kind": "memory",
                "label": f"Company doc: {title}",
                "summary": text[:500].strip(),
                "importance": 0.7,
                "confidence": 0.95,
                "status": "active",
                "tags": ["company-doc", name],
                "source": f"00_company_os/{fname}",
            })
            self.upsert_edge({
                "id": f"edge-company:nofitech-{nid}-contains",
                "source": "company:nofitech",
                "target": nid,
                "kind": "contains",
                "weight": 0.6,
            })
            stats["company_files"] += 1
            stats["edges"] += 1

        # memory-log-*.md (additional log files)
        co_memlogs = repo / "00_company_os"
        for p in sorted(co_memlogs.glob("memory-log-*.md")):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                stats["skipped"] += 1
                continue
            name = p.stem
            nid = f"company_doc:{_task_id_safe(name)}"
            if self.has_node(nid):
                continue
            self.upsert_node({
                "id": nid,
                "kind": "memory",
                "label": f"Company doc: {name}",
                "summary": text[:500].strip(),
                "importance": 0.5,
                "confidence": 0.9,
                "status": "active",
                "tags": ["company-doc", "memory-log"],
                "source": f"00_company_os/{p.name}",
            })
            self.upsert_edge({
                "id": f"edge-company:nofitech-{nid}-contains",
                "source": "company:nofitech",
                "target": nid,
                "kind": "contains",
                "weight": 0.5,
            })
            stats["company_files"] += 1
            stats["edges"] += 1

        # ----- 6. agent logs/**/*.md -----
        logs_root = repo / "00_company_os" / "04_agents" / "logs"
        if logs_root.is_dir():
            for md in sorted(logs_root.rglob("*.md")):
                try:
                    text = md.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    stats["skipped"] += 1
                    continue
                # Extract agent from path (.../logs/<date>/<agent>-<task>-<hash>.md)
                rel = md.relative_to(logs_root)
                parts = rel.parts
                date = parts[0] if parts else "unknown"
                fname = md.stem
                # Try to detect which agent this log is for from the filename prefix
                agent = None
                for a in known_agents:
                    if fname.lower().startswith(a.lower()):
                        agent = a
                        break
                nid = f"log:{_task_id_safe(fname)}"
                if self.has_node(nid):
                    continue
                self.upsert_node({
                    "id": nid,
                    "kind": "file",
                    "label": f"Log: {fname}",
                    "summary": text[:400].strip(),
                    "importance": 0.3,
                    "confidence": 0.7,
                    "status": "active",
                    "tags": ["log", date, agent or "unknown"],
                    "source": str(md.relative_to(repo)),
                    "agent": agent,
                    "metadata": {"log_date": date},
                })
                if agent:
                    self.upsert_edge({
                        "id": f"edge-agent:{agent}-{nid}-produced_artifact",
                        "source": f"agent:{agent}",
                        "target": nid,
                        "kind": "produced_artifact",
                        "weight": 0.5,
                    })
                    stats["edges"] += 1
                else:
                    self.upsert_edge({
                        "id": f"edge-company:nofitech-{nid}-contains",
                        "source": "company:nofitech",
                        "target": nid,
                        "kind": "contains",
                        "weight": 0.3,
                    })
                    stats["edges"] += 1
                stats["logs"] += 1

        # ----- 7. 04_agents/state.json -----
        state_path = repo / "00_company_os" / "04_agents" / "state.json"
        if state_path.is_file():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8", errors="replace"))
                if isinstance(state, dict):
                    self.upsert_node({
                        "id": "agent_state:04_agents",
                        "kind": "memory",
                        "label": "Agent state (04_agents/state.json)",
                        "summary": json.dumps(state)[:500],
                        "importance": 0.5,
                        "confidence": 0.9,
                        "status": "active",
                        "tags": ["agent-state", "config"],
                        "source": "00_company_os/04_agents/state.json",
                    })
                    self.upsert_edge({
                        "id": "edge-company:nofitech-agent_state:04_agents-contains",
                        "source": "company:nofitech",
                        "target": "agent_state:04_agents",
                        "kind": "contains",
                        "weight": 0.5,
                    })
                    stats["company_files"] += 1
                    stats["edges"] += 1
            except Exception:
                stats["skipped"] += 1

        # ----- 8. 00_company_os/state.json (top-level) -----
        top_state = repo / "00_company_os" / "state.json"
        if top_state.is_file():
            try:
                state = json.loads(top_state.read_text(encoding="utf-8", errors="replace"))
                if isinstance(state, dict):
                    self.upsert_node({
                        "id": "agent_state:company",
                        "kind": "memory",
                        "label": "Company state (state.json)",
                        "summary": json.dumps(state)[:500],
                        "importance": 0.5,
                        "confidence": 0.9,
                        "status": "active",
                        "tags": ["company-state", "config"],
                        "source": "00_company_os/state.json",
                    })
                    self.upsert_edge({
                        "id": "edge-company:nofitech-agent_state:company-contains",
                        "source": "company:nofitech",
                        "target": "agent_state:company",
                        "kind": "contains",
                        "weight": 0.5,
                    })
                    stats["company_files"] += 1
                    stats["edges"] += 1
            except Exception:
                stats["skipped"] += 1

        # Audit event for the seed.
        n_after = self.node_count()
        e_after = self.edge_count()
        self.append_event(
            event_type="bulk_seed",
            actor="forge",
            task_id="MC-LIVE-MEMORY-GRAPH-1",
            project="mission-control",
            agent="forge",
            source="bulk_seed_script",
            payload={
                "note": "Bulk filesystem seed completed",
                "stats": stats,
                "node_count": n_after,
                "edge_count": e_after,
            },
        )
        stats["total_nodes_after"] = n_after
        stats["total_edges_after"] = e_after
        return stats

    # ----- live auto-emit (MC-LIVE-MEMORY-GRAPH-1, 2026-06-19) ---------

    def add_node(self, node: dict) -> bool:
        """Public alias for upsert_node, used by serve.py hot paths.

        Idempotent on `id`. Returns True on success. Never raises —
        memory writes must never break kanban/agent operations.
        """
        try:
            return self.upsert_node(node)
        except Exception as e:
            log.warning("add_node failed for %r: %s", (node or {}).get("id"), e)
            return False

    def add_edge(self, edge: dict) -> bool:
        """Public alias for upsert_edge, used by serve.py hot paths.

        Idempotent on `id` (auto-generated as
        `edge-<source>-<target>-<kind>` when not supplied). Returns
        True on success. Never raises.
        """
        try:
            return self.upsert_edge(edge)
        except Exception as e:
            log.warning("add_edge failed: %s", e)
            return False

    def add_event(self, *, event_type: str, actor: str | None = None,
                  task_id: str | None = None, project: str | None = None,
                  agent: str | None = None, source: str | None = None,
                  payload: dict | None = None) -> None:
        """Public wrapper around append_event with optional node+edge emit.

        In addition to the audit event, if `task_id` is provided and a
        `task:<task_id>` node exists, this method is a no-op for nodes
        (it doesn't double-upsert). Use `add_node` separately if you
        want a fresh node written.
        """
        try:
            self.append_event(
                event_type=event_type,
                actor=actor,
                task_id=task_id,
                project=project,
                agent=agent,
                source=source,
                payload=payload or {},
            )
        except Exception as e:
            log.warning("add_event failed: %s", e)

    def reset_view(self) -> dict:
        """MC-LIVE-MEMORY-GRAPH-1: visual-only reset.

        The 'Reset View' button in the UI calls this. The DB is
        **never** touched — no DELETE, no reseed, no sample import.
        We just record a `view_reset` event for the audit trail and
        return the current graph shape. The frontend receives the
        200 response and resets the 3D camera on its end.

        This is a strict, observable change from the previous
        `reset()` behaviour (which wiped everything). Keeping the old
        `reset()` method around for tests / explicit admin tools.
        """
        with self._lock:
            self.append_event(
                event_type="view_reset",
                actor="user",
                task_id=None,
                project=None,
                agent=None,
                source="reset_view_endpoint",
                payload={
                    "note": "Reset View clicked — camera returned to origin, DB untouched",
                    "node_count": self.node_count(),
                    "edge_count": self.edge_count(),
                },
            )
        return self.load_scoped()

    def reset(self, *, reseed: bool = False) -> dict:
        """ADMIN: hard reset. Wipes nodes/edges/events.

        MC-LIVE-MEMORY-GRAPH-1 (2026-06-19): The user-facing
        /api/memory-graph/reset endpoint no longer calls this. The
        'Reset View' button calls `reset_view()` instead. This method
        is preserved for explicit admin/destructive use (tests, ops).
        Default `reseed=False` to make the destructive intent obvious.

        Returns the new (post-reset) graph shape (a scope='all' dict).
        """
        with self._lock:
            self._conn.execute("DELETE FROM nodes")
            self._conn.execute("DELETE FROM edges")
            self._conn.execute("DELETE FROM events")
            sample_graph: dict | None = None
            if reseed:
                sample_graph = self._load_sample_for_migration()
                if sample_graph is not None:
                    for n in sample_graph.get("nodes") or []:
                        if isinstance(n, dict) and n.get("id"):
                            self._upsert_node_row(n)
                    for e in sample_graph.get("edges") or []:
                        if isinstance(e, dict) and e.get("id"):
                            self._upsert_edge_row(e)
            n_after = self.node_count()
            e_after = self.edge_count()
            self.append_event(
                event_type="graph_reset_admin",
                actor="forge",
                task_id=None,
                project=None,
                agent=None,
                source="reset_endpoint",
                payload={
                    "note": (f"ADMIN reset ({n_after} nodes / {e_after} edges)"
                             if reseed and sample_graph is not None
                             else "ADMIN hard reset (no reseed)"),
                    "node_count": n_after,
                    "edge_count": e_after,
                    "reseed": bool(reseed),
                    "sample_loaded": sample_graph is not None,
                },
            )
        return self.load_scoped()

    def _load_sample_for_migration(self) -> dict | None:
        """Load sample-graph.json if it exists in any of the well-known
        locations. Returns the parsed graph dict (with 'nodes' and 'edges'
        arrays) or None if not found.
        """
        candidates: list[Path] = []
        # 1. data/sample-graph.json next to the company root
        candidates.append(Path("/home/nofidofi/NofiTech-Ind/data/sample-graph.json"))
        # 2. 01_projects/mission-control/data/sample-graph.json
        candidates.append(Path("/home/nofidofi/NofiTech-Ind/01_projects/mission-control/data/sample-graph.json"))
        # 3. alongside the SQLite file
        try:
            candidates.append(self.db_path.parent / "sample-graph.json")
        except Exception:
            pass
        # 4. anywhere under the project root
        try:
            for p in Path("/home/nofidofi/NofiTech-Ind").rglob("sample-graph.json"):
                candidates.append(p)
        except Exception:
            pass
        for p in candidates:
            try:
                if p.is_file():
                    return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
        return None

    def _upsert_node_row(self, n: dict) -> None:
        """Insert-or-replace a single node row from a sample dict.

        Column list MUST match the `nodes` table created in __init__'s
        SCHEMA constant. As of 2026-06-19 the table is:

            id, kind, label, summary, status, importance, confidence,
            tags, metadata, source, project, agent, created, updated

        Note: columns are `created` and `updated` (NOT `created_at` /
        `updated_at`). Sample rows from the seed JSON already carry
        `created` / `updated` ISO strings, so we pass them through
        unchanged. Tolerates extra keys (silently ignored).
        """
        nid = n.get("id") or ""
        if not nid:
            return
        try:
            importance = self._clamp01(n.get("importance"), 0.5)
        except (TypeError, ValueError):
            importance = 0.5
        try:
            confidence = self._clamp01(n.get("confidence"), 0.5)
        except (TypeError, ValueError):
            confidence = 0.5
        metadata_json = json.dumps(n.get("metadata") or {}, ensure_ascii=False)
        tags_json = json.dumps(n.get("tags") or [], ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO nodes (id, kind, label, summary, status,
                                   importance, confidence, tags, metadata,
                                   source, project, agent, created, updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                  project=COALESCE(excluded.project, nodes.project),
                  agent=COALESCE(excluded.agent, nodes.agent),
                  updated=COALESCE(NULLIF(excluded.updated, ''), nodes.updated)
                """,
                (
                    nid,
                    n.get("kind", "concept") or "concept",
                    n.get("label", "") or "",
                    n.get("summary", "") or "",
                    n.get("status", "active") or "active",
                    importance,
                    confidence,
                    tags_json,
                    metadata_json,
                    n.get("source") or "sample-seed",
                    n.get("project"),
                    n.get("agent"),
                    n.get("created") or self._now_iso(),
                    (n.get("updated") or "").strip() or None,
                ),
            )

    def _upsert_edge_row(self, e: dict) -> None:
        """Insert-or-replace a single edge row from a sample dict.

        Column list MUST match the `edges` table created in __init__'s
        SCHEMA constant. As of 2026-06-19 the table is:

            id, source, target, kind, weight, metadata, created

        Note: there is NO `label` column on edges (the draft copy-pasted
        from the node shape). The timestamp column is `created` (NOT
        `created_at`). Tolerates `from`/`to` as aliases for source/target
        and missing `id` (auto-generated).
        """
        src = e.get("source") or e.get("from") or ""
        dst = e.get("target") or e.get("to") or ""
        if not src or not dst:
            return
        eid = (e.get("id") or "").strip() or f"edge-{src}-{dst}-{e.get('kind', 'relates_to')}"
        try:
            weight = self._clamp01(e.get("weight"), 0.5)
        except (TypeError, ValueError):
            weight = 0.5
        metadata_json = json.dumps(e.get("metadata") or {}, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO edges (id, source, target, kind, weight,
                                   metadata, created)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  source=excluded.source,
                  target=excluded.target,
                  kind=excluded.kind,
                  weight=excluded.weight,
                  metadata=excluded.metadata
                """,
                (
                    eid,
                    src,
                    dst,
                    e.get("kind", "relates_to") or "relates_to",
                    weight,
                    metadata_json,
                    e.get("created") or self._now_iso(),
                ),
            )

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
        # Clear module-level references so the next caller doesn't
        # accidentally pick up a closed connection.
        global _STORE, _LAST_INSTANCE
        if _STORE is self:
            _STORE = None
        if _LAST_INSTANCE is self:
            _LAST_INSTANCE = None


# --- Module-level singleton --------------------------------------------

_STORE: GlobalMemoryGraphStore | None = None
_LAST_INSTANCE: GlobalMemoryGraphStore | None = None


def init_global_store(db_path: Path | None = None) -> GlobalMemoryGraphStore:
    """Initialise the singleton global store. Idempotent."""
    global _STORE
    if _STORE is None:
        _STORE = GlobalMemoryGraphStore(db_path)
    return _STORE


def get_global_store() -> GlobalMemoryGraphStore:
    if _STORE is None:
        # Fallback: if a recent instance exists and its conn is still
        # live, use it. Lets tests call `load_scoped_from_request`
        # without explicit `init_global_store(self.db)` wiring.
        global _LAST_INSTANCE
        if _LAST_INSTANCE is not None:
            try:
                _LAST_INSTANCE._conn.execute("SELECT 1").fetchone()
                globals()["_STORE"] = _LAST_INSTANCE
                return _LAST_INSTANCE
            except Exception:
                _LAST_INSTANCE = None
        raise RuntimeError(
            "global memory store not initialised — call init_global_store() first"
        )
    return _STORE


def reset_global_store() -> None:
    """Test helper: drop the singleton reference so the next init
    re-opens. We do NOT close the underlying connection here — tests
    typically manage store lifetime themselves; auto-closing would
    cause cross-test interference when one test's setUp creates a
    fresh store while a previous test's tearDown is still pending.
    """
    global _STORE, _LAST_INSTANCE
    _STORE = None
    _LAST_INSTANCE = None


def load_scoped_from_request(path: str) -> dict:
    """Parse `?scope=&project=&agent=&kind=&since=&until=&importance=`
    from a request path and return a scoped graph dict.

    Convenience wrapper for the API handler. Falls back to scope='all'
    with no filters when the path has no query string.
    """
    import urllib.parse as _up
    p = _up.urlparse(path)
    qs = _up.parse_qs(p.query)

    def _one(k: str) -> str | None:
        v = qs.get(k)
        return v[0].strip() if v and v[0] and v[0].strip() else None

    scope = (_one("scope") or "all").lower()
    project = _one("project")
    agent = _one("agent")
    kind = _one("kind")
    since = _one("since")
    until = _one("until")
    importance_raw = _one("importance")
    importance: float | None = None
    if importance_raw is not None:
        try:
            importance = max(0.0, min(1.0, float(importance_raw)))
        except (TypeError, ValueError):
            importance = None
    # Auto-init the global store from its default path if it isn't
    # already open. This makes the API handler safe to call from
    # tests and from serve.py startup before the explicit init hook.
    # If no singleton exists but a recent instance was created (test
    # path), fall back to that — it has the seeded data.
    global _STORE, _LAST_INSTANCE
    if _STORE is None and _LAST_INSTANCE is not None:
        try:
            # Sanity check: connection still open.
            _LAST_INSTANCE._conn.execute("SELECT 1").fetchone()
            _STORE = _LAST_INSTANCE
        except Exception:
            _LAST_INSTANCE = None
    if _STORE is None:
        init_global_store()
    store = get_global_store()
    return store.load_scoped(
        scope=scope, project=project, agent=agent, kind=kind,
        since=since, until=until, importance=importance,
    )
