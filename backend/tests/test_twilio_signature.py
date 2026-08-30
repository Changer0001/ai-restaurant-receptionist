"""
Tests for Twilio webhook signature validation.

This is the entire authorization boundary for the /webhooks/twilio/*
router (callers have no account/JWT) — these tests exist because Phase
1 originally shipped this check as `return signature is not None`, which
accepted literally any non-empty string as valid. That is exactly the
class of bug these tests are written to catch a regression of.
"""

from twilio.request_validator import RequestValidator

from app.providers.telephony.twilio_provider import TwilioTelephonyProvider

_AUTH_TOKEN = "test_auth_token_12345"
_URL = "https://example.com/webhooks/twilio/voice"
_PARAMS = {"CallSid": "CA123", "From": "+15551234567", "To": "+15559876543"}


def _provider() -> TwilioTelephonyProvider:
    return TwilioTelephonyProvider(account_sid="ACxxx", auth_token=_AUTH_TOKEN, webhook_secret="")


def _real_signature(url: str = _URL, params: dict = _PARAMS) -> str:
    return RequestValidator(_AUTH_TOKEN).compute_signature(url, params)


async def test_valid_signature_is_accepted():
    provider = _provider()
    assert await provider.validate_webhook_signature(_real_signature(), _URL, _PARAMS) is True


async def test_tampered_param_is_rejected():
    provider = _provider()
    signature = _real_signature()  # signed over the original params
    tampered = dict(_PARAMS, From="+19995551234")
    assert await provider.validate_webhook_signature(signature, _URL, tampered) is False


async def test_tampered_url_is_rejected():
    provider = _provider()
    signature = _real_signature()
    assert (
        await provider.validate_webhook_signature(
            signature, "https://evil.example.com/voice", _PARAMS
        )
        is False
    )


async def test_completely_fake_signature_is_rejected():
    provider = _provider()
    assert await provider.validate_webhook_signature("not-a-real-signature", _URL, _PARAMS) is False


async def test_empty_signature_is_rejected():
    """The original bug: `signature is not None` accepted an empty
    string (it's not None, just falsy) as a valid signature."""
    provider = _provider()
    assert await provider.validate_webhook_signature("", _URL, _PARAMS) is False


async def test_signature_from_a_different_auth_token_is_rejected():
    """Simulates an attacker who doesn't know this restaurant's/
    account's real Twilio auth token trying to forge a plausible-looking
    signature with a different one."""
    wrong_signature = RequestValidator("some_other_token").compute_signature(_URL, _PARAMS)
    provider = _provider()
    assert await provider.validate_webhook_signature(wrong_signature, _URL, _PARAMS) is False


async def test_extra_unsigned_param_is_rejected():
    """A request with an extra parameter appended after signing must not
    validate — Twilio signs over the exact parameter set it sent."""
    provider = _provider()
    signature = _real_signature()
    extra = dict(_PARAMS, Extra="injected")
    assert await provider.validate_webhook_signature(signature, _URL, extra) is False
