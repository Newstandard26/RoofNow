"""Shared-password admin auth (Phase 3).

The pricing dashboard is gated by a single ``ADMIN_PASSWORD`` (set in Vercel).
On login we issue a short-lived HMAC-signed token (no server-side session store
needed — it verifies statelessly). The token's signing secret is
``ADMIN_TOKEN_SECRET`` if set, else ``ADMIN_PASSWORD``.

Admin is disabled entirely when ``ADMIN_PASSWORD`` is unset (every check fails),
so the dashboard is inert until you configure it.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Optional

DEFAULT_TTL_SECONDS = 12 * 3600


def admin_enabled() -> bool:
    return bool(os.environ.get("ADMIN_PASSWORD"))


def _secret() -> Optional[str]:
    return os.environ.get("ADMIN_TOKEN_SECRET") or os.environ.get("ADMIN_PASSWORD")


def check_password(password: str) -> bool:
    expected = os.environ.get("ADMIN_PASSWORD")
    if not expected:
        return False
    return hmac.compare_digest(str(password or ""), expected)


def issue_token(ttl_seconds: int = DEFAULT_TTL_SECONDS, *, now: Optional[int] = None) -> str:
    secret = _secret()
    if not secret:
        raise RuntimeError("admin not configured")
    exp = int(now if now is not None else time.time()) + int(ttl_seconds)
    sig = hmac.new(secret.encode(), str(exp).encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def verify_token(token: str, *, now: Optional[int] = None) -> bool:
    secret = _secret()
    if not secret or not token or "." not in str(token):
        return False
    exp_s, _, sig = str(token).partition(".")
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    if exp < int(now if now is not None else time.time()):
        return False
    expected = hmac.new(secret.encode(), exp_s.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


def bearer_token(headers) -> str:
    """Pull the token from an Authorization: Bearer <token> header."""
    auth = ""
    try:
        auth = headers.get("authorization", "") or headers.get("Authorization", "")
    except Exception:  # noqa: BLE001
        auth = ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""
