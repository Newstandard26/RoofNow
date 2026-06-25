"""Lead funnel — fan a captured lead out to the sales channels.

The intake form gates the quote; once a lead is validated, this module pushes
it to wherever the team works. Phase 1 wires three env-gated sinks, each
best-effort (a failure NEVER blocks the lead or the homeowner's quote):

    1. Email     -> SMTP   (SMTP_HOST/PORT/USER/PASS, LEAD_NOTIFY_TO/FROM)
    2. Slack     -> Slack Incoming Webhook   (SLACK_WEBHOOK_URL)
    3. Zapier/CRM-> generic JSON webhook      (LEAD_WEBHOOK_URL)

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

        payload = dict(lead)
        if quote:
            payload["quote"] = {
                "price_range": quote.get("price_range"),
                "confidence": quote.get("confidence"),
            }
        requests.post(url, json=payload, timeout=5)
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
