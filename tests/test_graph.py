#!/usr/bin/env python3
"""
test_graph.py — Validation + dangling-edge handling for the memory graph.

Uses an in-memory SQLite (via the file-based store, in a tmp dir) so we
exercise the real code path that serve.py uses.
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "code"))

from memory_graph_store import (  # noqa: E402
    MemoryGraphStore, init_store, get_store, validate_node, validate_edge,
    MG_VALID_NODE_KINDS,
)


class NodeValidationTests(unittest.TestCase):
    def test_minimal_node(self):
        node, errs = validate_node({"id": "task-A", "kind": "task"})
        self.assertEqual(errs, [])
        self.assertEqual(node["id"], "task-A")
        self.assertEqual(node["kind"], "task")
        self.assertEqual(node["importance"], 0.5)
        self.assertEqual(node["confidence"], 0.5)

    def test_missing_id_returns_error(self):
        _, errs = validate_node({"kind": "task"})
        self.assertTrue(any("id" in e for e in errs))

    def test_bad_id_chars_rejected(self):
        _, errs = validate_node({"id": "bad id with spaces!"})
        self.assertTrue(any("id" in e for e in errs))

    def test_id_too_long_rejected(self):
        _, errs = validate_node({"id": "a" * 201})
        self.assertTrue(any("id" in e for e in errs))

    def test_unknown_kind_defaults_to_concept(self):
        node, errs = validate_node({"id": "x", "kind": "martian"})
        self.assertEqual(errs, [])
        self.assertEqual(node["kind"], "concept")

    def test_importance_clamped(self):
        node, _ = validate_node({"id": "x", "importance": 1.7})
        self.assertEqual(node["importance"], 1.0)
        node, _ = validate_node({"id": "x", "importance": -0.2})
        self.assertEqual(node["importance"], 0.0)

    def test_confidence_clamped(self):
        node, _ = validate_node({"id": "x", "confidence": "not a number"})
        self.assertEqual(node["confidence"], 0.5)  # default

    def test_label_truncated(self):
        node, _ = validate_node({"id": "x", "label": "x" * 1000})
        self.assertEqual(len(node["label"]), 500)

    def test_summary_truncated(self):
        node, _ = validate_node({"id": "x", "summary": "x" * 10000})
        self.assertEqual(len(node["summary"]), 5000)

    def test_all_valid_kinds_accepted(self):
        for k in MG_VALID_NODE_KINDS:
            node, errs = validate_node({"id": f"x-{k}", "kind": k})
            self.assertEqual(errs, [], f"kind {k} should validate")
            self.assertEqual(node["kind"], k)


class EdgeValidationTests(unittest.TestCase):
    def test_minimal_edge(self):
        edge, errs = validate_edge({"source": "A", "target": "B"})
        self.assertEqual(errs, [])
        self.assertEqual(edge["id"], "edge-A-B-relates_to")
        self.assertEqual(edge["weight"], 0.5)

    def test_missing_source(self):
        _, errs = validate_edge({"target": "B"})
        self.assertTrue(any("source" in e for e in errs))

    def test_missing_target(self):
        _, errs = validate_edge({"source": "A"})
        self.assertTrue(any("target" in e for e in errs))

    def test_weight_clamped(self):
        edge, _ = validate_edge({"source": "A", "target": "B", "weight": 5.0})
        self.assertEqual(edge["weight"], 1.0)

    def test_explicit_id_preserved(self):
        edge, _ = validate_edge({"source": "A", "target": "B",
                                 "id": "custom-id"})
        self.assertEqual(edge["id"], "custom-id")


class StoreIntegrationTests(unittest.TestCase):
    """Exercise the SQLite store end-to-end in a temp dir."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mg-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _store(self):
        return MemoryGraphStore(self.tmp)

    def test_empty_graph_loads(self):
        s = self._store()
        s.migrate_from_json_if_needed()
        g = s.load_graph()
        self.assertEqual(g["node_count"], 0)
        self.assertEqual(g["edge_count"], 0)

    def test_node_upsert_then_load(self):
        s = self._store()
        s.migrate_from_json_if_needed()
        r = s.ingest_event({"type": "node.upsert",
                            "node": {"id": "task-A", "kind": "task",
                                     "label": "A"}})
        self.assertTrue(r["ok"])
        g = s.load_graph()
        self.assertEqual(g["node_count"], 1)
        self.assertEqual(g["nodes"][0]["id"], "task-A")

    def test_dangling_edge_auto_creates_placeholders(self):
        s = self._store()
        s.migrate_from_json_if_needed()
        r = s.ingest_event({"type": "edge.upsert",
                            "edge": {"source": "ghost-source",
                                     "target": "ghost-target",
                                     "kind": "relates_to"}})
        self.assertTrue(r["ok"])
        g = s.load_graph()
        ids = {n["id"] for n in g["nodes"]}
        self.assertIn("ghost-source", ids)
        self.assertIn("ghost-target", ids)

    def test_node_delete_cascades(self):
        s = self._store()
        s.migrate_from_json_if_needed()
        s.ingest_event({"type": "node.upsert",
                        "node": {"id": "task-A"}})
        s.ingest_event({"type": "edge.upsert",
                        "edge": {"source": "task-A", "target": "task-B"}})
        g = s.load_graph()
        self.assertEqual(g["node_count"], 2)
        self.assertEqual(g["edge_count"], 1)
        s.ingest_event({"type": "node.delete", "id": "task-A"})
        g = s.load_graph()
        self.assertEqual(g["node_count"], 1)
        self.assertEqual(g["edge_count"], 0)

    def test_repair_creates_placeholders(self):
        s = self._store()
        s.migrate_from_json_if_needed()
        # Insert a node and an edge, then delete the node without cascade
        # by using raw SQL to leave a dangling edge.
        s.ingest_event({"type": "node.upsert",
                        "node": {"id": "task-A"}})
        s.ingest_event({"type": "edge.upsert",
                        "edge": {"source": "task-A", "target": "task-B"}})
        # Manually delete the node bypassing cascade.
        s._conn.execute("DELETE FROM nodes WHERE id='task-A'")
        # repair_graph() should re-add task-A as a placeholder.
        n = s.repair_graph()
        self.assertGreaterEqual(n, 1)
        g = s.load_graph()
        ids = {nd["id"] for nd in g["nodes"]}
        self.assertIn("task-A", ids)

    def test_invalid_node_id_returns_error(self):
        s = self._store()
        s.migrate_from_json_if_needed()
        r = s.ingest_event({"type": "node.upsert",
                            "node": {"id": "bad id!"}})
        self.assertFalse(r["ok"])

    def test_unknown_event_type_raises(self):
        s = self._store()
        s.migrate_from_json_if_needed()
        with self.assertRaises(ValueError):
            s.ingest_event({"type": "nonsense.event"})

    def test_recent_events(self):
        s = self._store()
        s.migrate_from_json_if_needed()
        s.ingest_event({"type": "node.upsert",
                        "node": {"id": "task-A"}})
        s.ingest_event({"type": "node.upsert",
                        "node": {"id": "task-B"}})
        evs = s.recent_events(10)
        self.assertEqual(len(evs), 2)
        self.assertEqual(evs[-1]["type"], "node.upsert")


class JsonMigrationTests(unittest.TestCase):
    """If memory-graph.json exists in the data dir, migrate it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mg-mig-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_imports_existing_json(self):
        # Write a minimal JSON snapshot.
        sample = {
            "metadata": {"name": "test"},
            "nodes": [
                {"id": "task-X", "kind": "task", "label": "X"},
                {"id": "task-Y", "kind": "concept"},
            ],
            "edges": [
                {"id": "edge-task-X-task-Y-relates_to",
                 "source": "task-X", "target": "task-Y",
                 "kind": "relates_to"},
            ],
            "last_updated": "2026-06-17T00:00:00+00:00",
        }
        import json
        (self.tmp / "memory-graph.json").write_text(json.dumps(sample))
        s = MemoryGraphStore(self.tmp)
        migrated = s.migrate_from_json_if_needed()
        self.assertTrue(migrated)
        g = s.load_graph()
        self.assertEqual(g["node_count"], 2)
        self.assertEqual(g["edge_count"], 1)


if __name__ == "__main__":
    unittest.main()
