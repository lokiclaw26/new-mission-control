#!/usr/bin/env python3
"""
test_overview_live.py — MC-LIVE-DASHBOARD-1 acceptance tests for /api/data/overview.

These tests verify that `data_overview()` derives every field from the
LIVE kanban board (`data_kanban()`), NOT from the stale `data_source: real`
task files + memory-log.md.

We seed a fake kanban state by monkey-patching `serve.data_kanban` (and
nothing else), then call `serve.data_overview()` and assert the derivation
rules from the spec:

  current_project  = project of any running_now task
  active_tasks     = count of kanban tasks with kanban_status=running_now
  failed_tasks     = count of kanban blocked tasks with empty blocker reason
  warnings         = blocked count + log warns count
  last_check       = now (every poll = "just polled")
  polled_at_iso    = current UTC ISO timestamp

We never touch disk: all fake state is in-memory only.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "code"))

import serve  # noqa: E402


# ---- helpers ---------------------------------------------------------------

def _make_board(columns, by_assignee=None, by_status=None):
    """Build a fake kanban board dict matching `data_kanban()`'s shape."""
    by_status = by_status or {c["id"]: c["count"] for c in columns}
    by_assignee = by_assignee or {}
    return {
        "columns": columns,
        "agents": [],
        "summary": {
            "total": sum(by_status.values()),
            "visible": sum(by_status.values()),
            "by_status": by_status,
            "by_assignee": by_assignee,
            "by_format": {"A": 0, "B": 0},
            "skipped": 0,
        },
        "warnings": [],
        "include_archived": False,
    }


def _col(col_id, tasks, count=None):
    return {
        "id": col_id,
        "label": col_id,
        "count": count if count is not None else len(tasks),
        "tasks": tasks,
    }


def _task(task_id, project, kanban_status, assigned_to=None, source_file=None):
    """Minimal kanban card shape — only the fields data_overview() reads."""
    return {
        "task_id": task_id,
        "title": task_id,
        "project": project,
        "status": kanban_status,
        "kanban_status": kanban_status,
        "assigned_to": assigned_to,
        "current_assignment": task_id,
        "source_file": source_file or f"01_projects/{project}/tasks/{task_id}.md",
    }


def _patched_overview(serve_module, board, monkey_overview=None):
    """Call data_overview() with data_kanban() stubbed to return `board`.

    `monkey_overview` is an optional extra patch path for tests that need
    to control deeper helpers (e.g. _task_has_blocker_reason).
    """
    with mock.patch.object(serve_module, "data_kanban", return_value=board):
        if monkey_overview:
            with mock.patch.object(serve_module, monkey_overview[0],
                                   side_effect=monkey_overview[1]):
                return serve_module.data_overview()
        return serve_module.data_overview()


# ---- tests -----------------------------------------------------------------

class PolledAtFieldTests(unittest.TestCase):
    """Every response MUST include a `polled_at_iso` field set to current UTC."""

    def test_polled_at_iso_present_and_iso(self):
        board = _make_board([_col("running_now", []),
                             _col("blocked", []),
                             _col("done", [])])
        out = _patched_overview(serve, board)
        self.assertIn("polled_at_iso", out)
        # Should be a parseable ISO timestamp ending in +00:00 (UTC)
        from datetime import datetime
        ts = out["polled_at_iso"]
        self.assertTrue(ts.endswith("+00:00") or ts.endswith("Z"),
                        f"polled_at_iso not UTC: {ts!r}")
        # And parseable
        datetime.fromisoformat(ts.replace("Z", "+00:00"))

    def test_last_check_value_equals_polled_at_iso(self):
        board = _make_board([_col("running_now", []),
                             _col("blocked", [])])
        out = _patched_overview(serve, board)
        self.assertEqual(out["last_check"]["value"], out["polled_at_iso"])
        # And the rel field is "live" — NO MORE "2h ago" hardcoded.
        self.assertEqual(out["last_check"]["rel"], "live")


