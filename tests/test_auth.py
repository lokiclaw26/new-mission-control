#!/usr/bin/env python3
"""
test_auth.py — Unit tests for MC_ADMIN_TOKEN enforcement.

We exercise `security.is_authorized` directly with a stub request object,
plus an integration test that hits the running server via urllib when
available. The unit tests are hermetic; the integration tests are
skipped if no server is reachable on the configured port.
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

from security import is_authorized, auth_required_error, reset_admin_token_cache  # noqa: E402


class _StubRequest:
    """Minimal stand-in for a BaseHTTPRequestHandler."""

    def __init__(self, ip="127.0.0.1", headers=None):
        self.client_address = (ip, 0)
        self.headers = headers or {}


class IsAuthorizedUnitTests(unittest.TestCase):
    def setUp(self):
        # security._resolve_admin_token() caches its result across calls.
        # Tests that swap os.environ need to invalidate the cache so the
        # next call actually re-reads from the (mocked) env, not the
        # prior real value.
        reset_admin_token_cache()
        # Patch the resolver so it does NOT fall back to start-mc.sh during
        # tests — the test's mocked os.environ should be the only source of
        # truth, otherwise the real token from start-mc.sh leaks in.
        self._resolver_patcher = mock.patch(
            "security._resolve_admin_token",
            side_effect=lambda: os.environ.get("MC_ADMIN_TOKEN", "").strip(),
        )
        self._resolver_patcher.start()

    def tearDown(self):
        self._resolver_patcher.stop()
        reset_admin_token_cache()

    def test_loopback_allowed_when_token_unset(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MC_ADMIN_TOKEN", None)
            reset_admin_token_cache()
            for ip in ("127.0.0.1", "::1", "localhost"):
                self.assertTrue(is_authorized(_StubRequest(ip=ip)),
                                f"loopback {ip} should be allowed")

    def test_lan_denied_when_token_unset(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MC_ADMIN_TOKEN", None)
            reset_admin_token_cache()
            self.assertFalse(is_authorized(_StubRequest(ip="192.168.0.29")))

    def test_token_required_when_set(self):
        with mock.patch.dict(os.environ, {"MC_ADMIN_TOKEN": "secret-xyz"}):
            reset_admin_token_cache()
            # No header → denied
            self.assertFalse(is_authorized(_StubRequest(ip="127.0.0.1")))
            # Wrong bearer → denied
            self.assertFalse(is_authorized(_StubRequest(
                ip="127.0.0.1",
                headers={"Authorization": "Bearer wrong-token"},
            )))
            # Correct bearer → allowed
            self.assertTrue(is_authorized(_StubRequest(
                ip="127.0.0.1",
                headers={"Authorization": "Bearer secret-xyz"},
            )))
            # X-MC-Admin-Token header → allowed
            self.assertTrue(is_authorized(_StubRequest(
                ip="127.0.0.1",
                headers={"X-MC-Admin-Token": "secret-xyz"},
            )))
            # LAN IP with token → allowed (token overrides loopback rule)
            self.assertTrue(is_authorized(_StubRequest(
                ip="192.168.0.29",
                headers={"Authorization": "Bearer secret-xyz"},
            )))

    def test_token_whitespace_only_treated_as_unset(self):
        with mock.patch.dict(os.environ, {"MC_ADMIN_TOKEN": "   "}):
            reset_admin_token_cache()
            # Token after strip is empty → loopback-only mode.
            self.assertTrue(is_authorized(_StubRequest(ip="127.0.0.1")))
            self.assertFalse(is_authorized(_StubRequest(ip="192.168.0.29")))


class AuthRequiredErrorTests(unittest.TestCase):
    def setUp(self):
        reset_admin_token_cache()
        self._resolver_patcher = mock.patch(
            "security._resolve_admin_token",
            side_effect=lambda: os.environ.get("MC_ADMIN_TOKEN", "").strip(),
        )
        self._resolver_patcher.start()

    def tearDown(self):
        self._resolver_patcher.stop()
        reset_admin_token_cache()

    def test_unset_token_message_mentions_setup(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MC_ADMIN_TOKEN", None)
            reset_admin_token_cache()
            err = auth_required_error()
            self.assertIn("MC_ADMIN_TOKEN", err["error"])
            self.assertTrue(err.get("setup_required"))

    def test_set_token_message_mentions_header(self):
        with mock.patch.dict(os.environ, {"MC_ADMIN_TOKEN": "secret"}):
            reset_admin_token_cache()
            err = auth_required_error()
            self.assertIn("unauthorized", err["error"])
            self.assertIn("Bearer", err["how"])


class ServerIntegrationTests(unittest.TestCase):
    """If a Mission Control server is reachable on port 8767, exercise auth."""

    @classmethod
    def setUpClass(cls):
        cls.port = int(os.environ.get("MC_TEST_PORT", "8767"))
        cls.host = os.environ.get("MC_TEST_HOST", "127.0.0.1")
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

    def test_unauthorized_write_returns_403(self):
        if not self.reachable:
            self.skipTest("server not reachable")
        # Save and clear MC_ADMIN_TOKEN at request time; the test process
        # env doesn't affect the already-running server. We just verify
        # that without a token, the LAN-write rejection path works.
        # Send with a known-bad token to force the 403 path.
        status, body = self._post(
            "/api/memory-graph/events",
            {"type": "node.upsert",
             "node": {"id": "auth-test-1", "kind": "concept",
                      "label": "x"}},
            headers={"Authorization": "Bearer obviously-wrong-token"},
        )
        self.assertEqual(status, 403, body)


if __name__ == "__main__":
    unittest.main()
