"""Admin shared-password auth (Phase 3)."""
import pytest

from roofwall import admin_auth


def test_disabled_without_password(monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("ADMIN_TOKEN_SECRET", raising=False)
    assert admin_auth.admin_enabled() is False
    assert admin_auth.check_password("anything") is False
    assert admin_auth.verify_token("whatever.sig") is False


def test_password_check(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    assert admin_auth.check_password("s3cret") is True
    assert admin_auth.check_password("nope") is False


def test_token_round_trip(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    monkeypatch.delenv("ADMIN_TOKEN_SECRET", raising=False)
    tok = admin_auth.issue_token(ttl_seconds=100, now=1000)
    assert admin_auth.verify_token(tok, now=1050) is True
    # expired
    assert admin_auth.verify_token(tok, now=2000) is False
    # tampered
    exp, _, sig = tok.partition(".")
    assert admin_auth.verify_token(exp + ".deadbeef", now=1050) is False


def test_token_secret_change_invalidates(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "s3cret")
    tok = admin_auth.issue_token(ttl_seconds=100, now=1000)
    monkeypatch.setenv("ADMIN_PASSWORD", "different")
    assert admin_auth.verify_token(tok, now=1050) is False


def test_bearer_token_parsing():
    assert admin_auth.bearer_token({"authorization": "Bearer abc.def"}) == "abc.def"
    assert admin_auth.bearer_token({"Authorization": "bearer xyz"}) == "xyz"
    assert admin_auth.bearer_token({}) == ""
