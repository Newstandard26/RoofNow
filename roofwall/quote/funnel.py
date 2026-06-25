"""Lead funnel — fan a captured lead out to the sales channels.

The intake form gates the quote; once a lead is validated, this module pushes
it to wherever the team works. Phase 1 wires three env-gated sinks, each
best-effort (a failure NEVER blocks the lead or the homeowner's quote):

    1. Email     -> SMTP   (SMTP_HOST/PORT/USER/PASS, LEAD_NOTIFY_TO/FROM)
    2. Slack     -> Slack Incoming Webhook   (SLACK_WEBHOOK_URL)
    3. Zapier/CRM-> Zapier Catch Hook (LEAD_WEBHOOK_URL) -> AccuLynx + LeadConnector

The Zapier webhook payload is a flat, CRM-ready record (see
``lead_to_webhook_payload``) whose keys line up 1:1 with the AccuLynx "Create
Lead" and LeadConnector "Add/Update Contact" actions, so the Catch Hook zap
needs little/no field massaging. See docs/instant-quote/08_ZAPIER_SETUP.md.

Important: the lead endpoint runs as a Vercel serverless function, so it can't
use any interactive/desktop integration — each sink uses its own credential
from the environment. Configure whichever you want; unconfigured sinks are
skipped. Everything is also logged to stdout (Vercel function logs) regardless.

The message *builders* (``build_email``, ``build_slack_blocks``) are pure and
unit-tested; only ``funnel_lead`` does I/O.
"""

from __future__ import annotations

import os
import smtplib
import sys
from email.message import EmailMessage
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_NOTIFY_TO = "mattk@newstandardrestoration.com"

# Confidence band -> LeadConnector "Capture Confidence" custom-field value.
_CAPTURE_CONFIDENCE = {"high": "Complete", "medium": "Partial", "low": "Needs Review"}
# Confidence band -> CRM lead priority.
_LEAD_PRIORITY = {"high": "Hot", "medium": "Warm", "low": "Cold"}


def lead_to_webhook_payload(
    lead: Dict[str, Any], quote: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Flatten a lead + quote into a CRM-ready record for the Zapier Catch Hook.

    Keys are chosen to drop straight onto the AccuLynx "Create Lead" and
    LeadConnector "Add/Update Contact" fields (first_name, last_name, email,
    phone, address, estimate_amount, capture_confidence, …), so the zap maps
    fields with little/no transformation.
    """
    pr = (quote or {}).get("price_range") or {}
    conf = (quote or {}).get("confidence") or {}
    band = conf.get("band")
    low = pr.get("low", lead.get("estimate_low"))
    high = pr.get("high", lead.get("estimate_high"))
    estimate_display = pr.get("display")
    if not estimate_display and (low or high):
        estimate_display = f"{_money(low)} – {_money(high)}"

    return {
        # contact
        "first_name": lead.get("first_name", ""),
        "last_name": lead.get("last_name", ""),
        "name": lead.get("name", ""),
        "email": lead.get("email", ""),
        "phone": lead.get("phone", ""),
        "address": lead.get("address", ""),
        # quote
        "tier": lead.get("tier"),
        "estimate_low": low,
        "estimate_high": high,
        "estimate_amount": estimate_display,
        "confidence_band": band,
        "confidence_pct": conf.get("confidence_pct"),
        "capture_confidence": _CAPTURE_CONFIDENCE.get(band) if band else None,
        "lead_priority": _LEAD_PRIORITY.get(band) if band else None,
        # CRM routing defaults (RoofNow is a website roof-replacement intake form)
        "source": "RoofNow Instant Quote",
        "lead_source_detail": "Website Form",
        "captured_by_agent": "Form",
        "service_needed": "Roof Replacement",
        "lead_type": "Residential",
        "property_type": "Single-Family",
        "pipeline_stage": "New Lead",
        "notes": " | ".join(_summary_lines(lead, quote)),
    }


def _money(v: Any) -> str:
    try:
        return f"${int(v):,}"
    except (TypeError, ValueError):
        return "n/a"


def _summary_lines(lead: Dict[str, Any], quote: Optional[Dict[str, Any]]) -> List[str]:
    """Shared human-readable summary used by both the email and Slack messages."""
    lines = [
        f"Name:    {lead.get('name') or '—'}",
        f"Phone:   {lead.get('phone') or '—'}",
        f"Email:   {lead.get('email') or '—'}",
        f"Address: {lead.get('address') or '—'}",
    ]
    if lead.get("tier"):
        lines.append(f"Interested in: {str(lead['tier']).title()} package")
    if quote:
        pr = quote.get("price_range") or {}
        if pr.get("display"):
            lines.append(f"Instant estimate: {pr['display']}")
        conf = quote.get("confidence") or {}
        if conf.get("band"):
            lines.append(
                f"Confidence: {conf['band']} ({conf.get('confidence_pct', '—')}%)"
            )
    elif lead.get("estimate_low") or lead.get("estimate_high"):
        lines.append(
            f"Instant estimate: {_money(lead.get('estimate_low'))} – "
            f"{_money(lead.get('estimate_high'))}"
        )
    return lines


def build_email(lead: Dict[str, Any], quote: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """(subject, body) for the team notification email."""
    name = lead.get("name") or "New lead"
    subject = f"New RoofNow lead: {name} — {lead.get('address') or 'address pending'}"
    body = "A homeowner just requested an instant roof quote on RoofNow.\n\n"
    body += "\n".join(_summary_lines(lead, quote))
    body += "\n\nFollow up to book the free inspection."
    return subject, body


def build_slack_blocks(lead: Dict[str, Any], quote: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Slack Incoming Webhook payload (text + a tidy section block)."""
    summary = "\n".join(_summary_lines(lead, quote))
    header = f":house: New RoofNow lead — {lead.get('name') or 'Unknown'}"
    return {
        "text": f"{header}\n{summary}",
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": "New RoofNow lead"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": summary}},
        ],
    }


