#!/usr/bin/env python3
"""
test_agents_live.py — MC-LIVE-DASHBOARD-1 acceptance tests for /api/data/agents.

These tests verify that `data_agents()` derives each agent's
`current_assignment`, `status`, and `last_activity` from the LIVE kanban
board (via `data_kanban()`), NOT from the stale state.json file.

We seed fake kanban state by monkey-patching `serve.data_kanban`, then
call `serve.data_agents()` and assert the derivation rules from the spec:

  current_assignment = the running_now task for this agent (kanban),
                       fallback to state.json only when no running task
  status             = "in_progress"  if has running_now task
                       "idle"         if has log mtime (any age)
                       "never-active" if no logs at all
  last_activity      = "live"          if status == in_progress
                       rel_time(mtime) if idle
                       "—"              if never-active
  polled_at_iso      = current UTC ISO (new field)
"""
import sys
import time as _time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "code"))

import serve  # noqa: E402


# ---- helpers ---------------------------------------------------------------

def _make_board(running_now=None, blocked=None):
    """Build a fake kanban board dict matching `data_kanban()`'s shape."""
    running_now = running_now or []
    blocked = blocked or []
    return {
        "columns": [
            {"id": "triage",     "label": "Triage",     "count": 0,          "tasks": []},
            {"id": "todo",       "label": "Todo",       "count": 0,          "tasks": []},
            {"id": "ready",      "label": "Ready",      "count": 0,          "tasks": []},
            {"id": "running_now","label": "Running Now","count": len(running_now), "tasks": running_now},
            {"id": "blocked",    "label": "Blocked",    "count": len(blocked),     "tasks": blocked},
            {"id": "done",       "label": "Done",       "count": 0,          "tasks": []},
            {"id": "archived",   "label": "Archived",   "count": 0,          "tasks": []},
        ],
        "agents": [],
        "summary": {
            "total": len(running_now) + len(blocked),
            "visible": len(running_now) + len(blocked),
            "by_status": {
                "triage": 0, "todo": 0, "ready": 0,
                "running_now": len(running_now),
                "blocked": len(blocked),
                "done": 0, "archived": 0,
            },
            "by_assignee": {},
            "by_format": {"A": 0, "B": 0},
            "skipped": 0,
        },
        "warnings": [],
        "include_archived": False,
    }


def _task(task_id, project, kanban_status, assigned_to, source_file=None):
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


class _FakeLogFile:
    """Minimal stand-in for a Path under 04_agents/logs/.

    Implements only what data_agents() actually uses:
      - .name (for the seen-set dedupe)
      - .stat().st_mtime (for the last-mtime calculation)
      - .relative_to(root) (returns a Path-like string)
    """

    def __init__(self, agent_id, mtime, name):
        self._agent_id = agent_id
        self._mtime = mtime
        self.name = name

    def stat(self):
        s = type("_S", (), {})()
        s.st_mtime = self._mtime
        return s

    def relative_to(self, root):
        # data_agents() only uses .relative_to(...).name-like access; we
        # return a plain Path that will render as a string.
        from pathlib import Path as _P
        return _P(f"00_company_os/04_agents/logs/{self.name}")


def _call_agents(board, state_agents=None, log_files=None, no_logs_for=None):
    """Call data_agents() with data_kanban + state + log file mtimes stubbed.

    state_agents: dict of agent_id → state.json entry (status/current_assignment).
    log_files:    list of (agent_id, mtime_epoch) tuples for fake log files.
    no_logs_for:  set of agent_ids that should appear to have NO log files.
    """
    state_agents = state_agents or {}
    log_files = log_files or []
    no_logs_for = set(no_logs_for or [])

    state = {"agents": state_agents, "updated": "2026-06-17T00:00:00Z"}

    # Build fake file list per agent (only those NOT in no_logs_for)
    fake_files = [
        _FakeLogFile(aid, mt, f"{aid}-test.md")
        for aid, mt in log_files
        if aid not in no_logs_for
    ]

    def patched_rglob(self, pattern):
        if "04_agents/logs" not in str(self):
            return []
        results = []
        for fp in fake_files:
            name = fp.name
            # Patterns used by data_agents():
            #   f"{oid}-*.md", f"*-{oid}-*.md", f"*{oid}*.md"
            # Convert to a simple contains check.
            if pattern == f"{fp._agent_id}-*.md" and name.startswith(f"{fp._agent_id}-"):
                results.append(fp)
            elif pattern == f"*-{fp._agent_id}-*.md" and f"-{fp._agent_id}-" in name:
                results.append(fp)
            elif pattern == f"*{fp._agent_id}*.md" and fp._agent_id in name:
                results.append(fp)
        # Dedupe by identity (data_agents() uses a seen set)
        seen = set()
        out = []
        for fp in results:
            if id(fp) not in seen:
                seen.add(id(fp))
                out.append(fp)
        return out

    # We also need is_dir() to return True for the logs root check
    orig_is_dir = Path.is_dir
    def patched_is_dir(self):
        if "04_agents/logs" in str(self):
            return True
        return orig_is_dir(self)

    with mock.patch.object(serve, "data_kanban", return_value=board), \
         mock.patch.object(serve, "_read_agent_state", return_value=state), \
         mock.patch.object(Path, "rglob", patched_rglob), \
         mock.patch.object(Path, "is_dir", patched_is_dir):
        return serve.data_agents()


