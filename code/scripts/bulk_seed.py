#!/usr/bin/env python3
"""
bulk_seed.py — one-shot bulk import of real NofiTech artifacts into
the GLOBAL memory graph (00_company_os/memory/memory-graph.sqlite3).

MC-LIVE-MEMORY-GRAPH-1 (2026-06-19): NOFI demanded a REAL live memory
graph, not a 17-node dummy seed. This script walks the filesystem
and turns every meaningful artifact into a graph node + edge.

Idempotent: re-running this script does NOT create duplicate nodes.
Every upsert is keyed on a stable id and the store enforces PK
uniqueness.

Walks:
  - 00_company_os/04_agents/*.md             -> agent files
  - 00_company_os/01_projects/*              -> projects
  - 01_projects/*                            -> projects
  - 01_projects/*/tasks/*.md                 -> tasks (Format A & B)
  - 00_company_os/02_tasks/*.md              -> tasks (alt)
  - 00_company_os/04_agents/events.jsonl     -> events
  - 00_company_os/events.jsonl               -> events
  - 00_company_os/05_knowledge/              -> knowledge
  - 00_company_os/charter.md, schemas, etc.  -> company docs
  - 00_company_os/04_agents/state.json       -> agent state
  - 00_company_os/04_agents/logs/**/*.md     -> log entries

Target: 100+ real nodes after one full run.

Usage:
  python3 scripts/bulk_seed.py                 # walks default repo
  python3 scripts/bulk_seed.py --repo /path    # walks a different root
  python3 scripts/bulk_seed.py --stats-only    # just show counts, no write
  python3 scripts/bulk_seed.py --max-events 1000  # cap event ingestion

Stdlib only — no new deps.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Make sibling modules importable when run as `python3 scripts/bulk_seed.py`.
_HERE = Path(__file__).resolve().parent
_CODE_DIR = _HERE.parent
if str(_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(_CODE_DIR))

from memory_graph_global import (  # noqa: E402
    init_global_store,
    get_global_store,
    global_db_path,
)


def _print(msg: str) -> None:
    print(f"[bulk_seed] {msg}", flush=True)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--repo", default=None,
                   help="Repository root to walk (default: $HERMES_REPO_ROOT "
                        "or /home/nofidofi/NofiTech-Ind).")
    p.add_argument("--stats-only", action="store_true",
                   help="Print current node/edge counts and exit (no write).")
    p.add_argument("--max-events", type=int, default=5000,
                   help="Cap events ingested per events.jsonl (default 5000).")
    args = p.parse_args()

    repo_root = (args.repo or os.environ.get("HERMES_REPO_ROOT")
                 or "/home/nofidofi/NofiTech-Ind")
    repo = Path(repo_root).expanduser().resolve()
    if not repo.is_dir():
        _print(f"ERROR: repo root not a directory: {repo}")
        return 2

    db = global_db_path()
    _print(f"db: {db}")
    _print(f"repo: {repo}")

    # Always initialise the store (idempotent open + WAL setup).
    store = init_global_store()

    if args.stats_only:
        _print(f"current: {store.node_count()} nodes / {store.edge_count()} edges")
        return 0

    n_before = store.node_count()
    e_before = store.edge_count()
    _print(f"before: {n_before} nodes / {e_before} edges")

    stats = store.bulk_seed(
        repo_root=repo,
        max_event_lines=args.max_events,
    )

    n_after = store.node_count()
    e_after = store.edge_count()
    delta_n = n_after - n_before
    delta_e = e_after - e_before
    _print(f"after:  {n_after} nodes / {e_after} edges  "
           f"(+{delta_n} nodes, +{delta_e} edges)")
    _print("seed stats:")
    for k, v in (stats or {}).items():
        _print(f"  {k:>24}: {v}")

    # Emit a compact summary line for cron / log scraping.
    summary = {
        "ok": True,
        "task": "MC-LIVE-MEMORY-GRAPH-1",
        "before": {"nodes": n_before, "edges": e_before},
        "after": {"nodes": n_after, "edges": e_after},
        "delta": {"nodes": delta_n, "edges": delta_e},
        "stats": stats,
    }
    _print(f"summary: {json.dumps(summary, ensure_ascii=False)}")

    if n_after < 100:
        _print(f"WARNING: only {n_after} nodes after seed (target >= 100).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        _print(f"FATAL: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
