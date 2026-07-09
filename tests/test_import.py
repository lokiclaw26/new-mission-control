#!/usr/bin/env python3
"""
test_import.py — the importer parses the 5 documented source types.

Each test creates a tiny in-tmp-dir universe:
  - 00_company_os/events.jsonl
  - 00_company_os/memory-log.md
  - 00_company_os/04_agents/state.json
  - 00_company_os/04_agents/logs/<date>/<agent>.md
  - 01_projects/<project>/tasks/<task>.md

All tmp dirs are created under /home/nofidofi/NofiTech-Ind (allowlisted
root) so the importer's assert_safe_path() check passes.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "code"))

from memory_graph_global import (  # noqa: E402
    GlobalMemoryGraphStore,
    reset_global_store,
)
from memory_graph_import import MemoryGraphImporter  # noqa: E402


def _make_universe(tmp: Path) -> Path:
    """Create a tiny NofiTech-shaped repo under `tmp` and return its root."""
    repo = tmp
    (repo / "00_company_os").mkdir(parents=True, exist_ok=True)
    (repo / "00_company_os" / "04_agents" / "logs" / "2026-06-17").mkdir(
        parents=True, exist_ok=True
    )
    (repo / "01_projects" / "mission-control" / "tasks").mkdir(
        parents=True, exist_ok=True
    )
    (repo / "01_projects" / "mission-control" / "data").mkdir(
        parents=True, exist_ok=True
    )
    return repo


class ImporterParseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mg-import-",
                                         dir="/home/nofidofi/NofiTech-Ind"))
        self.repo = _make_universe(self.tmp)
        self.db = self.tmp / "mg.sqlite3"
        self.store = GlobalMemoryGraphStore(self.db)
        self.imp = MemoryGraphImporter(store=self.store, repo_root=self.repo)
        reset_global_store()

    def tearDown(self):
        try:
            self.store.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    # (a) events.jsonl ----------------------------------------------------

    def test_parses_events_jsonl(self):
        events = self.repo / "00_company_os" / "events.jsonl"
        events.write_text(
            json.dumps({
                "ts": "2026-06-17T10:00:00+00:00",
                "actor": "nofi",
                "event_type": "task_created",
                "project": "mission-control",
                "task_id": "MC-IMP-1",
                "title": "test event",
                "message": "hello",
                "status": "triage",
            }) + "\n",
            encoding="utf-8",
        )
        self.imp.incremental()
        self.assertTrue(self.store.has_node("task:MC-IMP-1"))
        self.assertTrue(self.store.has_node("project:mission-control"))
        # event node id is namespaced; sha1 fallback if no task_id
        self.assertTrue(self.store.has_node("event:MC-IMP-1"))

    # (b) memory-log.md ---------------------------------------------------

    def test_parses_memory_log(self):
        log = self.repo / "00_company_os" / "memory-log.md"
        log.write_text(
            "# Memory Log\n\n"
            "### 001. First decision\n"
            "- **When:** 2026-06-17\n"
            "- **Decision:** Built first test.\n\n"
            "### 002. Second decision\n"
            "- **When:** 2026-06-17\n"
            "- **Decision:** Did the second test.\n",
            encoding="utf-8",
        )
        self.imp.incremental()
        # Two decisions → 2 nodes.
        nodes = self.store.node_count()
        # (also gets company + 3 agents via bootstrap)
        self.assertGreaterEqual(nodes, 5)
        # At least one decision: <sha1> id must exist.
        kinds = list(self.store.counts_by_kind().keys())
        self.assertIn("decision", kinds)

    # (c) 04_agents/state.json -------------------------------------------

    def test_parses_agents_state(self):
        st = self.repo / "00_company_os" / "04_agents" / "state.json"
        st.write_text(json.dumps({
            "agents": {
                "thor": {"status": "active",
                         "current_assignment": "MC-IMP-2",
                         "last_activity": "2026-06-17T10:00:00Z"},
                "forge": {"status": "spawning",
                          "current_assignment": "MC-IMP-2",
                          "last_activity": "2026-06-17T10:00:00Z"},
            }
        }), encoding="utf-8")
        self.imp.incremental()
        self.assertTrue(self.store.has_node("agent:thor"))
        self.assertTrue(self.store.has_node("agent:forge"))

    # (d) 04_agents/logs/<date>/<agent>.md -------------------------------

    def test_parses_agent_log(self):
        log = self.repo / "00_company_os" / "04_agents" / "logs" / "2026-06-17" / "forge-test.md"
        log.write_text(
            "---\n"
            "task_id: MC-IMP-3\n"
            "agent: forge\n"
            "role: Builder\n"
            "project: mission-control\n"
            "status: complete\n"
            "created: 2026-06-17T10:00:00+04:00\n"
            "---\n\n"
            "# Forge Build Log — MC-IMP-3\n\n"
            "Did the thing.\n",
            encoding="utf-8",
        )
        self.imp.incremental()
        self.assertTrue(self.store.has_node("task:MC-IMP-3"))
        self.assertTrue(self.store.has_node("agent:forge"))
        # file: node
        self.assertTrue(self.store.has_node(
            "file:00_company_os/04_agents/logs/2026-06-17/forge-test.md"
        ))

    # (e) 01_projects/<project>/tasks/<task>.md ---------------------------

    def test_parses_task_file(self):
        t = self.repo / "01_projects" / "mission-control" / "tasks" / "MC-001-overview-panel.md"
        t.write_text(
            "---\n"
            "id: MC-001\n"
            "title: Stage 4 — Overview panel\n"
            "project: mission-control\n"
            "agent: forge\n"
            "assigned_to: forge\n"
            "status: done\n"
            "priority: P0\n"
            "created: 2026-06-10\n"
            "updated: 2026-06-10\n"
            "description: Add 6th field (warnings) to Overview panel\n"
            "---\n\n"
            "Stage 4 shipped.\n",
            encoding="utf-8",
        )
        self.imp.incremental()
        self.assertTrue(self.store.has_node("task:MC-001"))
        self.assertTrue(self.store.has_node("project:mission-control"))
        self.assertTrue(self.store.has_node("agent:forge"))


if __name__ == "__main__":
    unittest.main()
