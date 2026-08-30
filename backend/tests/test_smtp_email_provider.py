"""
Tests for SMTPEmailProvider — monkeypatches aiosmtplib's `send`/`SMTP`
rather than talking to a real SMTP server, the same trust boundary
every other provider test in this suite draws around the actual
third-party call (see e.g. test_twilio_provider_sms.py).
"""

import pytest

import app.providers.email.smtp_provider as smtp_provider_module
from app.providers.email.smtp_provider import SMTPEmailProvider


def _provider(**overrides) -> SMTPEmailProvider:
    defaults = {
        "host": "smtp.example.com",
        "port": 587,
        "username": "user@example.com",
        "password": "secret",
        "from_email": "noreply@restaurant.local",
        "from_name": "AI Receptionist",
    }
    defaults.update(overrides)
    return SMTPEmailProvider(**defaults)


async def test_send_email_builds_and_sends_the_right_message(monkeypatch):
    provider = _provider()
    sent = []

    async def fake_send(message, **kwargs):
        sent.append((message, kwargs))
        return ({}, "OK")

    monkeypatch.setattr(smtp_provider_module.aiosmtplib, "send", fake_send)

    await provider.send_email("owner@testbistro.example", "New reservation", "Party of 4 at 7pm")

    assert len(sent) == 1
    message, kwargs = sent[0]
    assert message["To"] == "owner@testbistro.example"
    assert message["Subject"] == "New reservation"
    assert "noreply@restaurant.local" in str(message["From"])
    assert "AI Receptionist" in str(message["From"])
    assert message.get_content().strip() == "Party of 4 at 7pm"
    assert kwargs["hostname"] == "smtp.example.com"
    assert kwargs["port"] == 587
    assert kwargs["username"] == "user@example.com"
    assert kwargs["password"] == "secret"
    assert kwargs["start_tls"] is True
    assert kwargs["use_tls"] is False


async def test_send_email_uses_implicit_tls_on_port_465(monkeypatch):
    provider = _provider(port=465)
    sent = []

    async def fake_send(message, **kwargs):
        sent.append(kwargs)
        return ({}, "OK")

    monkeypatch.setattr(smtp_provider_module.aiosmtplib, "send", fake_send)

    await provider.send_email("to@example.com", "Subject", "Body")

    assert sent[0]["use_tls"] is True
    assert sent[0]["start_tls"] is None


async def test_send_email_with_no_configured_credentials_passes_none(monkeypatch):
    provider = _provider(username="", password="")
    sent = []

    async def fake_send(message, **kwargs):
        sent.append(kwargs)
        return ({}, "OK")

    monkeypatch.setattr(smtp_provider_module.aiosmtplib, "send", fake_send)

    await provider.send_email("to@example.com", "Subject", "Body")

    assert sent[0]["username"] is None
    assert sent[0]["password"] is None


async def test_send_email_propagates_a_send_failure(monkeypatch):
    provider = _provider()

    async def fake_send(message, **kwargs):
        raise RuntimeError("simulated SMTP failure")

    monkeypatch.setattr(smtp_provider_module.aiosmtplib, "send", fake_send)

    with pytest.raises(RuntimeError, match="simulated SMTP failure"):
        await provider.send_email("to@example.com", "Subject", "Body")


class _FakeSMTPClient:
    def __init__(self, *, should_fail: bool = False, **kwargs):
        self._should_fail = should_fail
        self.connected = False

    async def connect(self):
        if self._should_fail:
            raise ConnectionRefusedError("simulated connection failure")
        self.connected = True

    async def quit(self):
        self.connected = False


async def test_health_check_true_on_successful_connect(monkeypatch):
    provider = _provider()
    monkeypatch.setattr(
        smtp_provider_module.aiosmtplib, "SMTP", lambda **kwargs: _FakeSMTPClient(should_fail=False)
    )

    assert await provider.health_check() is True


async def test_health_check_false_on_connect_failure(monkeypatch):
    provider = _provider()
    monkeypatch.setattr(
        smtp_provider_module.aiosmtplib, "SMTP", lambda **kwargs: _FakeSMTPClient(should_fail=True)
    )

    assert await provider.health_check() is False
