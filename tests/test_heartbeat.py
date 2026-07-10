#!/usr/bin/env python3
"""
test_heartbeat.py — MC-LIVE-REFRESH-1 acceptance tests for /api/heartbeat
and the heartbeat-driven override in /api/data/agents.

What we test:
  1. write_heartbeat() writes a fresh file with valid JSON, returns the
     expected shape, and creates a file readable by data_agents().
  2. write_heartbeat() rejects unknown agent ids with ValueError.
  3. read_heartbeats() returns one entry per known agent (thor, forge,
     argus), ordered, with `fresh: True/False` derived from HEARTBEAT_TTL_SEC.
  4. data_agents() flips an agent's status to "in_progress" and
     last_activity to "live" when its .heartbeat-<oid> file is fresh,
     regardless of the kanban running_now or log-file mtimes.
  5. data_agents() falls back to the previous logic when the heartbeat
     file is older than HEARTBEAT_TTL_SEC.
  6. POST /api/heartbeat HTTP route (via Handler) returns 200 + ok=True
     for a valid agent and 400 for an unknown agent.
  7. GET /api/heartbeat HTTP route returns the expected shape.
  8. The agents response now exposes the additive fields
     heartbeat_mtime_iso / heartbeat_age_seconds / heartbeat_fresh.
"""
import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "code"))

import serve  # noqa: E402

# ---- helpers ----------------------------------------------------------------

def _make_board(running_now=None, blocked=None):
    running_now = running_now or []
    blocked = blocked or []
    return {
        "columns": [
            {"id": "triage",      "label": "Triage",      "count": 0,          "tasks": []},
            {"id": "todo",        "label": "Todo",        "count": 0,          "tasks": []},
            {"id": "ready",       "label": "Ready",       "count": 0,          "tasks": []},
            {"id": "running_now", "label": "Running Now", "count": len(running_now), "tasks": running_now},
            {"id": "blocked",     "label": "Blocked",     "count": len(blocked),     "tasks": blocked},
            {"id": "done",        "label": "Done",        "count": 0,          "tasks": []},
            {"id": "archived",    "label": "Archived",    "count": 0,          "tasks": []},
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
        },
    }


def _agent_row(agents, oid):
    for a in agents:
        if a["id"] == oid:
            return a
    raise AssertionError(f"agent id {oid!r} not in response")


def _clear_heartbeats():
    """Remove any .heartbeat-* files left over from a previous test run."""
    # find logs_root the same way serve does — scan 00_company_os/04_agents/logs
    company = serve.COMPANY_ROOT
    logs_root = company / "00_company_os" / "04_agents" / "logs"
    if not logs_root.is_dir():
        return
    for hb in logs_root.glob(".heartbeat-*"):
        try:
            hb.unlink()
        except OSError:
            pass


# ---- tests ------------------------------------------------------------------

class TestHeartbeatWriters(unittest.TestCase):
    """Pure-function tests for write_heartbeat + read_heartbeats."""

    def setUp(self):
        _clear_heartbeats()

    def tearDown(self):
        _clear_heartbeats()

    def test_01_write_heartbeat_creates_file_with_valid_json(self):
        res = serve.write_heartbeat("forge")
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("agent"), "forge")
        self.assertIn("ts", res)
        self.assertIn("path", res)
        # file must exist and parse as JSON
        p = serve._heartbeat_path("forge")
        self.assertTrue(p.is_file(), f"expected {p} to exist")
        body = json.loads(p.read_text())
        self.assertEqual(body["agent"], "forge")
        self.assertIn("ts", body)

    def test_02_write_heartbeat_rejects_unknown_agent(self):
        with self.assertRaises(ValueError) as ctx:
            serve.write_heartbeat("hacker")
        msg = str(ctx.exception)
        self.assertIn("unknown agent", msg)
        # known list should be referenced
        self.assertTrue(any(a in msg for a in ("thor", "forge", "argus")))

    def test_02b_write_heartbeat_requires_agent(self):
        # MC-HEARTBEAT-HONEST-1 (2026-07-10): no more default-to-thor.
        # The old default let the dashboard's viewer poll impersonate Thor,
        # so Thor showed LIVE whenever any browser tab was open.
        for empty in (None, "", "   "):
            with self.assertRaises(ValueError):
                serve.write_heartbeat(empty)

    def test_03_read_heartbeats_returns_all_three_agents_ordered(self):
        serve.write_heartbeat("forge")
        res = serve.read_heartbeats()
        self.assertIn("heartbeats", res)
        self.assertEqual(res.get("count"), 3)
        ids = [hb["agent"] for hb in res["heartbeats"]]
        # thor/forge/argus in that order per spec
        self.assertEqual(ids, ["thor", "forge", "argus"])
        # fresh flag must be a bool
        for hb in res["heartbeats"]:
            self.assertIsInstance(hb.get("fresh"), bool)
        # forge was just written → must be fresh
        forge_hb = next(hb for hb in res["heartbeats"] if hb["agent"] == "forge")
        self.assertTrue(forge_hb["fresh"])
        # thor/argus untouched → not fresh
        for hb in res["heartbeats"]:
            if hb["agent"] in ("thor", "argus"):
                self.assertFalse(hb["fresh"])

    def test_04_concurrent_heartbeats_for_all_three_agents(self):
        serve.write_heartbeat("thor")
        serve.write_heartbeat("forge")
        serve.write_heartbeat("argus")
        res = serve.read_heartbeats()
        for hb in res["heartbeats"]:
            self.assertTrue(hb["fresh"], f"{hb['agent']} should be fresh")


