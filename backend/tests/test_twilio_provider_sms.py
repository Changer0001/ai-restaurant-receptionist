"""
Tests for TwilioTelephonyProvider.send_sms — the notification worker's
only path for sending SMS (see app/services/notification_service.py).

Twilio's SDK Client is synchronous/requests-based, so these tests
monkeypatch its `messages.create` rather than making a real network
call — the same trust boundary every other provider test in this suite
draws around the actual third-party call.
"""

from dataclasses import dataclass

import pytest

from app.providers.telephony.twilio_provider import TwilioTelephonyProvider


@dataclass
class _FakeMessageInstance:
    sid: str = "SM1234567890"
    status: str = "queued"


def _provider() -> TwilioTelephonyProvider:
    return TwilioTelephonyProvider(account_sid="ACxxx", auth_token="tok", webhook_secret="")


async def test_send_sms_calls_twilio_with_the_right_arguments(monkeypatch):
    provider = _provider()
    calls = []

    def fake_create(*, to, from_, body):
        calls.append({"to": to, "from_": from_, "body": body})
        return _FakeMessageInstance()

    monkeypatch.setattr(provider.client.messages, "create", fake_create)

    result = await provider.send_sms(to="+15551234567", from_="+15559876543", body="hello")

    assert calls == [{"to": "+15551234567", "from_": "+15559876543", "body": "hello"}]
    assert result == {"sid": "SM1234567890", "status": "queued"}


async def test_send_sms_propagates_a_twilio_failure(monkeypatch):
    """send_sms must not swallow errors — notification_service._send_one
    is what's responsible for catching this and recording it."""
    provider = _provider()

    def fake_create(*, to, from_, body):
        raise RuntimeError("simulated Twilio API error")

    monkeypatch.setattr(provider.client.messages, "create", fake_create)

    with pytest.raises(RuntimeError, match="simulated Twilio API error"):
        await provider.send_sms(to="+15551234567", from_="+15559876543", body="hello")
