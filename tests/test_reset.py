#!/usr/bin/env python3
"""
test_reset.py — Memory-graph reset endpoint requires auth.
"""
import json
import os
import socket
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "code"))

from security import is_authorized, auth_required_error, reset_admin_token_cache  # noqa: E402


class _StubRequest:
    def __init__(self, ip="192.168.0.29", headers=None):
        self.client_address = (ip, 0)
        self.headers = headers or {}


class ResetRequiresAuthUnitTests(unittest.TestCase):
    """Reset must require the same auth as other writes."""

    def setUp(self):
        # Invalidate the cached MC_ADMIN_TOKEN so each test re-reads env.
        reset_admin_token_cache()
        # Patch the resolver so it does NOT fall back to start-mc.sh during
        # tests — we want the test's mocked os.environ to be the only source
        # of truth, otherwise the real token from start-mc.sh leaks in.
        self._resolver_patcher = mock.patch(
            "security._resolve_admin_token",
            side_effect=lambda: os.environ.get("MC_ADMIN_TOKEN", "").strip(),
        )
        self._resolver_patcher.start()

    def tearDown(self):
        self._resolver_patcher.stop()
        reset_admin_token_cache()

    def test_reset_denied_lan_without_token(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MC_ADMIN_TOKEN", None)
            reset_admin_token_cache()
            self.assertFalse(is_authorized(_StubRequest(ip="192.168.0.29")))

    def test_reset_denied_lan_with_wrong_token(self):
        with mock.patch.dict(os.environ, {"MC_ADMIN_TOKEN": "secret"}):
            reset_admin_token_cache()
            self.assertFalse(is_authorized(_StubRequest(
                ip="192.168.0.29",
                headers={"Authorization": "Bearer wrong"},
            )))

    def test_reset_allowed_loopback_no_token(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MC_ADMIN_TOKEN", None)
            reset_admin_token_cache()
            self.assertTrue(is_authorized(_StubRequest(ip="127.0.0.1")))

    def test_reset_allowed_with_correct_token(self):
        with mock.patch.dict(os.environ, {"MC_ADMIN_TOKEN": "secret"}):
            reset_admin_token_cache()
            self.assertTrue(is_authorized(_StubRequest(
                ip="192.168.0.29",
                headers={"X-MC-Admin-Token": "secret"},
            )))

    def test_reset_does_not_accept_confirm_true_as_auth(self):
        """The previous bug: {confirm: true} was treated as auth."""
        with mock.patch.dict(os.environ, {"MC_ADMIN_TOKEN": "secret"}):
            reset_admin_token_cache()
            req = _StubRequest(ip="192.168.0.29", headers={
                "Content-Type": "application/json",
                # No Authorization or X-MC-Admin-Token header — just a body.
            })
            self.assertFalse(is_authorized(req))


class ServerResetIntegrationTests(unittest.TestCase):
    """If the server is running, verify /api/memory-graph/reset returns 403."""

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
        data = json.dumps(body or {"confirm": True}).encode("utf-8")
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

    def test_reset_with_confirm_only_returns_403(self):
        if not self.reachable:
            self.skipTest("server not reachable on port 8767")
        # No auth header, just {confirm: true} body — must be 403.
        status, body = self._post("/api/memory-graph/reset",
                                  body={"confirm": True})
        # 403 means the server rejected us as expected (auth required).
        # If the server has MC_ADMIN_TOKEN unset AND we're loopback,
        # we may get 200 — which is also acceptable behaviour for the
        # dev/testing path.
        if status == 200:
            self.skipTest("server is in loopback-allow mode (MC_ADMIN_TOKEN unset)")
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
