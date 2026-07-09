#!/usr/bin/env python3
"""
test_scoped_api.py — MemoryGraphAPI scoped-query behaviour.

We test the API handlers directly (no HTTP server) by synthesising a
minimal BaseHTTPRequestHandler-like object whose .path is set to
the request URL we want to simulate.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "code"))

from memory_graph_global import GlobalMemoryGraphStore  # noqa: E402
from memory_graph_api import get_graph, get_events_recent  # noqa: E402


class _FakeHandler:
    """Minimal stand-in for BaseHTTPRequestHandler. Only `.path` is
    needed by get_graph / get_events_recent."""
    def __init__(self, path: str):
        self.path = path
        self.headers = {}
        self.client_address = ("127.0.0.1", 0)


def _seed(store: GlobalMemoryGraphStore) -> None:
    """Populate a small but multi-project/multi-agent graph."""
    nodes = [
        # project nodes
        {"id": "project:mission-control", "kind": "project",
         "label": "MC", "importance": 0.8,
         "project": "mission-control"},
        {"id": "project:roguelike-v1", "kind": "project",
         "label": "RL", "importance": 0.7,
         "project": "roguelike-v1"},
        # task nodes
        {"id": "task:MC-001", "kind": "task", "label": "MC-001",
         "importance": 0.6, "project": "mission-control",
         "agent": "forge", "created": "2026-06-10T10:00:00+00:00",
         "updated": "2026-06-15T10:00:00+00:00"},
        {"id": "task:MC-002", "kind": "task", "label": "MC-002",
         "importance": 0.6, "project": "mission-control",
         "agent": "forge", "created": "2026-06-16T10:00:00+00:00",
         "updated": "2026-06-17T10:00:00+00:00"},
        {"id": "task:RL-001", "kind": "task", "label": "RL-001",
         "importance": 0.5, "project": "roguelike-v1",
         "agent": "thor", "created": "2026-06-11T10:00:00+00:00",
         "updated": "2026-06-12T10:00:00+00:00"},
        # agent nodes
        {"id": "agent:forge", "kind": "agent", "label": "Forge",
         "importance": 0.9, "agent": "forge"},
        {"id": "agent:thor", "kind": "agent", "label": "Thor",
         "importance": 0.9, "agent": "thor"},
        {"id": "agent:argus", "kind": "agent", "label": "Argus",
         "importance": 0.9, "agent": "argus"},
    ]
    for n in nodes:
        store.upsert_node(n)
    edges = [
        {"source": "project:mission-control", "target": "task:MC-001",
         "kind": "contains"},
        {"source": "project:mission-control", "target": "task:MC-002",
         "kind": "contains"},
        {"source": "project:roguelike-v1", "target": "task:RL-001",
         "kind": "contains"},
        {"source": "agent:forge", "target": "task:MC-001",
         "kind": "assigned_to"},
        {"source": "agent:forge", "target": "task:MC-002",
         "kind": "assigned_to"},
        {"source": "agent:thor", "target": "task:RL-001",
         "kind": "assigned_to"},
    ]
    for e in edges:
        store.upsert_edge(e)


class ScopedApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mg-scope-",
                                         dir="/home/nofidofi/NofiTech-Ind"))
        self.db = self.tmp / "mg.sqlite3"
        self.store = GlobalMemoryGraphStore(self.db)
        # Patch the API module's global store singleton to use ours.
        import memory_graph_global as _g
        import memory_graph_api as _a
        _g._STORE = self.store
        _a.get_global_store = _g.get_global_store
        _a.init_global_store = lambda *a, **k: _g.init_global_store(self.db)
        _seed(self.store)

    def tearDown(self):
        try:
            self.store.close()
        except Exception:
            pass
        import memory_graph_global as _g
        _g._STORE = None
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_scope_all_returns_more_than_project(self):
        status, g_all = get_graph(_FakeHandler("/api/memory-graph?scope=all"))
        self.assertEqual(status, 200)
        status, g_mc = get_graph(
            _FakeHandler("/api/memory-graph?scope=project&project=mission-control")
        )
        self.assertEqual(status, 200)
        self.assertGreater(g_all["node_count"], g_mc["node_count"])

    def test_scope_project_mission_control(self):
        status, g = get_graph(
            _FakeHandler("/api/memory-graph?scope=project&project=mission-control")
        )
        ids = {n["id"] for n in g["nodes"]}
        self.assertIn("task:MC-001", ids)
        self.assertIn("task:MC-002", ids)
        self.assertNotIn("task:RL-001", ids)

    def test_agent_filter_returns_forge_nodes(self):
        status, g = get_graph(_FakeHandler("/api/memory-graph?agent=forge"))
        ids = {n["id"] for n in g["nodes"]}
        # task nodes assigned to forge.
        self.assertIn("task:MC-001", ids)
        self.assertIn("task:MC-002", ids)
        # thor-only nodes should be excluded.
        self.assertNotIn("task:RL-001", ids)

    def test_kind_filter_returns_only_task_kind(self):
        status, g = get_graph(_FakeHandler("/api/memory-graph?kind=task"))
        for n in g["nodes"]:
            self.assertEqual(n["kind"], "task")

    def test_kind_filter_multi_value(self):
        status, g = get_graph(_FakeHandler("/api/memory-graph?kind=task,agent"))
        kinds = {n["kind"] for n in g["nodes"]}
        self.assertTrue(kinds.issubset({"task", "agent"}))
        self.assertIn("task", kinds)
        self.assertIn("agent", kinds)

    def test_since_excludes_older_events(self):
        status, g = get_graph(
            _FakeHandler("/api/memory-graph?since=2026-06-15T00:00:00+00:00")
        )
        # MC-001 (updated 2026-06-15) should be included; MC-002 too.
        ids = {n["id"] for n in g["nodes"]}
        self.assertIn("task:MC-002", ids)
        # RL-001 (updated 2026-06-12) excluded.
        self.assertNotIn("task:RL-001", ids)

    def test_importance_floor(self):
        status, g = get_graph(_FakeHandler("/api/memory-graph?importance=0.8"))
        for n in g["nodes"]:
            self.assertGreaterEqual(n["importance"], 0.8)

    def test_response_shape(self):
        status, g = get_graph(_FakeHandler("/api/memory-graph?scope=all"))
        self.assertEqual(status, 200)
        for k in ("nodes", "edges", "metadata", "last_updated",
                  "node_count", "edge_count"):
            self.assertIn(k, g)


if __name__ == "__main__":
    unittest.main()
