#!/usr/bin/env python3
"""
security.py — authentication + secret redaction for Mission Control.

MC-MEMORY-GRAPH-3A-BACKEND (2026-06-17):
  - is_authorized(request): token-or-loopback gate for write endpoints.
  - redact_secrets(value): field-aware redactor (preserves task IDs).
  - _resolve_admin_token(): reads from env first, falls back to start-mc.sh
    so the server can be started from any shell (not just one that has
    MC_ADMIN_TOKEN pre-exported).

Behaviour:
  - SECRET_KEYS → value becomes '[REDACTED]'.
  - GRAPH_KEYS  → recurse into value; do NOT redact unless whole value
                   already matches a secret pattern.
  - FREETEXT_KEYS → apply regex patterns + truncation.
  - Other keys   → recurse, then apply freetext pattern if string.

All identifiers (id, source, target, kind, label, tags, status, project,
path, task_id, created, updated, weight, importance, confidence, actor,
assignee, assigned_to, kanban_status) are NEVER touched by the regex
patterns unless their value happens to look like a secret on its own.
"""

import hmac
import json
import os
import re
import socket
from pathlib import Path
from typing import Any

_LOOPBACK_IPS = {"127.0.0.1", "::1", "localhost"}

# Where start-mc.sh lives — used as a fallback source for MC_ADMIN_TOKEN
# so the server doesn't have to be started from a shell that already
# exported the variable. If start-mc.sh sets it, we honor that.
_START_MC_PATH = Path("/home/nofidofi/NofiTech-Ind/start-mc.sh")

_admin_token_cache: str | None = None


def _resolve_admin_token() -> str:
    """Return the effective MC_ADMIN_TOKEN, or '' if not configured.

    Lookup order:
      1. ``os.environ['MC_ADMIN_TOKEN']`` (set by start-mc.sh via ``export``)
      2. Parsed value of ``MC_ADMIN_TOKEN="..."`` line in start-mc.sh
         (so that ``python3 serve.py`` started from any shell still works)
    """
    global _admin_token_cache
    if _admin_token_cache is not None:
        return _admin_token_cache
    tok = os.environ.get("MC_ADMIN_TOKEN", "").strip()
    if tok:
        _admin_token_cache = tok
        return tok
    # Fallback: parse start-mc.sh
    try:
        if _START_MC_PATH.is_file():
            for line in _START_MC_PATH.read_text(encoding="utf-8").splitlines():
                m = re.match(r'\s*export\s+MC_ADMIN_TOKEN\s*=\s*"([^"]+)"', line)
                if m:
                    tok = m.group(1).strip()
                    if tok:
                        _admin_token_cache = tok
                        return tok
    except Exception:
        pass
    _admin_token_cache = ""
    return ""


def reset_admin_token_cache() -> None:
    """Clear the cached token so the next request re-reads from env/file.

    Useful for tests and for when the operator edits start-mc.sh and wants
    the change to take effect without restarting the server.
    """
    global _admin_token_cache
    _admin_token_cache = None


