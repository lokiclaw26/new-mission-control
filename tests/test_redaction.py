#!/usr/bin/env python3
"""
test_redaction.py — Field-aware redaction tests.

The KEY test: task IDs like `task-MC-MEMORY-GRAPH-3` must NEVER be mangled.
Real-looking secrets (sk-..., ghp_..., Bearer ...) must be stripped.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "code"))

from security import redact_secrets, SECRET_KEYS, GRAPH_KEYS, FREETEXT_KEYS  # noqa: E402


class TaskIdPreservationTests(unittest.TestCase):
    """The bug NOFI reported: the old redactor ate substrings of IDs."""

    def test_task_id_unchanged(self):
        obj = {"id": "task-MC-MEMORY-GRAPH-3", "kind": "task",
               "label": "Normal label"}
        out = redact_secrets(obj)
        self.assertEqual(out["id"], "task-MC-MEMORY-GRAPH-3")
        self.assertEqual(out["kind"], "task")
        self.assertEqual(out["label"], "Normal label")

    def test_long_task_id_unchanged(self):
        nid = "task-MC-MEMORY-GRAPH-3A-BACKEND-2026-06-17"
        obj = {"id": nid, "source": "task-A", "target": "task-B"}
        out = redact_secrets(obj)
        self.assertEqual(out["id"], nid)
        self.assertEqual(out["source"], "task-A")
        self.assertEqual(out["target"], "task-B")

    def test_agent_id_unchanged(self):
        obj = {"id": "agent-thor", "kind": "entity",
               "tags": ["agent", "ceo"]}
        out = redact_secrets(obj)
        self.assertEqual(out["id"], "agent-thor")
        self.assertEqual(out["kind"], "entity")
        self.assertEqual(out["tags"], ["agent", "ceo"])

    def test_kind_field_unchanged(self):
        obj = {"id": "x", "kind": "task", "weight": 0.7,
               "importance": 0.9, "confidence": 0.8}
        out = redact_secrets(obj)
        self.assertEqual(out["kind"], "task")
        self.assertEqual(out["weight"], 0.7)


class SecretStrippingTests(unittest.TestCase):
    def test_api_key_redacted(self):
        obj = {"metadata": {"api_key": "sk-abcdefghijklmnop12345"}}
        out = redact_secrets(obj)
        self.assertEqual(out["metadata"]["api_key"], "[REDACTED]")

    def test_password_redacted(self):
        obj = {"config": {"password": "supersecret123"}}
        out = redact_secrets(obj)
        self.assertEqual(out["config"]["password"], "[REDACTED]")

    def test_token_redacted(self):
        obj = {"session": {"token": "abcdefghijklmnop"}}
        out = redact_secrets(obj)
        self.assertEqual(out["session"]["token"], "[REDACTED]")

    def test_bearer_in_freetext_redacted(self):
        obj = {"summary": "Call me with Bearer abcdefghijklmnop"}
        out = redact_secrets(obj)
        self.assertNotIn("abcdefghijklmnop", out["summary"])
        self.assertIn("[REDACTED]", out["summary"])

    def test_github_token_in_freetext_redacted(self):
        obj = {"summary": "leaked ghp_abcdefghijklmnopqrstuvwxyz"}
        out = redact_secrets(obj)
        self.assertNotIn("ghp_abcdefghijklmnopqrstuvwxyz", out["summary"])
        self.assertIn("[REDACTED]", out["summary"])

    def test_openai_key_in_freetext_redacted(self):
        obj = {"note": "sk-abcdefghijklmnop12345 was here"}
        out = redact_secrets(obj)
        self.assertNotIn("sk-abcdefghijklmnop12345", out["note"])
        self.assertIn("[REDACTED]", out["note"])

    def test_jwt_in_freetext_redacted(self):
        obj = {"log": "Got JWT eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c back"}
        out = redact_secrets(obj)
        self.assertNotIn("eyJhbGciOi", out["log"])
        self.assertIn("[JWT]", out["log"])

    def test_long_freetext_truncated(self):
        long = "x" * 1000
        obj = {"summary": long}
        out = redact_secrets(obj)
        self.assertTrue(out["summary"].endswith("...[truncated]"))
        self.assertLess(len(out["summary"]), 600)


class MixedStructureTests(unittest.TestCase):
    def test_nested_dict_with_id_and_secret(self):
        obj = {
            "id": "task-X",
            "kind": "task",
            "metadata": {"api_key": "sk-abcdefghijklmnop12345",
                         "tags": ["foo", "bar"]},
        }
        out = redact_secrets(obj)
        self.assertEqual(out["id"], "task-X")
        self.assertEqual(out["metadata"]["api_key"], "[REDACTED]")
        self.assertEqual(out["metadata"]["tags"], ["foo", "bar"])

    def test_list_of_nodes(self):
        nodes = [
            {"id": "task-A", "kind": "task"},
            {"id": "task-B", "kind": "task",
             "metadata": {"password": "leaked"}},
        ]
        out = redact_secrets(nodes)
        self.assertEqual(out[0]["id"], "task-A")
        self.assertEqual(out[1]["id"], "task-B")
        self.assertEqual(out[1]["metadata"]["password"], "[REDACTED]")

    def test_secret_keys_set_is_comprehensive(self):
        # Sanity: ensure the documented keys are all present.
        required = {"api_key", "password", "secret", "bearer",
                    "access_token", "refresh_token"}
        missing = required - SECRET_KEYS
        self.assertFalse(missing, f"SECRET_KEYS missing: {missing}")

    def test_graph_keys_set_includes_ids(self):
        required = {"id", "source", "target", "kind", "label",
                    "task_id", "created", "updated", "weight"}
        missing = required - GRAPH_KEYS
        self.assertFalse(missing, f"GRAPH_KEYS missing: {missing}")

    def test_freetext_keys_includes_summary(self):
        required = {"summary", "message", "body", "description"}
        missing = required - FREETEXT_KEYS
        self.assertFalse(missing, f"FREETEXT_KEYS missing: {missing}")


class RealisticMemoryEventTests(unittest.TestCase):
    """End-to-end look-alike events from the real UI."""

    def test_node_upsert_event(self):
        event = {
            "type": "node.upsert",
            "node": {
                "id": "task-MC-MEMORY-GRAPH-3",
                "kind": "task",
                "label": "Backend hardening",
                "summary": "Includes ghp_abcdefghijklmnopqrstuvwxyz leaked",
            },
        }
        out = redact_secrets(event)
        self.assertEqual(out["node"]["id"], "task-MC-MEMORY-GRAPH-3")
        self.assertEqual(out["node"]["kind"], "task")
        self.assertNotIn("ghp_abcdefghijklmnopqrstuvwxyz", out["node"]["summary"])
        self.assertIn("[REDACTED]", out["node"]["summary"])

    def test_edge_event(self):
        event = {
            "type": "edge.upsert",
            "edge": {
                "source": "task-A",
                "target": "status-running_now",
                "kind": "kanban_status",
            },
        }
        out = redact_secrets(event)
        self.assertEqual(out["edge"]["source"], "task-A")
        self.assertEqual(out["edge"]["target"], "status-running_now")
        self.assertEqual(out["edge"]["kind"], "kanban_status")


if __name__ == "__main__":
    unittest.main()
