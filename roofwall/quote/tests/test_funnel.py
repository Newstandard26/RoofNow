"""Lead funnel message builders + env-gated sink dispatch."""
import pytest

from roofwall.quote.funnel import (
    build_email,
    build_slack_blocks,
    funnel_lead,
)

_LEAD = {
    "name": "Jane Roof", "first_name": "Jane", "last_name": "Roof",
    "email": "jane@example.com", "phone": "5551234567",
    "address": "1 Oak St, Springfield", "tier": "better",
}
_QUOTE = {
    "price_range": {"low": 12000, "high": 21000, "display": "$12,000 – $21,000"},
    "confidence": {"band": "high", "confidence_pct": 90},
}


def test_build_email_has_contact_and_estimate():
    subject, body = build_email(_LEAD, _QUOTE)
    assert "Jane Roof" in subject and "1 Oak St" in subject
    assert "jane@example.com" in body
    assert "5551234567" in body
    assert "$12,000 – $21,000" in body
    assert "Better" in body  # tier interest


def test_build_email_without_quote():
    subject, body = build_email(_LEAD, None)
    assert "Jane Roof" in subject
    assert "1 Oak St" in body


def test_build_slack_blocks_shape():
    payload = build_slack_blocks(_LEAD, _QUOTE)
    assert "text" in payload and "blocks" in payload
    assert "Jane Roof" in payload["text"]
    assert any(b["type"] == "header" for b in payload["blocks"])
    assert "high" in payload["text"]


def test_funnel_skips_when_nothing_configured(monkeypatch):
    for var in ("LEAD_WEBHOOK_URL", "SLACK_WEBHOOK_URL", "SMTP_HOST"):
        monkeypatch.delenv(var, raising=False)
    results = funnel_lead(_LEAD, _QUOTE)
    assert results == {"email": "skipped", "slack": "skipped", "webhook": "skipped"}


def test_funnel_webhook_dispatched(monkeypatch):
    sent = {}

    class _Resp:
        pass

    def fake_post(url, json=None, timeout=None):
        sent["url"] = url
        sent["json"] = json
        return _Resp()

    import sys
    import types
    fake_requests = types.ModuleType("requests")
    fake_requests.post = fake_post
    monkeypatch.setitem(sys.modules, "requests", fake_requests)

    monkeypatch.setenv("LEAD_WEBHOOK_URL", "https://hooks.example.com/x")
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)

    results = funnel_lead(_LEAD, _QUOTE)
    assert results["webhook"] == "sent"
    assert sent["url"] == "https://hooks.example.com/x"
    assert sent["json"]["email"] == "jane@example.com"
    assert sent["json"]["quote"]["price_range"]["low"] == 12000


def test_funnel_never_raises_on_sink_error(monkeypatch):
    import sys
    import types

    def boom(*a, **k):
        raise RuntimeError("network down")

    fake_requests = types.ModuleType("requests")
    fake_requests.post = boom
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/x")
    monkeypatch.delenv("LEAD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)

    results = funnel_lead(_LEAD, _QUOTE)
    assert results["slack"].startswith("error:")  # captured, not raised
