"""Lead capture validation — intake form gates the quote, so all fields required."""
import pytest

from roofwall.quote.lead import validate_lead


def _full(**over):
    base = {
        "first_name": "Jane", "last_name": "Roof",
        "email": "Jane@Example.com", "phone": "(555) 123-4567",
        "address": "1 Oak St", "tier": "better",
    }
    base.update(over)
    return base


def test_valid_full_lead():
    lead, errors = validate_lead(_full())
    assert errors == []
    assert lead["first_name"] == "Jane"
    assert lead["last_name"] == "Roof"
    assert lead["name"] == "Jane Roof"
    assert lead["email"] == "jane@example.com"
    assert lead["phone"] == "5551234567"
    assert lead["tier"] == "better"
    assert lead["source"] == "roofnow_instant_quote"


def test_combined_name_back_compat():
    lead, errors = validate_lead(_full(first_name="", last_name="", name="Bob Smith"))
    assert errors == []
    assert lead["first_name"] == "Bob"
    assert lead["last_name"] == "Smith"


@pytest.mark.parametrize("missing", ["first_name", "last_name", "email", "phone", "address"])
def test_each_field_required(missing):
    _, errors = validate_lead(_full(**{missing: ""}))
    assert errors, f"expected an error when {missing} is blank"


def test_invalid_email():
    _, errors = validate_lead(_full(email="not-an-email"))
    assert any("Email" in e for e in errors)


def test_short_phone():
    _, errors = validate_lead(_full(phone="12345"))
    assert any("Phone" in e for e in errors)


def test_bad_tier_dropped_not_fatal():
    lead, errors = validate_lead(_full(tier="platinum"))
    assert errors == []
    assert lead["tier"] is None
