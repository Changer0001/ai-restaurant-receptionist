"""
Integration tests for the Twilio HTTP webhooks (voice, status, recording,
transfer). The media-stream WebSocket has its own test file
(test_media_stream_websocket.py).

Every test signs its request with a real, correctly-computed Twilio
signature (via the same RequestValidator Twilio itself uses) — these are
the tests that would have caught Phase 1's `signature is not None` bug
immediately, since a request with no signature override at all fails
every one of them.
"""

from twilio.request_validator import RequestValidator

from app.api.endpoints.twilio_webhooks import _get_telephony_provider
from app.db.models import Call, RestaurantPhoneNumber
from app.main import app
from app.providers.telephony.twilio_provider import TwilioTelephonyProvider

_TEST_AUTH_TOKEN = "test_webhook_auth_token"
_TWILIO_NUMBER = "+15559876543"


def _test_telephony_provider() -> TwilioTelephonyProvider:
    return TwilioTelephonyProvider(
        account_sid="ACtest", auth_token=_TEST_AUTH_TOKEN, webhook_secret=""
    )


def _sign(url: str, params: dict) -> str:
    return RequestValidator(_TEST_AUTH_TOKEN).compute_signature(url, params)


def _signed_post(client, path: str, params: dict, *, bad_signature: bool = False):
    url = f"http://testserver{path}"
    signature = "not-a-real-signature" if bad_signature else _sign(url, params)
    return client.post(path, data=params, headers={"X-Twilio-Signature": signature})


async def _add_twilio_number(db_session, restaurant, number: str = _TWILIO_NUMBER):
    db_session.add(
        RestaurantPhoneNumber(restaurant_id=restaurant.id, phone_number=number, is_active=True)
    )
    await db_session.commit()


def _use_test_telephony_provider(client):
    app.dependency_overrides[_get_telephony_provider] = _test_telephony_provider
    return client


# ----------------------------------------------------------------------
# /voice
# ----------------------------------------------------------------------


async def test_voice_webhook_creates_call_and_returns_stream_twiml(client, db_session, restaurant):
    await _add_twilio_number(db_session, restaurant)
    _use_test_telephony_provider(client)

    resp = _signed_post(
        client,
        "/webhooks/twilio/voice",
        {"CallSid": "CA_voice_1", "From": "+15551110000", "To": _TWILIO_NUMBER},
    )

    assert resp.status_code == 200
    assert "<Connect>" in resp.text
    assert "CA_voice_1" in resp.text

    from sqlalchemy import select

    result = await db_session.execute(select(Call).where(Call.call_sid == "CA_voice_1"))
    call = result.scalar_one()
    assert call.restaurant_id == restaurant.id
    assert call.caller_number == "+15551110000"


def test_voice_webhook_rejects_invalid_signature(client, db_session, restaurant):
    _use_test_telephony_provider(client)

    resp = _signed_post(
        client,
        "/webhooks/twilio/voice",
        {"CallSid": "CA_bad_sig", "From": "+1", "To": _TWILIO_NUMBER},
        bad_signature=True,
    )

    assert resp.status_code == 403
    assert "<Hangup" in resp.text


async def test_voice_webhook_unknown_number_is_graceful_and_creates_no_call(
    client, db_session, restaurant
):
    _use_test_telephony_provider(client)

    resp = _signed_post(
        client,
        "/webhooks/twilio/voice",
        {"CallSid": "CA_unknown", "From": "+1", "To": "+19995550000"},  # never mapped
    )

    assert resp.status_code == 200
    assert "not currently in service" in resp.text
    assert "<Connect>" not in resp.text

    from sqlalchemy import select

    result = await db_session.execute(select(Call).where(Call.call_sid == "CA_unknown"))
    assert result.scalar_one_or_none() is None