# ---- tests -----------------------------------------------------------------

class PolledAtFieldTests(unittest.TestCase):
    """The agents response must include polled_at_iso."""

    def test_polled_at_iso_present(self):
        board = _make_board()
        out = _call_agents(board, no_logs_for={"thor", "forge", "argus"})
        self.assertIn("polled_at_iso", out)
        # Must be a parseable UTC ISO timestamp
        from datetime import datetime
        ts = out["polled_at_iso"]
        self.assertTrue(ts.endswith("+00:00") or ts.endswith("Z"),
                        f"polled_at_iso not UTC: {ts!r}")
        datetime.fromisoformat(ts.replace("Z", "+00:00"))

    def test_count_present(self):
        board = _make_board()
        out = _call_agents(board, no_logs_for={"thor", "forge", "argus"})
        self.assertEqual(out["count"], 3)
        self.assertEqual(len(out["agents"]), 3)


class CurrentAssignmentTests(unittest.TestCase):
    """current_assignment must come from live kanban, not stale state.json."""

    def test_running_now_task_is_current_assignment(self):
        """A kanban running_now task overrides the stale state.json value."""
        board = _make_board(running_now=[
            _task("MC-LIVE-1", "mission-control", "running_now", "forge"),
        ])
        out = _call_agents(
            board,
            state_agents={"forge": {"current_assignment": "STALE-OLD",
                                    "status": "active"}},
            no_logs_for={"thor", "forge", "argus"},
        )
        forge = next(a for a in out["agents"] if a["id"] == "forge")
        self.assertEqual(forge["current_assignment"], "MC-LIVE-1")

    def test_no_running_now_assignment_is_none_not_stale(self):
        """MC-LIVE-DASHBOARD-1 (2026-06-18): per spec, if no running_now task
        exists for this agent, current_assignment is None — NOT a fallback
        to the stale state.json value. Showing a stale "current" task is
        the bug NOFI reported."""
        board = _make_board(running_now=[
            _task("MC-LIVE-1", "mission-control", "running_now", "forge"),
        ])
        out = _call_agents(
            board,
            state_agents={"thor": {"current_assignment": "MC-STALE-1",
                                   "status": "active"}},
            no_logs_for={"forge", "argus"},
        )
        thor = next(a for a in out["agents"] if a["id"] == "thor")
        self.assertIsNone(thor["current_assignment"])

    def test_no_running_no_state_assignment_is_none(self):
        board = _make_board()
        out = _call_agents(board, no_logs_for={"thor", "forge", "argus"})
        for a in out["agents"]:
            self.assertIsNone(a["current_assignment"])


