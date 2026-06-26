"""Supabase-backed pricing config store (Phase 3).

The admin dashboard edits pricing, but Vercel functions are stateless — so the
active rate card lives in Supabase (table ``pricing_config``, append-only with an
``is_active`` flag). Functions read it server-side with the service-role key
(RLS-protected; never reachable from the browser).

Reads are cached per warm instance (short TTL) so we don't hit Supabase on every
quote. All reads are best-effort: any error returns ``None`` so
``load_pricing()`` cleanly falls back to env/file/built-in defaults.

Config via env (server-side only):
    SUPABASE_URL                 e.g. https://<ref>.supabase.co
    SUPABASE_SERVICE_ROLE_KEY    service-role key (bypasses RLS)
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict, Optional, Tuple

_TABLE = "pricing_config"
_CACHE_TTL_SECONDS = 60.0
_cache: Dict[str, Any] = {"at": 0.0, "value": None}


def _creds() -> Optional[Tuple[str, str]]:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None
    return url.rstrip("/"), key


def _headers(key: str, *, write: bool = False) -> Dict[str, str]:
    h = {"apikey": key, "Authorization": f"Bearer {key}",
         "Content-Type": "application/json"}
    if write:
        h["Prefer"] = "return=representation"
    return h


def enabled() -> bool:
    return _creds() is not None


def load_active_config_dict(*, use_cache: bool = True) -> Optional[Dict[str, Any]]:
    """Return the active pricing config dict from Supabase, or None."""
    creds = _creds()
    if not creds:
        return None
    now = time.monotonic()
    if use_cache and _cache["value"] is not None and (now - _cache["at"]) < _CACHE_TTL_SECONDS:
        return _cache["value"]
    url, key = creds
    try:
        import requests

        resp = requests.get(
            f"{url}/rest/v1/{_TABLE}",
            headers=_headers(key),
            params={"is_active": "eq.true", "select": "config,created_at",
                    "order": "created_at.desc", "limit": "1"},
            timeout=5,
        )
        resp.raise_for_status()
        rows = resp.json()
        cfg = rows[0]["config"] if rows else None
        _cache.update(at=now, value=cfg)
        return cfg
    except Exception as exc:  # noqa: BLE001
        print(f"[pricing_store] read failed: {exc}", file=sys.stderr)
        return None


def save_config_dict(config: Dict[str, Any], *, updated_by: str = "admin",
                     label: str = "admin") -> Dict[str, Any]:
    """Append a new active config version (deactivating the previous active).

    Raises on failure (the admin API surfaces the error). Invalidates the cache.
    """
    creds = _creds()
    if not creds:
        raise RuntimeError("Supabase is not configured (SUPABASE_URL / SERVICE_ROLE_KEY).")
    url, key = creds
    import requests

    # Deactivate current active version(s), then insert the new active one.
    requests.patch(
        f"{url}/rest/v1/{_TABLE}",
        headers=_headers(key, write=True),
        params={"is_active": "eq.true"},
        json={"is_active": False},
        timeout=5,
    ).raise_for_status()

    resp = requests.post(
        f"{url}/rest/v1/{_TABLE}",
        headers=_headers(key, write=True),
        json={"config": config, "is_active": True, "label": label,
              "updated_by": updated_by},
        timeout=5,
    )
    resp.raise_for_status()
    _cache.update(at=0.0, value=None)   # invalidate
    row = resp.json()
    return row[0] if isinstance(row, list) and row else row