def is_authorized(request) -> bool:
    """Return True iff the request is authorized to perform writes.

    Rules (per MC-MEMORY-GRAPH-3A-BACKEND spec):
      - If MC_ADMIN_TOKEN is configured (env or start-mc.sh): require a
        matching Authorization: Bearer *** OR X-MC-Admin-Token: <token>
        header.
      - If MC_ADMIN_TOKEN is unset: allow only loopback clients.
      - {confirm: true} body does NOT count as auth.
    """
    token = _resolve_admin_token()
    if not token:
        # No token configured. Allow loopback only.
        try:
            client_addr = request.client_address[0]
        except Exception:
            client_addr = ""
        if client_addr in _LOOPBACK_IPS:
            return True
        return False

    # Token configured. Require it in either header.
    auth_header = (request.headers.get("Authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        provided = auth_header[7:].strip()
    else:
        provided = (request.headers.get("X-MC-Admin-Token") or "").strip()
    # Constant-time comparison — a plain == leaks the match length through
    # response timing, which is enough to brute-force a token on a LAN.
    return hmac.compare_digest(provided.encode("utf-8"), token.encode("utf-8"))


def auth_required_error() -> dict:
    """Return the canonical 403 payload when auth fails on a write endpoint."""
    token = _resolve_admin_token()
    if not token:
        return {
            "error": (
                "MC_ADMIN_TOKEN is not configured. LAN writes are disabled. "
                "Set MC_ADMIN_TOKEN in start-mc.sh or use loopback."
            ),
            "setup_required": True,
        }
    return {
        "error": "unauthorized: missing or invalid MC_ADMIN_TOKEN",
        "how": "Provide Authorization: Bearer *** or X-MC-Admin-Token: <token>",
    }


# --- Redaction ------------------------------------------------------------

# Keys whose value is ALWAYS a credential and should be entirely replaced.
SECRET_KEYS = {
    "token", "api_key", "apikey", "authorization", "auth", "password", "pwd",
    "secret", "bearer", "credential", "credentials", "access_token",
    "refresh_token", "private_key", "session_token", "csrf",
}

# Keys that hold graph/task identifiers. Recurse into them but NEVER
# blanket-replace their values (this is the bug NOFI reported: the old
# redactor was eating substrings of normal IDs).
GRAPH_KEYS = {
    "id", "source", "target", "kind", "label", "tags", "status",
    "project", "path", "task_id", "created", "updated", "weight",
    "importance", "confidence", "actor", "assignee", "assigned_to",
    "kanban_status",
}

# Keys whose value is user-written prose. Run pattern matches + truncate.
FREETEXT_KEYS = {
    "summary", "message", "body", "log", "text", "content",
    "description", "notes", "note",
}

# Regex patterns for secret-shaped strings. Applied to FREETEXT_KEYS and
# to the value of GRAPH_KEYS only when the WHOLE value matches.
SECRET_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}"), "sk-ant-[REDACTED]"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "sk-[REDACTED]"),
    (re.compile(r"ghp_[A-Za-z0-9]{8,}"), "ghp_[REDACTED]"),
    (re.compile(r"gho_[A-Za-z0-9]{8,}"), "gho_[REDACTED]"),
    (re.compile(r"ghu_[A-Za-z0-9]{8,}"), "ghu_[REDACTED]"),
    (re.compile(r"ghs_[A-Za-z0-9]{8,}"), "ghs_[REDACTED]"),
    (re.compile(r"ghr_[A-Za-z0-9]{8,}"), "ghr_[REDACTED]"),
    (re.compile(r"xox[bp]-[A-Za-z0-9\-]{8,}"), "xox*-[REDACTED]"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AKIA[REDACTED]"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), "[JWT]"),
    (re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9_\-\.=]{8,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(Authorization:\s*)[A-Za-z0-9_\-\.=]{8,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(api[_\-]?key\s*[=:]\s*)[^\s,'\"}\]\)]{3,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(token\s*[=:]\s*)[A-Za-z0-9_\-\.]{8,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(password\s*[=:]\s*)[^\s,'\"}\]\)]{3,}"), r"\1[REDACTED]"),
]

_FREETEXT_MAX_LEN = 500


def _redact_freetext(s: Any) -> Any:
    """Apply regex patterns + truncate. Return s unchanged if non-string."""
    if not isinstance(s, str):
        return s
    out = s
    for pat, repl in SECRET_PATTERNS:
        out = pat.sub(repl, out)
    if len(out) > _FREETEXT_MAX_LEN:
        out = out[:_FREETEXT_MAX_LEN] + "...[truncated]"
    return out


def _looks_like_a_secret_string(s: str) -> bool:
    """True if the entire string matches one of the SECRET_PATTERNS."""
    if not s or len(s) < 8:
        return False
    for pat, _ in SECRET_PATTERNS:
        m = pat.fullmatch(s)
        if m:
            return True
    return False


def redact_secrets(obj: Any) -> Any:
    """Field-aware redactor. Returns a new structure; never mutates input.

    - SECRET_KEYS → value becomes '[REDACTED]' (unless it was already empty).
    - GRAPH_KEYS  → recurse into nested structures; for STRING values, do
                    NOT apply pattern regex (that's the bug NOFI reported:
                    pattern `sk-[A-Za-z0-9_\-]{16,}` matches `sk-MC-...`
                    inside `task-MC-...`). Instead, only check if the WHOLE
                    string value is a secret; if so, replace it. This
                    preserves normal IDs like `task-MC-MEMORY-GRAPH-3`.
    - FREETEXT_KEYS → recurse then run pattern matches + truncate.
    - Anything else → recurse, then run pattern matches at the end.
    """
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj
    if isinstance(obj, str):
        return _redact_freetext(obj)
    if isinstance(obj, dict):
        out: dict = {}
        for k, v in obj.items():
            kl = str(k).lower()
            if kl in SECRET_KEYS:
                out[k] = "[REDACTED]" if v not in (None, "", b"") else v
            elif kl in GRAPH_KEYS:
                if isinstance(v, str):
                    # Whole-value check: only redact if the ENTIRE value
                    # looks like a secret. Pattern matching on substrings
                    # is exactly the bug we're fixing.
                    if _looks_like_a_secret_string(v):
                        out[k] = "[REDACTED]"
                    else:
                        # Apply freetext truncation (500-char cap) only,
                        # NOT the regex patterns.
                        out[k] = v if len(v) <= _FREETEXT_MAX_LEN else v[:_FREETEXT_MAX_LEN] + "...[truncated]"
                elif isinstance(v, (dict, list)):
                    out[k] = redact_secrets(v)
                else:
                    out[k] = v
            elif kl in FREETEXT_KEYS:
                out[k] = redact_secrets(v)
            else:
                out[k] = redact_secrets(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [redact_secrets(x) for x in obj]
    # Fallback: stringify, redact, keep as string.
    try:
        return _redact_freetext(str(obj))
    except Exception:
        return obj
