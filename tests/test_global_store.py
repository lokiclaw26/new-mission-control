#!/usr/bin/env python3
"""
test_global_store.py — global path resolution, init, idempotent open.

Uses a tmp dir under /home/nofidofi/NofiTech-Ind (allowlisted root) so
the safety check passes. Tmp dirs under /tmp would be refused by
assert_safe_path.
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "code"))

from memory_graph_global import (  # noqa: E402
    GlobalMemoryGraphStore,
    init_global_store,
    reset_global_store,
    get_global_store,
    global_db_path,
    global_dir,
    assert_safe_path,
    load_scoped_from_request,
)


class PathResolutionTests(unittest.TestCase):
    def test_global_dir_under_repo(self):
        d = global_dir()
        self.assertTrue(d.is_absolute())
        self.assertTrue(str(d).startswith("/home/nofidofi/NofiTech-Ind"))
        self.assertTrue(d.name == "memory")

    def test_global_db_path_is_under_global_dir(self):
        p = global_db_path()
        d = global_dir()
        self.assertEqual(p.parent, d)
        self.assertEqual(p.name, "memory-graph.sqlite3")

    def test_assert_safe_path_accepts_repo(self):
        p = Path("/home/nofidofi/NofiTech-Ind/00_company_os/memory-log.md")
        self.assertTrue(assert_safe_path(p))

    def test_assert_safe_path_accepts_hermes_cron(self):
        p = Path("/home/nofidofi/.hermes/cron/output/abc/summary.md")
        self.assertTrue(assert_safe_path(p))

    def test_assert_safe_path_rejects_etc(self):
        p = Path("/etc/passwd")
        self.assertFalse(assert_safe_path(p))

    def test_assert_safe_path_rejects_tmp(self):
        p = Path("/tmp/whatever")
        self.assertFalse(assert_safe_path(p))


class InitAndOpenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mg-global-",
                                         dir="/home/nofidofi/NofiTech-Ind"))
        self.db = self.tmp / "memory-graph.sqlite3"

    def tearDown(self):
        reset_global_store()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_init_creates_db_at_right_path(self):
        self.assertFalse(self.db.exists())
        s = GlobalMemoryGraphStore(self.db)
        self.assertTrue(self.db.exists())
        self.assertEqual(s.db_path.resolve(), self.db.resolve())
        s.close()

    def test_idempotent_open(self):
        s1 = GlobalMemoryGraphStore(self.db)
        s1.upsert_node({"id": "company:test", "kind": "company",
                         "label": "T", "summary": "T", "importance": 0.5})
        s1.close()
        s2 = GlobalMemoryGraphStore(self.db)
        self.assertTrue(s2.has_node("company:test"))
        s2.close()

    def test_init_global_store_idempotent(self):
        s = init_global_store(self.db)
        s2 = init_global_store(self.db)
        self.assertIs(s, s2)
        reset_global_store()
        s3 = init_global_store(self.db)
        self.assertIsNot(s, s3)

    def test_get_global_store_after_init(self):
        init_global_store(self.db)
        s = get_global_store()
        self.assertEqual(s.db_path.resolve(), self.db.resolve())

    def test_reject_db_outside_allowlist(self):
        bad = Path("/tmp/mg-bad.sqlite3")
        with self.assertRaises(RuntimeError):
            GlobalMemoryGraphStore(bad)


class ScopedQueryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mg-global-",
                                         dir="/home/nofidofi/NofiTech-Ind"))
        self.db = self.tmp / "memory-graph.sqlite3"
        self.s = GlobalMemoryGraphStore(self.db)
        # Seed a tiny graph.
        for n in [
            {"id": "project:mission-control", "kind": "project",
             "label": "MC", "importance": 0.7, "project": "mission-control"},
            {"id": "project:roguelike-v1", "kind": "project",
             "label": "RL", "importance": 0.7, "project": "roguelike-v1"},
            {"id": "task:MC-001", "kind": "task", "label": "T1",
             "importance": 0.5, "project": "mission-control", "agent": "forge"},
            {"id": "task:RL-001", "kind": "task", "label": "T2",
             "importance": 0.5, "project": "roguelike-v1", "agent": "thor"},
            {"id": "agent:forge", "kind": "agent", "label": "Forge",
             "importance": 0.8, "agent": "forge"},
            {"id": "agent:thor", "kind": "agent", "label": "Thor",
             "importance": 0.8, "agent": "thor"},
        ]:
            self.s.upsert_node(n)
        self.s.upsert_edge({"id": "e1", "source": "project:mission-control",
                            "target": "task:MC-001", "kind": "contains",
                            "weight": 0.8})
        self.s.upsert_edge({"id": "e2", "source": "agent:forge",
                            "target": "task:MC-001", "kind": "assigned_to",
                            "weight": 0.7})

    def tearDown(self):
        self.s.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_scope_all_returns_everything(self):
        g = self.s.load_scoped(scope="all")
        self.assertGreaterEqual(g["node_count"], 6)

    def test_scope_project_filters_to_project(self):
        g = self.s.load_scoped(scope="project", project="mission-control")
        ids = {n["id"] for n in g["nodes"]}
        self.assertIn("task:MC-001", ids)
        self.assertNotIn("task:RL-001", ids)

    def test_scope_agent_filters_to_agent(self):
        g = self.s.load_scoped(scope="agent", agent="forge")
        ids = {n["id"] for n in g["nodes"]}
        self.assertIn("task:MC-001", ids)
        self.assertNotIn("task:RL-001", ids)

    def test_kind_filter(self):
        g = self.s.load_scoped(kind="task")
        for n in g["nodes"]:
            self.assertEqual(n["kind"], "task")

    def test_importance_floor(self):
        g = self.s.load_scoped(importance=0.7)
        for n in g["nodes"]:
            self.assertGreaterEqual(n["importance"], 0.7)

    def test_response_shape_is_compatible(self):
        g = self.s.load_scoped(scope="all")
        for k in ("nodes", "edges", "metadata", "last_updated",
                  "node_count", "edge_count"):
            self.assertIn(k, g)
        self.assertIsInstance(g["nodes"], list)
        self.assertIsInstance(g["edges"], list)

    def test_load_scoped_from_request_parses_query(self):
        g = load_scoped_from_request("/api/memory-graph?scope=project&project=mission-control")
        ids = {n["id"] for n in g["nodes"]}
        self.assertIn("task:MC-001", ids)
        self.assertNotIn("task:RL-001", ids)


if __name__ == "__main__":
    unittest.main()
