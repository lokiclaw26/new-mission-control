#!/usr/bin/env python3
"""
test_kanban.py — Sanity tests for kanban_service.

These exercise the data shapes and helper functions; the actual PATCH
endpoint is end-to-end exercised in test_auth.py's integration section.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "code"))

import kanban_service  # noqa: E402


class ConstantsTests(unittest.TestCase):
    def test_valid_statuses_include_running_now(self):
        self.assertIn("running_now", kanban_service.KANBAN_VALID_STATUSES)
        self.assertIn("ready", kanban_service.KANBAN_VALID_STATUSES)
        self.assertIn("done", kanban_service.KANBAN_VALID_STATUSES)

    def test_legacy_status_map_includes_running(self):
        self.assertEqual(
            kanban_service.KANBAN_LEGACY_STATUS_MAP["running"],
            "running_now",
        )

    def test_valid_assignees_includes_three_agents(self):
        for a in ("thor", "forge", "argus", ""):
            self.assertIn(a, kanban_service.KANBAN_VALID_ASSIGNEES)


class DataKanbanTests(unittest.TestCase):
    def test_data_kanban_returns_dict(self):
        result = kanban_service.data_kanban(include_archived=True)
        self.assertIsInstance(result, dict)
        # The board contract: has columns and agents lanes.
        self.assertTrue(any(k in result for k in ("columns", "lanes",
                                                  "cards", "tasks")))


class FindTaskFileTests(unittest.TestCase):
    def test_empty_id_returns_none(self):
        self.assertIsNone(kanban_service._find_task_file(""))

    def test_path_traversal_blocked(self):
        self.assertIsNone(kanban_service._find_task_file("../etc/passwd"))
        self.assertIsNone(kanban_service._find_task_file("foo/bar"))


class FrontmatterHelperTests(unittest.TestCase):
    def test_set_existing_field(self):
        text = "---\nfoo: bar\n---\nbody\n"
        out = kanban_service._set_frontmatter_field(text, "foo", "baz")
        self.assertIn("foo: baz", out)
        self.assertIn("body", out)

    def test_insert_new_field(self):
        text = "---\nfoo: bar\n---\nbody\n"
        out = kanban_service._set_frontmatter_field(text, "new", "v")
        self.assertIn("new: v", out)

    def test_remove_field_when_value_empty(self):
        text = "---\nfoo: bar\nkeep: yes\n---\nbody\n"
        out = kanban_service._set_frontmatter_field(text, "foo", "")
        self.assertNotIn("foo:", out)
        self.assertIn("keep: yes", out)


if __name__ == "__main__":
    unittest.main()
