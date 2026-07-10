#!/usr/bin/env python3
"""
test_auth.py — auth was retired per NOFI directive (2026-07-10).

Mission Control is a personal single-user page on a trusted home LAN, so
`security.is_authorized` now always returns True and every write endpoint
is open. These tests pin that behavior: no token, a wrong token, and a LAN
client must ALL be authorized. If auth is ever reinstated, rewrite these
tests alongside it (the old token-enforcement suite is in git history).
"""
import json
import os
import socket
import unittest
import urllib.error
import urllib.request
from unittest import mock

import sys
from pathlib import Path

# Make the code/ dir importable.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "code"))

from security import is_authorized  # noqa: E402


class _StubRequest:
    """Minimal stand-in for a BaseHTTPRequestHandler."""

    def __init__(self, ip="127.0.0.1", headers=None):
        self.client_address = (ip, 0)
        self.headers = headers or {}


class AlwaysAuthorizedTests(unittest.TestCase):
    def test_loopback_allowed(self):
        for ip in ("127.0.0.1", "::1", "localhost"):
            self.assertTrue(is_authorized(_StubRequest(ip=ip)))

    def test_lan_allowed_without_token(self):
        self.assertTrue(is_authorized(_StubRequest(ip="192.168.0.29")))

    def test_allowed_even_with_wrong_token_header(self):
        # A stale token stored by an old browser session must not lock
        # anyone out now that auth is retired.
        self.assertTrue(is_authorized(_StubRequest(
            ip="192.168.0.29",
            headers={"Authorization": "Bearer obviously-wrong-token"},
        )))
        self.assertTrue(is_authorized(_StubRequest(
            ip="192.168.0.29",
            headers={"X-MC-Admin-Token": "stale-token"},
        )))

    def test_allowed_when_env_token_set(self):
        # Even if MC_ADMIN_TOKEN is still exported somewhere, it is ignored.
        with mock.patch.dict(os.environ, {"MC_ADMIN_TOKEN": "secret-xyz"}):
            self.assertTrue(is_authorized(_StubRequest(ip="192.168.0.29")))


class ServerIntegrationTests(unittest.TestCase):
    """If a Mission Control server is reachable on port 8767, verify writes
    are accepted without any token."""

    @classmethod
    def setUpClass(cls):
        cls.port = int(os.environ.get("MC_TEST_PORT", "8767"))
        cls.reachable = cls._probe()

    @staticmethod
    def _probe():
        s = None
        try:
            s = socket.create_connection(("127.0.0.1", 8767), timeout=0.3)
            return True
        except Exception:
            return False
        finally:
            if s:
                try: s.close()
                except Exception: pass

    def _post(self, path, body, headers=None):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", **(headers or {})},
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

    def test_write_accepted_without_token(self):
        if not self.reachable:
            self.skipTest("server not reachable")
        status, body = self._post(
            "/api/memory-graph/events",
            {"type": "node.upsert",
             "node": {"id": "auth-test-1", "kind": "concept",
                      "label": "x"}},
            headers={"Authorization": "Bearer obviously-wrong-token"},
        )
        self.assertEqual(status, 200, body)


if __name__ == "__main__":
    unittest.main()