class CurrentProjectTests(unittest.TestCase):
    """current_project must reflect live activity, NOT alphabetical first."""

    def test_current_project_from_running_now_task(self):
        board = _make_board([
            _col("running_now", [_task("LIVE-1", "mission-control", "running_now")]),
            _col("blocked", []),
        ])
        out = _patched_overview(serve, board)
        self.assertEqual(out["current_project"]["value"], "mission-control")
        self.assertIsNone(out["current_project"]["reason"])

    def test_current_project_not_alphabetical_first_when_no_running(self):
        """If no running_now tasks but there ARE recent task files in
        01_projects/, current_project should derive from those — NOT just
        pick the first subdir alphabetically."""
        # No running tasks — current_project should come from the
        # most-recent file mtime path. With a recent file under
        # 01_projects/zzz-zzz/tasks/, the mtime path picks zzz-zzz — NOT
        # the alphabetical first subdir which could be anything else.
        import tempfile
        import time as _time
        with tempfile.TemporaryDirectory() as td:
            tmp_root = Path(td)
            proj = tmp_root / "01_projects" / "zzz-zzz" / "tasks"
            proj.mkdir(parents=True)
            tf = proj / "ZZZ-1.md"
            tf.write_text("---\ntask_id: ZZZ-1\nproject: zzz-zzz\nstatus: todo\n---\n")
            import os
            os.utime(tf, (_time.time(), _time.time()))
            board = _make_board([_col("running_now", []),
                                 _col("blocked", [])])
            with mock.patch.object(serve, "COMPANY_ROOT", tmp_root):
                out = _patched_overview(serve, board)
            # Now current_project must be "zzz-zzz" — derived from mtime,
            # NOT from whatever first subdir alphabetically might be.
            self.assertEqual(out["current_project"]["value"], "zzz-zzz")


class ActiveTasksTests(unittest.TestCase):
    """active_tasks = count of kanban running_now tasks."""

    def test_active_tasks_zero_when_no_running(self):
        board = _make_board([_col("running_now", []),
                             _col("blocked", [])])
        out = _patched_overview(serve, board)
        self.assertEqual(out["active_tasks"]["value"], 0)
        self.assertEqual(out["active_tasks"]["reason"], "no tasks in running_now")

    def test_active_tasks_counts_running_now_only(self):
        """Counts running_now, not other statuses (not in_progress etc)."""
        board = _make_board([
            _col("running_now", [_task("R1", "p1", "running_now"),
                                 _task("R2", "p1", "running_now")]),
            _col("ready", [_task("RD1", "p1", "ready")]),
            _col("blocked", [_task("B1", "p1", "blocked")]),
            _col("done", [_task("D1", "p1", "done"),
                          _task("D2", "p1", "done")]),
        ])
        out = _patched_overview(serve, board)
        self.assertEqual(out["active_tasks"]["value"], 2)
        self.assertIsNone(out["active_tasks"]["reason"])

    def test_active_tasks_three_running(self):
        board = _make_board([
            _col("running_now", [
                _task("A", "p1", "running_now"),
                _task("B", "p2", "running_now"),
                _task("C", "p3", "running_now"),
            ]),
            _col("blocked", []),
        ])
        out = _patched_overview(serve, board)
        self.assertEqual(out["active_tasks"]["value"], 3)