# --------------------------------------------------------------------------- #
# I/O sinks — each best-effort, returns "sent" | "skipped" | "error: ..."
# --------------------------------------------------------------------------- #


def _send_webhook(lead: Dict[str, Any], quote: Optional[Dict[str, Any]]) -> str:
    url = os.environ.get("LEAD_WEBHOOK_URL")
    if not url:
        return "skipped"
    try:
        import requests

        requests.post(url, json=lead_to_webhook_payload(lead, quote), timeout=5)
        return "sent"
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"


def _send_slack(lead: Dict[str, Any], quote: Optional[Dict[str, Any]]) -> str:
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        return "skipped"
    try:
        import requests

        requests.post(url, json=build_slack_blocks(lead, quote), timeout=5)
        return "sent"
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"


def _send_email(lead: Dict[str, Any], quote: Optional[Dict[str, Any]]) -> str:
    host = os.environ.get("SMTP_HOST")
    if not host:
        return "skipped"
    try:
        port = int(os.environ.get("SMTP_PORT", "587"))
        user = os.environ.get("SMTP_USER")
        password = os.environ.get("SMTP_PASS")
        to_addr = os.environ.get("LEAD_NOTIFY_TO", DEFAULT_NOTIFY_TO)
        from_addr = os.environ.get("LEAD_NOTIFY_FROM", user or to_addr)

        subject, body = build_email(lead, quote)
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_addr
        if lead.get("email"):
            msg["Reply-To"] = lead["email"]
        msg.set_content(body)

        with smtplib.SMTP(host, port, timeout=10) as server:
            server.starttls()
            if user and password:
                server.login(user, password)
            server.send_message(msg)
        return "sent"
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"


def funnel_lead(lead: Dict[str, Any], quote: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Fan a validated lead out to all configured sinks. Never raises.

    Returns a per-sink status map, e.g. ``{"email": "sent", "slack": "skipped",
    "webhook": "sent"}``. Unconfigured sinks report ``"skipped"``.
    """
    results = {
        "email": _send_email(lead, quote),
        "slack": _send_slack(lead, quote),
        "webhook": _send_webhook(lead, quote),
    }
    print(f"[lead] funneled {lead.get('email')} -> {results}", file=sys.stderr)
    return results