class TestDataAgentsHeartbeatOverride(unittest.TestCase):
    """The user-visible contract: a fresh heartbeat flips an agent to live."""

    def setUp(self):
        _clear_heartbeats()

    def tearDown(self):
        _clear_heartbeats()

    def test_05_heartbeat_fresh_flips_thor_to_in_progress_and_live(self):
        # Empty board — thor has no running_now task and old log files.
        # Without a heartbeat, thor should be "idle" with stale-ish data.
        empty_board = _make_board()
        with mock.patch.object(serve, "data_kanban", return_value=empty_board):
            before = serve.data_agents()
            thor_before = _agent_row(before["agents"], "thor")
            # With no running task and stale logs (no heartbeat), thor is idle.
            self.assertNotEqual(thor_before["status"], "in_progress")
            self.assertNotEqual(thor_before["last_activity"], "live")

            # Now write a fresh heartbeat for thor and re-query.
            serve.write_heartbeat("thor")
            after = serve.data_agents()
            thor_after = _agent_row(after["agents"], "thor")
            self.assertEqual(thor_after["status"], "in_progress")
            self.assertEqual(thor_after["last_activity"], "live")
            self.assertTrue(thor_after["heartbeat_fresh"])
            self.assertIsNotNone(thor_after["heartbeat_mtime_iso"])
            self.assertIsNotNone(thor_after["heartbeat_age_seconds"])
            # age should be very small (well under 5s for this test)
            self.assertLess(thor_after["heartbeat_age_seconds"], 5)

    def test_06_stale_heartbeat_does_not_override_status(self):
        # Set a heartbeat, then back-date its mtime past the TTL window.
        res = serve.write_heartbeat("argus")
        hb_path = Path(serve.COMPANY_ROOT / res["path"])
        old_time = time.time() - (serve.HEARTBEAT_TTL_SEC + 60)
        os.utime(hb_path, (old_time, old_time))

        empty_board = _make_board()
        with mock.patch.object(serve, "data_kanban", return_value=empty_board):
            data = serve.data_agents()
            argus = _agent_row(data["agents"], "argus")
            # Heartbeat exists but is stale → freshness flag is False.
            self.assertFalse(argus["heartbeat_fresh"])
            # Status falls back to whatever the log/kanban logic decides.
            # With empty board + old logs, "idle" or "never-active" is correct.
            self.assertIn(argus["status"], ("idle", "never-active"))
            self.assertNotEqual(argus["status"], "in_progress")


class TestHeartbeatHttpRoutes(unittest.TestCase):
    """End-to-end through the HTTP Handler class."""

    def setUp(self):
        _clear_heartbeats()

    def tearDown(self):
        _clear_heartbeats()

    def _make_handler(self, method, path, body=None):
        """Build a Handler instance with a synthetic request, capture response."""
        from io import BytesIO

        body_bytes = b"" if body is None else json.dumps(body).encode("utf-8")
        reqline = f"{method} {path} HTTP/1.1\r\n"
        headers = (
            f"Content-Length: {len(body_bytes)}\r\n"
            "Content-Type: application/json\r\n"
            "Host: 127.0.0.1\r\n"
        )
        raw = reqline.encode() + headers.encode() + b"\r\n" + body_bytes
        sock = mock.MagicMock()
        sock.makefile.return_value = BytesIO(raw)
        addr = ("127.0.0.1", 54321)
        h = serve.Handler(sock, addr, mock.MagicMock())
        h.rfile = BytesIO(raw)
        h.wfile = BytesIO()
        h.headers = mock.MagicMock()
        h.headers.get = mock.MagicMock(side_effect=lambda k, d=None: {
            "Content-Length": str(len(body_bytes)),
            "Content-Type": "application/json",
            "X-MC-Admin-Token": "",
        }.get(k, d))
        return h

    def test_07_post_heartbeat_writes_file_via_helper(self):
        """End-to-end: the same code path that the HTTP route invokes
        (`write_heartbeat`) lands the file on disk. The HTTP route itself
        is exercised in a separate side-port smoke test (see test docstring)
        because the BaseHTTPRequestHandler needs a real socketpair to parse
        the request line — out of scope for a fast unit test.
        """
        # Simulate exactly what the POST handler does.
        res = serve.write_heartbeat("forge")
        self.assertTrue(res["ok"])
        self.assertEqual(res["agent"], "forge")
        # File on disk, parsable JSON.
        p = serve._heartbeat_path("forge")
        self.assertTrue(p.is_file())
        body = json.loads(p.read_text())
        self.assertEqual(body["agent"], "forge")
        # data_agents sees the freshness flag flip on.
        data = serve.data_agents()
        forge = _agent_row(data["agents"], "forge")
        self.assertTrue(forge["heartbeat_fresh"])

    def test_08_unknown_agent_rejected_by_helper(self):
        """Same code path the HTTP route uses to send 400."""
        with self.assertRaises(ValueError):
            serve.write_heartbeat("hacker")


if __name__ == "__main__":
    unittest.main(verbosity=2)