class FailedTasksTests(unittest.TestCase):
    """failed_tasks = blocked count with EMPTY blocker reason on disk."""

    def test_failed_tasks_zero_when_blocked_have_reasons(self):
        """If every blocked task has a blocker_reason on disk → failed=0."""
        blocked_tasks = [
            _task("B1", "p1", "blocked", source_file="/abs/p1/tasks/B1.md"),
            _task("B2", "p2", "blocked", source_file="/abs/p2/tasks/B2.md"),
        ]
        board = _make_board([
            _col("running_now", []),
            _col("blocked", blocked_tasks),
        ])
        # Stub the blocker-reason check to always return True
        # (all blocked tasks have known reasons)
        with mock.patch.object(serve, "data_kanban", return_value=board), \
             mock.patch.object(serve, "_task_has_blocker_reason",
                               return_value=True):
            out = serve.data_overview()
        self.assertEqual(out["failed_tasks"]["value"], 0)

    def test_failed_tasks_counts_blocked_without_reason(self):
        """Blocked tasks WITHOUT a blocker_reason → counted as failed."""
        blocked_tasks = [
            _task("B1", "p1", "blocked"),  # no blocker
            _task("B2", "p2", "blocked"),  # no blocker
            _task("B3", "p3", "blocked"),  # no blocker
        ]
        board = _make_board([
            _col("running_now", []),
            _col("blocked", blocked_tasks),
        ])
        # Stub the blocker-reason check to always return False
        # (no blocked task has a reason → all 3 are failed)
        with mock.patch.object(serve, "data_kanban", return_value=board), \
             mock.patch.object(serve, "_task_has_blocker_reason",
                               return_value=False):
            out = serve.data_overview()
        self.assertEqual(out["failed_tasks"]["value"], 3)

    def test_failed_tasks_partial(self):
        """Mixed: 2 blocked, 1 has reason → 1 failed."""
        blocked_tasks = [
            _task("B1", "p1", "blocked"),
            _task("B2", "p2", "blocked"),
        ]
        board = _make_board([
            _col("running_now", []),
            _col("blocked", blocked_tasks),
        ])
        # B1 has reason, B2 doesn't
        def selective_reason(card):
            return card["task_id"] == "B1"
        with mock.patch.object(serve, "data_kanban", return_value=board), \
             mock.patch.object(serve, "_task_has_blocker_reason",
                               side_effect=selective_reason):
            out = serve.data_overview()
        self.assertEqual(out["failed_tasks"]["value"], 1)


class WarningsTests(unittest.TestCase):
    """warnings = blocked count + log_warns count."""

    def test_warnings_equals_blocked_when_no_logs(self):
        board = _make_board([
            _col("running_now", []),
            _col("blocked", [_task("B1", "p1", "blocked"),
                             _task("B2", "p1", "blocked"),
                             _task("B3", "p1", "blocked")]),
        ])
        out = _patched_overview(serve, board)
        self.assertEqual(out["warnings"]["value"], 3)
        self.assertEqual(out["warnings"]["breakdown"]["blocked_tasks"], 3)

    def test_warnings_includes_log_warns(self):
        board = _make_board([
            _col("running_now", []),
            _col("blocked", [_task("B1", "p1", "blocked")]),
        ])
        # Patch _read_events_tail-style scanning: stub the log scan to
        # find 2 warn-level log files. The simplest is to patch
        # data_overview's logs_root walk — but it's local. Instead we
        # patch the glob iterator via a custom logs_root.
        with mock.patch.object(serve, "data_kanban", return_value=board), \
             mock.patch.object(serve, "parse_frontmatter",
                               return_value=({"level": "warn"}, "")), \
             mock.patch("pathlib.Path.rglob",
                        return_value=[Path("/fake/log1.md"),
                                      Path("/fake/log2.md")]), \
             mock.patch.object(serve, "safe_read", return_value="x"):
            out = serve.data_overview()
        self.assertEqual(out["warnings"]["value"], 3)  # 1 blocked + 2 log warns
        self.assertEqual(out["warnings"]["breakdown"]["blocked_tasks"], 1)
        self.assertEqual(out["warnings"]["breakdown"]["log_warns"], 2)


class LastCheckTests(unittest.TestCase):
    """last_check reflects actual poll time, not memory-log."""

    def test_last_check_is_now(self):
        """last_check.value should equal polled_at_iso (which is now)."""
        board = _make_board([_col("running_now", []),
                             _col("blocked", [])])
        out = _patched_overview(serve, board)
        self.assertEqual(out["last_check"]["value"], out["polled_at_iso"])

    def test_last_check_not_from_memory_log(self):
        """Even with a stale memory-log entry, last_check reflects now."""
        # Write a stale memory-log entry to disk
        import tempfile, time as _time
        with tempfile.TemporaryDirectory() as td:
            tmp_root = Path(td)
            (tmp_root / "00_company_os").mkdir()
            # "Stale" memory-log entry dated 2 hours ago
            stale = (tmp_root / "00_company_os" / "memory-log.md")
            stale.write_text(
                "### 999. Stale entry — **When:** 2020-01-01 00:00\n"
            )
            board = _make_board([_col("running_now", []),
                                 _col("blocked", [])])
            # Override COMPANY_ROOT for this test
            with mock.patch.object(serve, "COMPANY_ROOT", tmp_root):
                out = _patched_overview(serve, board)
            # Must NOT be 2020 — must be now
            self.assertFalse(out["last_check"]["value"].startswith("2020"))
            self.assertTrue(out["last_check"]["value"].startswith("20"))