class StatusTests(unittest.TestCase):
    """status must be derived from kanban + log mtime."""

    def test_status_in_progress_when_running_now(self):
        board = _make_board(running_now=[
            _task("MC-LIVE-1", "mission-control", "running_now", "forge"),
        ])
        out = _call_agents(board, no_logs_for={"thor", "forge", "argus"})
        forge = next(a for a in out["agents"] if a["id"] == "forge")
        self.assertEqual(forge["status"], "in_progress")

    def test_status_idle_when_log_present_no_running(self):
        board = _make_board()  # no running_now
        now = _time.time()
        out = _call_agents(
            board,
            log_files=[("forge", now - 3600)],  # 1h ago
            no_logs_for={"thor", "argus"},
        )
        forge = next(a for a in out["agents"] if a["id"] == "forge")
        self.assertEqual(forge["status"], "idle")

    def test_status_never_active_when_no_logs_no_running(self):
        board = _make_board()
        out = _call_agents(board, no_logs_for={"thor", "forge", "argus"})
        for a in out["agents"]:
            self.assertEqual(a["status"], "never-active")

    def test_status_in_progress_overrides_stale_state(self):
        """Live running_now wins over a stale state.json status claim."""
        board = _make_board(running_now=[
            _task("MC-LIVE-1", "mission-control", "running_now", "forge"),
        ])
        out = _call_agents(
            board,
            state_agents={"forge": {"status": "active",
                                    "current_assignment": "STALE-OLD"}},
            no_logs_for={"thor", "forge", "argus"},
        )
        forge = next(a for a in out["agents"] if a["id"] == "forge")
        self.assertEqual(forge["status"], "in_progress")


class LastActivityTests(unittest.TestCase):
    """last_activity must be 'live' for active agents, else rel_time."""

    def test_last_activity_live_when_in_progress(self):
        board = _make_board(running_now=[
            _task("MC-LIVE-1", "mission-control", "running_now", "forge"),
        ])
        out = _call_agents(board, no_logs_for={"thor", "forge", "argus"})
        forge = next(a for a in out["agents"] if a["id"] == "forge")
        self.assertEqual(forge["last_activity"], "live")

    def test_last_activity_rel_time_when_idle(self):
        board = _make_board()
        now = _time.time()
        out = _call_agents(
            board,
            log_files=[("forge", now - 7200)],  # 2h ago
            no_logs_for={"thor", "argus"},
        )
        forge = next(a for a in out["agents"] if a["id"] == "forge")
        self.assertIn("ago", forge["last_activity"])
        self.assertNotEqual(forge["last_activity"], "live")

    def test_last_activity_dash_when_never_active(self):
        board = _make_board()
        out = _call_agents(board, no_logs_for={"thor", "forge", "argus"})
        for a in out["agents"]:
            self.assertEqual(a["last_activity"], "—")


class MultipleAgentsTests(unittest.TestCase):
    """Each agent gets their own running_now task independently."""

    def test_each_agent_assigned_their_own_task(self):
        board = _make_board(running_now=[
            _task("TASK-FORGE", "mission-control", "running_now", "forge"),
            _task("TASK-THOR",  "mission-control", "running_now", "thor"),
        ])
        out = _call_agents(board, no_logs_for={"argus"})
        forge = next(a for a in out["agents"] if a["id"] == "forge")
        thor = next(a for a in out["agents"] if a["id"] == "thor")
        argus = next(a for a in out["agents"] if a["id"] == "argus")
        self.assertEqual(forge["current_assignment"], "TASK-FORGE")
        self.assertEqual(forge["status"], "in_progress")
        self.assertEqual(thor["current_assignment"], "TASK-THOR")
        self.assertEqual(thor["status"], "in_progress")
        # argus has no running task
        self.assertIsNone(argus["current_assignment"])
        self.assertEqual(argus["status"], "never-active")


class StaleFieldTests(unittest.TestCase):
    """The `stale` field is preserved."""

    def test_stale_field_present_and_bool(self):
        board = _make_board()
        out = _call_agents(board, no_logs_for={"thor", "forge", "argus"})
        for a in out["agents"]:
            self.assertIn("stale", a)
            self.assertIsInstance(a["stale"], bool)


class AgentShapeTests(unittest.TestCase):
    """The agent row shape is preserved (no breaking changes)."""

    def test_required_fields_present(self):
        board = _make_board()
        out = _call_agents(board, no_logs_for={"thor", "forge", "argus"})
        for a in out["agents"]:
            for field in ("id", "name", "role", "emoji", "status",
                          "last_activity", "stale", "current_assignment",
                          "blocker", "reasons"):
                self.assertIn(field, a, f"agent {a.get('id')} missing {field}")

    def test_three_agents_returned(self):
        board = _make_board()
        out = _call_agents(board, no_logs_for={"thor", "forge", "argus"})
        ids = [a["id"] for a in out["agents"]]
        self.assertEqual(set(ids), {"thor", "forge", "argus"})


if __name__ == "__main__":
    unittest.main()
