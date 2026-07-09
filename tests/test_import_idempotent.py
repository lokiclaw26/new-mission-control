#!/usr/bin/env python3
"""
test_import_idempotent.py — running the importer twice must NOT
produce duplicate nodes or edges.
"""
import json
import shutil
import sys
import os
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "code"))

from memory_graph_global import GlobalMemoryGraphStore, reset_global_store  # noqa: E402
from memory_graph_import import MemoryGraphImporter  # noqa: E402


class IdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mg-idem-",
                                         dir=os.environ.get("NOFITECH_ROOT") or "/home/nofidofi/NofiTech-Ind"))
        self.repo = self.tmp
        (self.repo / "00_company_os").mkdir(parents=True, exist_ok=True)
        (self.repo / "00_company_os" / "04_agents" / "logs" / "2026-06-17").mkdir(
            parents=True, exist_ok=True
        )
        (self.repo / "01_projects" / "mission-control" / "tasks").mkdir(
            parents=True, exist_ok=True
        )
        (self.repo / "01_projects" / "mission-control" / "data").mkdir(
            parents=True, exist_ok=True
        )
        # One event, one task, one log, one state.
        (self.repo / "00_company_os" / "events.jsonl").write_text(
            json.dumps({
                "ts": "2026-06-17T10:00:00+00:00",
                "actor": "nofi",
                "event_type": "task_created",
                "project": "mission-control",
                "task_id": "MC-IDEM-1",
                "title": "test",
            }) + "\n",
            encoding="utf-8",
        )
        (self.repo / "00_company_os" / "04_agents" / "state.json").write_text(
            json.dumps({"agents": {"forge": {"status": "active",
                                              "current_assignment": "MC-IDEM-1",
                                              "last_activity": "2026-06-17T10:00:00Z"}}}),
            encoding="utf-8",
        )
        (self.repo / "00_company_os" / "04_agents" / "logs" / "2026-06-17" / "forge.md").write_text(
            "---\n"
            "task_id: MC-IDEM-1\nagent: forge\nrole: Builder\nproject: mission-control\n"
            "status: complete\ncreated: 2026-06-17T10:00:00+04:00\n---\n\n"
            "Body.\n",
            encoding="utf-8",
        )
        (self.repo / "01_projects" / "mission-control" / "tasks" / "MC-IDEM-1.md").write_text(
            "---\nid: MC-IDEM-1\ntitle: Idem test\nproject: mission-control\n"
            "agent: forge\nstatus: done\ncreated: 2026-06-17\n---\n\nBody.\n",
            encoding="utf-8",
        )
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

    def test_full_rebuild_idempotent(self):
        s1 = self.imp.full_rebuild()
        n1 = self.store.node_count()
        e1 = self.store.edge_count()
        s2 = self.imp.full_rebuild()
        n2 = self.store.node_count()
        e2 = self.store.edge_count()
        self.assertEqual(n1, n2, f"node count changed: {n1} -> {n2}")
        self.assertEqual(e1, e2, f"edge count changed: {e1} -> {e2}")

    def test_incremental_idempotent(self):
        self.imp.full_rebuild()
        n1 = self.store.node_count()
        e1 = self.store.edge_count()
        # Run incremental 3 more times.
        for _ in range(3):
            self.imp.incremental()
        n4 = self.store.node_count()
        e4 = self.store.edge_count()
        self.assertEqual(n1, n4)
        self.assertEqual(e1, e4)


if __name__ == "__main__":
    unittest.main()
