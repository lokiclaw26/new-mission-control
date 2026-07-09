#!/usr/bin/env python3
"""
memory_graph_api.py — HTTP endpoint handlers for the Memory Graph.

MC-MEMORY-GRAPH-3A-BACKEND (2026-06-17) — original version.
MC-MEMORY-GRAPH-4-GLOBAL  (2026-06-17) — read path now hits the global
                                        store at 00_company_os/memory/.
                                        New query params: scope, project,
                                        agent, kind, since, until,
                                        importance. Response shape is
                                        preserved (backwards-compatible).

Each handler is a small function that takes a BaseHTTPRequestHandler and
returns a (status_code, payload_dict) tuple. The HTTP layer in
serve.py / server.py converts that into a JSON response. The auth check
runs before any write.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
from typing import Any

from security import is_authorized, auth_required_error, redact_secrets
from memory_graph_store import get_store  # legacy (kanban-bridge)
from memory_graph_global import (
    init_global_store,
    get_global_store,
    load_scoped_from_request,
)

log = logging.getLogger("mc.mg_api")


# Body limits (per spec). Keep tight; events should be small JSON objects.
_MAX_EVENT_BODY = 64 * 1024
_MAX_RESET_BODY = 4 * 1024


def _read_json_body(handler, max_bytes: int) -> tuple[dict | list | None, str | None]:
    """Read + parse the request body. Returns (parsed, error_msg)."""
    try:
        length = int(handler.headers.get("Content-Length") or "0")
    except (TypeError, ValueError):
        length = 0
    if length < 0 or length > max_bytes:
        return None, f"body must be 1..{max_bytes} bytes"
    raw = handler.rfile.read(length) if length > 0 else b""
    if not raw:
        return None, "empty body"
    try:
        return json.loads(raw.decode("utf-8")), None
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return None, f"invalid JSON: {e}"


def get_graph(handler) -> tuple[int, dict]:
    """GET /api/memory-graph — return the (scoped) graph.

    Query params (all optional):
      scope      = all | project | agent | kind | session   (default: all)
      project    = <id>  (used when scope=project)
      agent      = <name> (used when scope=agent)
      kind       = <kind> or comma-separated list (used when scope=kind or as a filter)
      since      = ISO timestamp (created/updated >= since)
      until      = ISO timestamp (created/updated <= until)
      importance = float 0..1 (min importance floor)

    Response shape (backwards-compatible):
      {nodes, edges, metadata, last_updated, node_count, edge_count}
    """
    # Ensure the global store is initialised (idempotent).
    try:
        get_global_store()
    except RuntimeError:
        init_global_store()
    g = load_scoped_from_request(handler.path)
    return 200, {
        "nodes": g.get("nodes", []),
        "edges": g.get("edges", []),
        "metadata": g.get("metadata", {}),
        "last_updated": g.get("last_updated"),
        "node_count": g.get("node_count", 0),
        "edge_count": g.get("edge_count", 0),
    }


def post_events(handler) -> tuple[int, dict]:
    """POST /api/memory-graph/events — ingest one event or an array.

    Requires auth (per MC-MEMORY-GRAPH-3A-BACKEND §1).
    Body is redacted before ingestion.

    MC-MEMORY-GRAPH-4-GLOBAL: events are written to BOTH the global
    store (canonical) and the legacy store (kanban-bridge compatibility).
    The legacy store is the one wired into the kanban service; we keep
    the dual write minimal so behaviour for kanban_service is unchanged.
    """
    if not is_authorized(handler):
        return 403, auth_required_error()

    parsed, err = _read_json_body(handler, _MAX_EVENT_BODY)
    if err:
        return 400, {"error": err}
    events = parsed if isinstance(parsed, list) else [parsed]
    if not events:
        return 400, {"error": "no events in payload"}

    # Legacy store (kanban-bridge compatibility) — preserved unchanged.
    try:
        store = get_store()
    except RuntimeError:
        store = None
    # Global store (canonical).
    try:
        global_store = get_global_store()
    except RuntimeError:
        global_store = init_global_store()

    results: list[dict] = []
    all_ok = True
    for ev in events:
        if not isinstance(ev, dict):
            all_ok = False
            results.append({"ok": False, "error": "event must be a JSON object"})
            continue
        # Redact FIRST, then ingest. Persisted data is always safe.
        redacted = redact_secrets(ev)
        # Legacy ingest (unchanged for kanban).
        legacy_ok = True
        legacy_err = None
        if store is not None:
            try:
                r = store.ingest_event(redacted)
                if not r.get("ok"):
                    legacy_ok = False
                    legacy_err = r
            except ValueError as e:
                legacy_ok = False
                legacy_err = str(e)
        # Global ingest: write event into events table + mirror as node.
        try:
            etype = (redacted.get("type") or "log")
            global_store.append_event(
                event_type=etype,
                actor=redacted.get("actor"),
                task_id=redacted.get("task_id"),
                project=redacted.get("project"),
                agent=redacted.get("actor") or redacted.get("agent"),
                source=redacted.get("source"),
                payload=redacted,
            )
        except Exception as e:
            all_ok = False
            results.append({"ok": False, "error": f"global store: {e}",
                            "type": redacted.get("type")})
            continue
        results.append({
            "ok": legacy_ok,
            "legacy": legacy_ok,
            "global": True,
            "legacy_error": legacy_err,
            "type": redacted.get("type"),
        })
        if not legacy_ok:
            all_ok = False
    return (200 if all_ok else 400), {
        "ok": all_ok,
        "results": results,
        "count": len(results),
    }


def post_reset(handler) -> tuple[int, dict]:
    """POST /api/memory-graph/reset — user-facing "Reset View" button.

    MC-LIVE-MEMORY-GRAPH-1 (2026-06-19): NOFI complained that
    clicking reset wiped the graph. The new behaviour is **visual
    reset only**: the DB is NEVER touched (no DELETE, no reseed).
    We just record a `view_reset` event for the audit trail and
    return the current graph shape. The frontend resets the 3D
    camera on its end.

    The hard-reset (admin wipe) is now exposed at
    /api/memory-graph/admin-reset and is NOT wired to the UI.

    Requires auth (same as before). Returns 200 with the current
    node/edge counts (unchanged) and a `view_reset: true` flag.
    """
    if not is_authorized(handler):
        return 403, auth_required_error()
    # Body may be empty. Read for shape-validation only.
    try:
        length = int(handler.headers.get("Content-Length") or "0")
    except (TypeError, ValueError):
        length = 0
    if length < 0 or length > _MAX_RESET_BODY:
        return 400, {"error": f"body must be 1..{_MAX_RESET_BODY} bytes"}
    if length > 0:
        handler.rfile.read(length)  # discard; we don't accept {confirm:true}

    try:
        global_store = get_global_store()
    except RuntimeError:
        global_store = init_global_store()

    # Visual reset only. DB is preserved.
    g = global_store.reset_view()
    return 200, {
        "ok": True,
        "view_reset": True,
        "db_wiped": False,
        "reset_at": g.get("last_updated"),
        "node_count": g.get("node_count", 0),
        "edge_count": g.get("edge_count", 0),
        "note": "Camera returned to origin. Database is unchanged.",
    }


def post_admin_reset(handler) -> tuple[int, dict]:
    """POST /api/memory-graph/admin-reset — destructive hard reset.

    MC-LIVE-MEMORY-GRAPH-1 (2026-06-19): NOT wired to the UI.
    Kept for explicit ops / tests. Requires auth.
    """
    if not is_authorized(handler):
        return 403, auth_required_error()
    try:
        length = int(handler.headers.get("Content-Length") or "0")
    except (TypeError, ValueError):
        length = 0
    if length < 0 or length > _MAX_RESET_BODY:
        return 400, {"error": f"body must be 1..{_MAX_RESET_BODY} bytes"}
    if length > 0:
        handler.rfile.read(length)

    try:
        global_store = get_global_store()
    except RuntimeError:
        global_store = init_global_store()
    g = global_store.reset(reseed=False)
    return 200, {
        "ok": True,
        "admin_reset": True,
        "reset_at": g.get("last_updated"),
        "node_count": g.get("node_count", 0),
        "edge_count": g.get("edge_count", 0),
    }


def post_rebuild(handler) -> tuple[int, dict]:
    """POST /api/memory-graph/rebuild — admin wipe + full re-import from disk.

    Unlike reset (which wipes and leaves the graph empty), rebuild runs the
    full importer pipeline so the graph is immediately repopulated. NOFI
    complained that reset left the graph empty and there was no way to
    repopulate it from the UI — this endpoint fixes that.

    Requires auth (same as reset). Returns 200 with the import stats.

    Implementation: just call the existing `MemoryGraphImporter.full_rebuild()`
    which is the same code path the CLI uses (`--full-rebuild`).
    """
    if not is_authorized(handler):
        return 403, auth_required_error()
    # Body may be empty. Read for shape-validation only.
    try:
        length = int(handler.headers.get("Content-Length") or "0")
    except (TypeError, ValueError):
        length = 0
    if length < 0 or length > _MAX_RESET_BODY:
        return 400, {"error": f"body must be 1..{_MAX_RESET_BODY} bytes"}
    if length > 0:
        handler.rfile.read(length)  # discard; we don't accept {confirm:true}

    # Use the same module the serve.py boot uses. We import lazily so the
    # import path stays consistent with the rest of the code.
    import memory_graph_import  # noqa: PLC0415  (lazy import; same module the boot uses)
    from memory_graph_global import init_global_store  # noqa: PLC0415

    try:
        global_store = init_global_store()
    except Exception as e:
        return 500, {"ok": False, "error": f"failed to init global store: {e}"}
    try:
        # REPO_ROOT is the module-level constant the CLI uses; it's the
        # project root (~/NofiTech-Ind) so the importer can scan for source
        # files. Don't use the store's db_path — that's a file, not a dir.
        importer = memory_graph_import.MemoryGraphImporter(
            store=global_store, repo_root=memory_graph_import.REPO_ROOT
        )
        stats = importer.full_rebuild()
    except Exception as e:
        return 500, {"ok": False, "error": f"full_rebuild failed: {e}"}

    return 200, {
        "ok": True,
        "stats": stats,
        "node_count": stats.get("nodes_upserted", 0),
        "edge_count": stats.get("edges_upserted", 0),
        "files_ingested": stats.get("files_ingested", 0),
    }


def get_events_recent(handler) -> tuple[int, dict]:
    """GET /api/memory-graph/events/recent?n=20"""
    p = urllib.parse.urlparse(handler.path)
    qs = urllib.parse.parse_qs(p.query)
    try:
        n = int((qs.get("n", [20])[0] or "20"))
    except (TypeError, ValueError):
        n = 20
    n = max(1, min(n, 200))
    try:
        store = get_store()
    except RuntimeError:
        store = None
    if store is None:
        return 200, {"events": [], "count": n}
    return 200, {"events": store.recent_events(n), "count": n}


def get_stream_disabled(handler) -> tuple[int, dict]:
    """GET /api/memory-graph/stream — disabled (was blocking SSE).

    Returns 410 Gone per MC-MEMORY-GRAPH-3A spec §6.
    """
    return 410, {
        "error": "SSE stream endpoint disabled — poll /api/memory-graph instead",
        "use_polling": True,
        "polling_endpoint": "/api/memory-graph",
        "polling_interval_seconds": 5,
    }


def emit_kanban_memory_event(task_id: str, new_status: str,
                             project: str | None = None,
                             label: str | None = None) -> None:
    """Best-effort: emit a node.upsert for a kanban status change.

    Called by kanban_service when a task's kanban_status changes. If the
    memory store is not initialised or anything fails, swallow silently —

    MC-MEMORY-GRAPH-4-GLOBAL: also write to the global store so the
    kanban event is visible in the full Hermes graph. Failures are
    swallowed silently — kanban must never break on a memory hiccup.
    """
    try:
        store = get_store()
        nid = f"task:{task_id}"
        node = {
            "id": nid,
            "kind": "task",
            "label": label or task_id,
            "summary": f"Kanban task {task_id} → {new_status}",
            "importance": 0.7,
            "confidence": 0.9,
            "status": str(new_status or "active"),
            "tags": ["kanban", "task"],
            "metadata": {},
            "source": "kanban-bridge",
        }
        if project:
            node["project"] = project
        store.ingest_event({"type": "node.upsert", "node": node,
                            "task_id": task_id, "actor": "kanban-bridge"})
    except Exception:
        pass
    # Also write to the global store.
    try:
        global_store = get_global_store()
    except RuntimeError:
        try:
            global_store = init_global_store()
        except Exception:
            return
    try:
        global_store.upsert_node({
            "id": f"task:{task_id}",
            "kind": "task",
            "label": label or task_id,
            "summary": f"Kanban task {task_id} → {new_status}",
            "importance": 0.7,
            "confidence": 0.9,
            "status": str(new_status or "active"),
            "tags": ["kanban", "task"],
            "source": "kanban-bridge-global",
            "project": project,
        })
        global_store.append_event(
            event_type="kanban.status_change",
            actor="kanban-bridge",
            task_id=task_id,
            project=project,
            agent="kanban-bridge",
            source="kanban_service",
            payload={"new_status": str(new_status), "label": label},
        )
    except Exception:
        pass
