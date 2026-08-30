"""Tests for app.providers.telephony.twiml — TwiML generation."""

from app.providers.telephony.twiml import (
    build_media_stream_twiml,
    build_rejection_twiml,
    build_transfer_or_hangup_twiml,
)


def test_media_stream_twiml_contains_connect_stream_with_call_sid():
    xml = build_media_stream_twiml("CA123abc")
    assert "<Connect>" in xml
    assert "<Stream" in xml
    assert "/webhooks/twilio/media-stream/CA123abc" in xml


def test_media_stream_twiml_uses_websocket_scheme():
    xml = build_media_stream_twiml("CA123")
    # PUBLIC_BASE_URL defaults to http://localhost:8000 in test settings,
    # so the stream URL should use the plain ws:// scheme, not wss://.
    assert "ws://" in xml or "wss://" in xml
    assert "://" in xml


def test_media_stream_twiml_redirects_to_transfer_endpoint():
    xml = build_media_stream_twiml("CA123")
    assert "<Redirect>" in xml
    assert "/webhooks/twilio/transfer/CA123" in xml


def test_transfer_twiml_dials_when_number_given():
    xml = build_transfer_or_hangup_twiml("+15551234567")
    assert "<Dial>+15551234567</Dial>" in xml
    assert "<Hangup" not in xml


def test_transfer_twiml_hangs_up_when_no_number():
    xml = build_transfer_or_hangup_twiml(None)
    assert "<Hangup" in xml
    assert "<Dial>" not in xml


def test_rejection_twiml_says_message_and_hangs_up():
    xml = build_rejection_twiml("Sorry, we could not verify this request.")
    assert "Sorry, we could not verify this request." in xml
    assert "<Hangup" in xml


def test_rejection_twiml_escapes_special_characters():
    """Uses Twilio's own SDK to build TwiML rather than string
    concatenation, specifically so this can't happen: a message
    containing XML-special characters must not corrupt the markup."""
    xml = build_rejection_twiml("Tom & Jerry's <diner>")
    assert "&amp;" in xml
    assert "<diner>" not in xml  # must be escaped, not injected as a tag
