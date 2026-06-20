"""roofwall CLI.

    roofwall measure "1600 Pennsylvania Ave NW, Washington DC"
    roofwall measure --lat 38.8977 --lng -77.0365 --json

Phase 1: geocode -> Solar API -> measurement engine -> report.
On no Solar coverage (404) the tool reports the gap; the LiDAR fallback
(Phase 2) is not yet wired in.
"""

from __future__ import annotations

import argparse
import json
import sys

from roofwall.report.render import report_to_dict, report_to_text
from roofwall.sources.geocode import GeocodeError, Geocoder
from roofwall.sources.solar import CoverageError, SolarClient, SolarError


def _resolve_location(args) -> tuple[float, float, str | None]:
    if args.lat is not None and args.lng is not None:
        return args.lat, args.lng, None
    if not args.address:
        raise SystemExit("provide an address, or --lat and --lng")
    result = Geocoder(api_key=args.api_key).geocode(args.address)
    return result.lat, result.lng, result.formatted_address


def cmd_measure(args) -> int:
    try:
        lat, lng, formatted = _resolve_location(args)
    except GeocodeError as exc:
        print(f"geocode failed: {exc}", file=sys.stderr)
        return 2

    client = SolarClient(api_key=args.api_key)
    try:
        report = client.roof_report(lat, lng, waste_pct=args.waste)
    except CoverageError:
        print(
            "No Google Solar coverage for this location (HTTP 404).\n"
            "LiDAR fallback (Phase 2) is not yet available.",
            file=sys.stderr,
        )
        return 3
    except SolarError as exc:
        print(f"Solar API error: {exc}", file=sys.stderr)
        return 4

    address = formatted or args.address
    if args.json:
        meta = {"lat": lat, "lng": lng, "address": address}
        print(json.dumps(report_to_dict(report, meta=meta), indent=2))
    else:
        print(report_to_text(report, address=address))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="roofwall")
    sub = parser.add_subparsers(dest="command", required=True)

    m = sub.add_parser("measure", help="measure a roof from an address or coords")
    m.add_argument("address", nargs="?", help="street address")
    m.add_argument("--lat", type=float, help="latitude (skip geocoding)")
    m.add_argument("--lng", type=float, help="longitude (skip geocoding)")
    m.add_argument("--waste", type=float, default=None, help="waste fraction, e.g. 0.10")
    m.add_argument("--api-key", default=None, help="Google Maps API key (or env)")
    m.add_argument("--json", action="store_true", help="emit JSON instead of text")
    m.set_defaults(func=cmd_measure)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
