# Backend Implementation Plan

Create package:

roofwall/property_report/
- __init__.py
- schema.py
- service.py
- summary.py
- health.py
- storm.py
- recommendation.py

Main function:

build_property_report(address, lead=None) -> dict

Reuse:
- measurement engine
- confidence engine
- pricing engine
- quote output

Failure mode: if measurement fails, return low-confidence manual estimate CTA.
