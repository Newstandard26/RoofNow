"""Address -> (lat, lng) via the Google Geocoding API.

Injectable ``http_get`` for tests, same pattern as the Solar client.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Optional

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


class GeocodeError(RuntimeError):
    """Geocoding failed or returned no result."""


@dataclass(frozen=True)
class GeocodeResult:
    lat: float
    lng: float
    formatted_address: str


class Geocoder:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        http_get: Optional[Callable[..., Any]] = None,
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY")
        self._http_get = http_get
        self.timeout = timeout

    def geocode(self, address: str) -> GeocodeResult:
        if not self.api_key:
            raise GeocodeError("no API key; set GOOGLE_MAPS_API_KEY")
        params = {"address": address, "key": self.api_key}

        if self._http_get is not None:
            data = self._http_get(GEOCODE_URL, params=params, timeout=self.timeout)
        else:
            import requests

            resp = requests.get(GEOCODE_URL, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                raise GeocodeError(f"geocode HTTP {resp.status_code}")
            data = resp.json()

        results = data.get("results") or []
        if data.get("status") != "OK" or not results:
            raise GeocodeError(
                f"geocode status={data.get('status')!r} for {address!r}"
            )
        top = results[0]
        loc = top["geometry"]["location"]
        return GeocodeResult(
            lat=float(loc["lat"]),
            lng=float(loc["lng"]),
            formatted_address=top.get("formatted_address", address),
        )
