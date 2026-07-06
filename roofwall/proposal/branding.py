"""Company branding + boilerplate for the roof proposal PDF.

Company-specific only (no individual rep). Values come from New Standard
Restoration's materials; edit here (or override select fields via env) to change
what appears on every proposal.
"""

from __future__ import annotations

import os
from typing import Any, Dict

# NSR blue + dark palette (matches the site).
NSR_BLUE = "#51C5F4"
NSR_BLUE_DARK = "#1597D4"
DARK = "#0A0E14"
CHARCOAL = "#121A24"
INK = "#101820"
MUTED = "#5F6B7A"

COMPANY: Dict[str, Any] = {
    "name": "New Standard Restoration, LLC",
    "short_name": "New Standard Restoration",
    "tagline": "Roscoe's Most Trusted Roofing & Siding Experts",
    "phone": os.environ.get("NSR_PHONE", "(833) 773-7160"),
    "email": os.environ.get("NSR_EMAIL", "info@newstandardrestoration.com"),
    "website": "newstandardrestoration.com",
    "website_url": "https://newstandardrestoration.com",
    "address": "4675 Bluestem Road, Roscoe, IL 61073",
    "license": os.environ.get("NSR_LICENSE", "License # 104.020070"),
    "certification": "Owens Corning Preferred Contractor",
    "who_we_are": (
        "At New Standard Restoration, we raise the bar in roofing and siding. Our "
        "mission is simple: protect your home like it's our own. As an Owens Corning "
        "Preferred Contractor, we deliver precision, professionalism, and lasting quality."
    ),
    "features": [
        ("Licensed & Insured", "Fully licensed and insured for your peace of mind and protection."),
        ("Financing Available", "Flexible payment plans with $0 down options for qualified customers."),
        ("Insurance Claims", "We work with all insurance companies to make your claims process smooth."),
        ("Workmanship Warranty", "Industry-leading warranties for lasting peace of mind."),
    ],
    "testimonials": [
        ("They worked directly with my insurance company and had my new roof completed in "
         "record time. Five stars!", "Robert T.", "Loves Park, IL"),
        ("Professional from the first call to the final walk-through. The crew was clean, "
         "fast, and respectful of our home.", "Lisa J.", "Rockford, IL"),
    ],
    # NSR scope-of-work boilerplate for a full roof replacement.
    "scope_of_work": [
        "Remove and dispose of the existing roof.",
        "Price is based on 1 layer removal unless otherwise stated; each additional layer "
        "is charged at $40/sq.",
        "Roof substrate inspected after tear-off. Rotted/deteriorated wood replaced to "
        "maintain a nailable surface (plywood $60/sheet, dimensional lumber $8/foot).",
        "Install Owens Corning synthetic underlayment.",
        "Install Owens Corning ice & water shield to meet code requirements.",
        "Replace all penetration flashings and any damaged step, roof-to-wall, and chimney "
        "flashings.",
        "Provide a dedicated on-site supervisor.",
        "Complete clean-up and a final walk-through at the end of the job.",
        "Owens Corning Preferred Warranty: 10-year labor / lifetime manufacturing "
        "(non-prorated).",
    ],
}
