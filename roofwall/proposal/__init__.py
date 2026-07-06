"""RoofNow branded roof-proposal PDF (mailable to the customer).

Auto-generated per lead. Reuses the measurement + Good/Better/Best pricing from
:func:`roofwall.property_report.build_property_report`; adds a print-ready,
NSR-branded PDF that presents all three packages so the customer can choose.
Company-branded only (no individual sales rep).
"""

from roofwall.proposal.branding import COMPANY
from roofwall.proposal.pdf import build_proposal_pdf

__all__ = ["build_proposal_pdf", "COMPANY"]
