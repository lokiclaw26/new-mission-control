#!/usr/bin/env python3
"""
test_import_no_dangling.py — every edge has both endpoints present
in the nodes table after a full rebuild.
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


class NoDanglingEdgesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mg-dangle-",
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
                "task_id": "MC-DG-1",
                "title": "test",
            }) + "\n",
            encoding="utf-8",
        )
        (self.repo / "00_company_os" / "04_agents" / "state.json").write_text(
            json.dumps({"agents": {"forge": {"status": "active",
                                              "current_assignment": "MC-DG-1",
                                              "last_activity": "2026-06-17T10:00:00Z"}}}),
            encoding="utf-8",
        )
        (self.repo / "00_company_os" / "04_agents" / "logs" / "2026-06-17" / "forge.md").write_text(
            "---\ntask_id: MC-DG-1\nagent: forge\nrole: Builder\nproject: mission-control\n"
            "status: complete\ncreated: 2026-06-17T10:00:00+04:00\n---\n\nBody.\n",
            encoding="utf-8",
        )
        (self.repo / "01_projects" / "mission-control" / "tasks" / "MC-DG-1.md").write_text(
            "---\nid: MC-DG-1\ntitle: DG test\nproject: mission-control\n"
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

    def _check_dangling(self) -> list[str]:
        with self.store._lock:
            ids = {r[0] for r in self.store._conn.execute("SELECT id FROM nodes").fetchall()}
            edges = self.store._conn.execute(
                "SELECT source, target FROM edges"
            ).fetchall()
        dangle: list[str] = []
        for src, tgt in edges:
            if src not in ids:
                dangle.append(f"missing source: {src}")
            if tgt not in ids:
                dangle.append(f"missing target: {tgt}")
        return dangle

    def test_no_dangling_edges_after_full_rebuild(self):
        self.imp.full_rebuild()
        dangle = self._check_dangling()
        self.assertEqual(dangle, [], f"dangling edges: {dangle}")

    def test_no_dangling_edges_after_incremental(self):
        self.imp.incremental()
        dangle = self._check_dangling()
        self.assertEqual(dangle, [], f"dangling edges: {dangle}")


if __name__ == "__main__":
    unittest.main()