async def test_voice_webhook_never_leaks_another_restaurants_number_mapping(
    client, db_session, restaurant
):
    """Restaurant B's Twilio number must route to Restaurant B, never A —
    the whole basis of this system's multi-tenancy for voice calls."""
    from app.db.models import Restaurant as RestaurantModel

    restaurant_b = RestaurantModel(name="Restaurant B", timezone="America/New_York", is_active=True)
    db_session.add(restaurant_b)
    await db_session.flush()
    await _add_twilio_number(db_session, restaurant, "+15551110001")
    await _add_twilio_number(db_session, restaurant_b, "+15551110002")
    await db_session.commit()

    _use_test_telephony_provider(client)

    resp = _signed_post(
        client, "/webhooks/twilio/voice", {"CallSid": "CA_b", "From": "+1", "To": "+15551110002"}
    )
    assert resp.status_code == 200

    from sqlalchemy import select

    result = await db_session.execute(select(Call).where(Call.call_sid == "CA_b"))
    call = result.scalar_one()
    assert call.restaurant_id == restaurant_b.id
    assert call.restaurant_id != restaurant.id


# ----------------------------------------------------------------------
# /status
# ----------------------------------------------------------------------


async def test_status_webhook_finalizes_an_open_call(client, db_session, restaurant):
    from app.services import call_service

    call = await call_service.create_call(
        db_session, restaurant.id, "CA_status_1", "+1", _TWILIO_NUMBER
    )
    await db_session.commit()

    _use_test_telephony_provider(client)
    resp = _signed_post(
        client, "/webhooks/twilio/status", {"CallSid": "CA_status_1", "CallStatus": "completed"}
    )

    assert resp.status_code == 204

    await db_session.refresh(call)
    assert call.end_time is not None


def test_status_webhook_rejects_invalid_signature(client):
    _use_test_telephony_provider(client)
    resp = _signed_post(
        client,
        "/webhooks/twilio/status",
        {"CallSid": "CA_x", "CallStatus": "completed"},
        bad_signature=True,
    )
    assert resp.status_code == 403


# ----------------------------------------------------------------------
# /recording
# ----------------------------------------------------------------------


async def test_recording_webhook_stores_recording_url(client, db_session, restaurant):
    from app.services import call_service

    call = await call_service.create_call(
        db_session, restaurant.id, "CA_rec_1", "+1", _TWILIO_NUMBER
    )
    await db_session.commit()

    _use_test_telephony_provider(client)
    resp = _signed_post(
        client,
        "/webhooks/twilio/recording",
        {"CallSid": "CA_rec_1", "RecordingUrl": "https://api.twilio.com/recordings/RE123"},
    )

    assert resp.status_code == 204
    await db_session.refresh(call)
    assert call.recording_path == "https://api.twilio.com/recordings/RE123"


# ----------------------------------------------------------------------
# /transfer/{call_sid}
# ----------------------------------------------------------------------


async def test_transfer_webhook_dials_when_call_was_transferred(client, db_session, restaurant):
    from app.services import call_service

    call = await call_service.create_call(
        db_session, restaurant.id, "CA_transfer_1", "+1", _TWILIO_NUMBER
    )
    call.was_transferred = True
    await db_session.commit()

    _use_test_telephony_provider(client)
    resp = _signed_post(client, "/webhooks/twilio/transfer/CA_transfer_1", {})

    assert resp.status_code == 200
    assert f">{restaurant.transfer_number}</Dial>" in resp.text
    # Dialed as the restaurant, not as the customer — otherwise a caller
    # whose own line is the transfer target gets asked for a voicemail
    # password instead of being connected.
    assert f'callerId="{restaurant.phone_number}"' in resp.text


async def test_transfer_webhook_hangs_up_when_call_was_not_transferred(
    client, db_session, restaurant
):
    from app.services import call_service

    await call_service.create_call(db_session, restaurant.id, "CA_transfer_2", "+1", _TWILIO_NUMBER)
    await db_session.commit()

    _use_test_telephony_provider(client)
    resp = _signed_post(client, "/webhooks/twilio/transfer/CA_transfer_2", {})

    assert resp.status_code == 200
    assert "<Dial>" not in resp.text
    assert "<Hangup" in resp.text


def test_transfer_webhook_rejects_invalid_signature(client):
    _use_test_telephony_provider(client)
    resp = _signed_post(client, "/webhooks/twilio/transfer/CA_x", {}, bad_signature=True)
    assert resp.status_code == 403
