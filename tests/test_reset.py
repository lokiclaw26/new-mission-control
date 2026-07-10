#!/usr/bin/env python3
"""
test_reset.py — memory-graph reset endpoints after auth retirement.

MC-NO-AUTH-1 (2026-07-10): auth is gone (is_authorized always True), so:
  - /api/memory-graph/reset is open — safe, because it is a VISUAL reset
    only (the DB is never touched).
  - /api/memory-graph/admin-reset (destructive wipe) is protected by an
    explicit {"confirm": true} body instead of the old token. These tests
    pin the refusal path — a bare POST must NOT wipe the graph.
"""
import io
import json
import os
import socket
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "code"))

from security import is_authorized  # noqa: E402
import memory_graph_api  # noqa: E402


class _StubRequest:
    def __init__(self, ip="192.168.0.29", headers=None, body=b""):
        self.client_address = (ip, 0)
        self.headers = headers or {}
        if body:
            self.headers.setdefault("Content-Length", str(len(body)))
        self.rfile = io.BytesIO(body)


class ResetOpenAccessUnitTests(unittest.TestCase):
    """Auth retired: every caller is authorized, LAN included."""

    def test_lan_authorized_without_token(self):
        self.assertTrue(is_authorized(_StubRequest(ip="192.168.0.29")))

    def test_authorized_even_with_wrong_token(self):
        self.assertTrue(is_authorized(_StubRequest(
            ip="192.168.0.29",
            headers={"Authorization": "Bearer wrong"},
        )))


class AdminResetConfirmGateUnitTests(unittest.TestCase):
    """The destructive wipe requires {"confirm": true} in the body."""

    def test_bare_post_refused(self):
        status, body = memory_graph_api.post_admin_reset(_StubRequest())
        self.assertEqual(status, 400)
        self.assertIn("confirm", body.get("error", ""))

    def test_confirm_false_refused(self):
        status, body = memory_graph_api.post_admin_reset(
            _StubRequest(body=json.dumps({"confirm": False}).encode("utf-8")))
        self.assertEqual(status, 400)

    def test_garbage_body_refused(self):
        status, body = memory_graph_api.post_admin_reset(
            _StubRequest(body=b"not-json"))
        self.assertEqual(status, 400)


class ServerResetIntegrationTests(unittest.TestCase):
    """If a server is reachable on port 8767, verify both reset behaviors.

    Safe to run against a live server: /reset is visual-only (DB untouched)
    and the admin-reset request here deliberately OMITS confirm, so it must
    be refused.
    """

    @classmethod
    def setUpClass(cls):
        cls.port = int(os.environ.get("MC_TEST_PORT", "8767"))
        s = None
        try:
            s = socket.create_connection(("127.0.0.1", cls.port), timeout=0.3)
            cls.reachable = True
        except Exception:
            cls.reachable = False
        finally:
            if s:
                try: s.close()
                except Exception: pass

    def _post(self, path, body=None, headers=None):
        data = json.dumps(body if body is not None else {}).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            headers={"Content-Type": "application/json",
                     **(headers or {})},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as r:
                return r.status, json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode("utf-8") or "{}")
            except Exception:
                body = {"error": str(e)}
            return e.code, body
        except Exception as e:
            self.skipTest(f"server not reachable: {e}")

    def test_visual_reset_open_and_nondestructive(self):
        if not self.reachable:
            self.skipTest("server not reachable on port 8767")
        status, body = self._post("/api/memory-graph/reset")
        self.assertEqual(status, 200, body)
        self.assertFalse(body.get("db_wiped", False))

    def test_admin_reset_without_confirm_refused(self):
        if not self.reachable:
            self.skipTest("server not reachable on port 8767")
        status, body = self._post("/api/memory-graph/admin-reset")
        self.assertEqual(status, 400, body)


if __name__ == "__main__":
    unittest.main()