class BlockerReasonHelperTests(unittest.TestCase):
    """Direct unit tests for `_task_has_blocker_reason`."""

    def test_blocker_reason_format_a_present(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tf = Path(td) / "TASK-1.md"
            tf.write_text(
                "---\n"
                "task_id: TASK-1\n"
                "blocker: \"Waiting on NOFI approval for paid LLM key\"\n"
                "---\n"
            )
            card = {"task_id": "TASK-1",
                    "source_file": str(tf.relative_to(td))}
            with mock.patch.object(serve, "COMPANY_ROOT", Path(td)):
                self.assertTrue(serve._task_has_blocker_reason(card))

    def test_blocker_reason_format_a_blockers_alias(self):
        """`blockers` (plural) is also recognised."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tf = Path(td) / "TASK-1.md"
            tf.write_text(
                "---\n"
                "task_id: TASK-1\n"
                "blockers: \"firefox hangs on this host\"\n"
                "---\n"
            )
            card = {"task_id": "TASK-1",
                    "source_file": str(tf.relative_to(td))}
            with mock.patch.object(serve, "COMPANY_ROOT", Path(td)):
                self.assertTrue(serve._task_has_blocker_reason(card))

    def test_blocker_reason_format_b_table(self):
        """Format B markdown table: `| **blocker** | ... |` is recognised."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tf = Path(td) / "TASK-1.md"
            tf.write_text(
                "| Field | Value |\n"
                "|---|---|\n"
                "| **id** | TASK-1 |\n"
                "| **blocker** | Waiting for dispatcher runner |\n"
            )
            card = {"task_id": "TASK-1",
                    "source_file": str(tf.relative_to(td))}
            with mock.patch.object(serve, "COMPANY_ROOT", Path(td)):
                self.assertTrue(serve._task_has_blocker_reason(card))

    def test_no_blocker_reason_returns_false(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tf = Path(td) / "TASK-1.md"
            tf.write_text(
                "---\n"
                "task_id: TASK-1\n"
                "status: failed\n"
                # NO blocker field
                "---\n"
            )
            card = {"task_id": "TASK-1",
                    "source_file": str(tf.relative_to(td))}
            with mock.patch.object(serve, "COMPANY_ROOT", Path(td)):
                self.assertFalse(serve._task_has_blocker_reason(card))

    def test_empty_blocker_returns_false(self):
        """Empty / whitespace / dash / 'none' blocker → not a real blocker."""
        import tempfile
        for empty_val in ("", "   ", "-", "none", "n/a"):
            with tempfile.TemporaryDirectory() as td:
                tf = Path(td) / "TASK-1.md"
                tf.write_text(
                    f"---\n"
                    f"task_id: TASK-1\n"
                    f"blocker: \"{empty_val}\"\n"
                    f"---\n"
                )
                card = {"task_id": "TASK-1",
                        "source_file": str(tf.relative_to(td))}
                with mock.patch.object(serve, "COMPANY_ROOT", Path(td)):
                    self.assertFalse(serve._task_has_blocker_reason(card),
                                     f"empty_val={empty_val!r} should be False")

    def test_missing_source_file_returns_false(self):
        card = {"task_id": "GHOST", "source_file": "nonexistent/path.md"}
        self.assertFalse(serve._task_has_blocker_reason(card))

    def test_empty_source_file_returns_false(self):
        card = {"task_id": "X", "source_file": ""}
        self.assertFalse(serve._task_has_blocker_reason(card))


if __name__ == "__main__":
    unittest.main()
