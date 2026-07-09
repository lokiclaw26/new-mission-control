#!/usr/bin/env python3
"""
test_redaction_preserves_ids.py — make sure the field-aware redactor
in security.py NEVER mangles namespaced task IDs like `task:MC-FOO-001`
even though the underlying `sk-` regex would superficially look
dangerous (the `MC-` portion is the historical bug NOFI reported).

This is the regression test for the redactor that the new global
importer relies on (every string value passes through redact_secrets
before being written to SQLite).
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "code"))

from security import redact_secrets, _looks_like_a_secret_string  # noqa: E402


class TaskIdPreservationThroughImporterTests(unittest.TestCase):
    """The global importer's safety contract: namespaced IDs survive
    the redactor unchanged. The old `sk-[A-Za-z0-9_\-]{16,}` regex
    matched `sk-MC-...` inside `task-MC-...`; the new redactor only
    redacts whole-string secret matches, not substrings."""

    def test_task_id_preserved(self):
        nid = "task:MC-FOO-001"
        out = redact_secrets({"id": nid, "kind": "task", "label": "foo"})
        self.assertEqual(out["id"], nid)
        self.assertEqual(out["kind"], "task")
        self.assertEqual(out["label"], "foo")

    def test_long_task_id_preserved(self):
        nid = "task:MC-MEMORY-GRAPH-4-GLOBAL-2026-06-17"
        out = redact_secrets({"id": nid, "source": "task:foo",
                              "target": "task:bar"})
        self.assertEqual(out["id"], nid)
        self.assertEqual(out["source"], "task:foo")
        self.assertEqual(out["target"], "task:bar")

    def test_agent_id_preserved(self):
        for a in ("agent:thor", "agent:forge", "agent:argus"):
            out = redact_secrets({"id": a, "kind": "agent"})
            self.assertEqual(out["id"], a)
            self.assertEqual(out["kind"], "agent")

    def test_project_id_preserved(self):
        for p in ("project:mission-control", "project:diy-hub-v1",
                  "project:roguelike-v1"):
            out = redact_secrets({"id": p, "kind": "project"})
            self.assertEqual(out["id"], p)
            self.assertEqual(out["kind"], "project")

    def test_file_event_decision_error_session_tool_ids_preserved(self):
        ids = [
            "file:00_company_os/memory-log.md",
            "event:MC-MEMORY-GRAPH-4-GLOBAL",
            "decision:abcdef012345",
            "error:deadbeef0000",
            "session:2026-06-17",
            "tool:terminal",
        ]
        out = redact_secrets({"ids": ids})
        self.assertEqual(out["ids"], ids)

    def test_sk_regex_does_not_eat_mc(self):
        # Direct check on the regex pattern itself.
        out = redact_secrets("task:MC-MEMORY-GRAPH-3A-BACKEND")
        self.assertEqual(out, "task:MC-MEMORY-GRAPH-3A-BACKEND")

    def test_real_openai_key_in_freetext_still_redacted(self):
        # Make sure redaction still WORKS on real secrets.
        out = redact_secrets({"summary":
            "I have a key sk-abcdefghijklmnopqrstuvwxyz1234567890ABCD"})
        self.assertIn("sk-[REDACTED]", out["summary"])
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", out["summary"])

    def test_whole_string_secret_redacted(self):
        # If a string IS exactly a secret, it must be redacted.
        out = redact_secrets({"token": "sk-abcdefghijklmnopqrstuvwxyz1234567890ABCD"})
        self.assertEqual(out["token"], "[REDACTED]")

    def test_looks_like_a_secret_string(self):
        self.assertTrue(_looks_like_a_secret_string(
            "sk-abcdefghijklmnopqrstuvwxyz1234567890ABCD"
        ))
        self.assertFalse(_looks_like_a_secret_string("task:MC-FOO-001"))
        self.assertFalse(_looks_like_a_secret_string("agent:thor"))
        self.assertFalse(_looks_like_a_secret_string("project:mission-control"))


if __name__ == "__main__":
    unittest.main()
