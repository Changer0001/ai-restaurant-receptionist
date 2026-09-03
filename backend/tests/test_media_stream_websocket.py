"""
Full end-to-end test of the Twilio Media Streams WebSocket
(/webhooks/twilio/media-stream/{call_sid}): connect, start, media (real
μ-law-encoded audio, enough to trip the turn detector), stop — verifying
audio comes back over the wire and the Call record is correctly
finalized in the database afterward.

This is the closest thing in this test suite to actually placing a call
through the whole voice pipeline (everything except real Twilio, a real
phone, and real models — those are provided by fakes/scripts, same as
every other phase's tests).
"""

import asyncio
import base64

import numpy as np

from app.api.endpoints.twilio_webhooks import _get_telephony_provider
from app.audio.codec import pcm16_to_mulaw
from app.db.models import Call, CallOutcomeEnum, RestaurantPhoneNumber
from app.main import app
from app.providers.embedding import get_embedding_provider
from app.providers.llm import get_classifier_llm_provider, get_llm_provider
from app.providers.stt import get_stt_provider
from app.providers.tts import get_tts_provider
from app.rag.vector_db import get_vector_db
from tests.fakes import FakeTTSProvider, ScriptedLLMProvider, ScriptedSTTProvider, contains
from tests.test_voice_webhooks import _sign, _test_telephony_provider

_TWILIO_NUMBER = "+15559876543"


def _speech_mulaw_frame() -> str:
    t = np.linspace(0, 0.02, 160, endpoint=False)
    pcm = (np.sin(2 * np.pi * 300 * t) * 5000).astype(np.int16)
    return base64.b64encode(pcm16_to_mulaw(pcm)).decode("ascii")


def _silence_mulaw_frame() -> str:
    return base64.b64encode(pcm16_to_mulaw(np.zeros(160, dtype=np.int16))).decode("ascii")


async def _create_call_via_voice_webhook(client, db_session, restaurant) -> str:
    # A short greeting keeps the synthesized playback window (and hence
    # CallSession's no-barge-in "still speaking" gate, which is driven by
    # real wall-clock time) small enough that the test's own frame-sending
    # loop below can clear it with a short, deterministic sleep rather
    # than a multi-second one.
    restaurant.ai_greeting = "Hi!"
    db_session.add(
        RestaurantPhoneNumber(
            restaurant_id=restaurant.id, phone_number=_TWILIO_NUMBER, is_active=True
        )
    )
    await db_session.commit()

    app.dependency_overrides[_get_telephony_provider] = _test_telephony_provider
    params = {"CallSid": "CA_ws_test", "From": "+15551110000", "To": _TWILIO_NUMBER}
    url = "http://testserver/webhooks/twilio/voice"
    resp = client.post(
        "/webhooks/twilio/voice", data=params, headers={"X-Twilio-Signature": _sign(url, params)}
    )
    assert resp.status_code == 200
    return "CA_ws_test"


def _override_ai_providers(llm, stt, tts, embedding_provider, vector_db):
    app.dependency_overrides[get_llm_provider] = lambda: llm
    # The engine classifies with its own provider, which defaults to a
    # real one — without this the test reaches for a live LLM.
    app.dependency_overrides[get_classifier_llm_provider] = lambda: llm
    app.dependency_overrides[get_stt_provider] = lambda: stt
    app.dependency_overrides[get_tts_provider] = lambda: tts
    app.dependency_overrides[get_embedding_provider] = lambda: embedding_provider
    app.dependency_overrides[get_vector_db] = lambda: vector_db


async def test_full_call_over_websocket_faq_question(
    client, db_session, restaurant, vector_db, embedding_provider
):
    call_sid = await _create_call_via_voice_webhook(client, db_session, restaurant)

    llm = ScriptedLLMProvider(
        [
            (contains("decide if it needs to be handed off"), "NO"),
            (contains("Respond with exactly one of these labels"), "FAQ"),
            (contains("using ONLY the information below"), "SHOULD_NOT_BE_CALLED"),
        ]
    )
    stt = ScriptedSTTProvider([("What time do you close tonight?", 0.9)])
    tts = FakeTTSProvider()
    _override_ai_providers(llm, stt, tts, embedding_provider, vector_db)

    with client.websocket_connect(f"/webhooks/twilio/media-stream/{call_sid}") as ws:
        ws.send_json({"event": "connected", "protocol": "Call", "version": "1.0"})

        ws.send_json({"event": "start", "start": {"streamSid": "MZ123", "callSid": call_sid}})
        greeting_audio = ws.receive_json()
        assert greeting_audio["event"] == "media"
        assert greeting_audio["streamSid"] == "MZ123"
        assert len(greeting_audio["media"]["payload"]) > 0

        # CallSession has no barge-in support: it ignores inbound audio
        # until its estimated greeting-playback window (real wall-clock
        # time, computed from the synthesized audio's own duration) has
        # elapsed. Twilio would naturally take this long to stream the
        # frames below in a real call; here we simulate that elapsed time
        # with a short sleep instead, since the frames are sent back-to-
        # back with no pacing of their own.
        await asyncio.sleep(0.5)

        # Speech, then enough silence to trip the turn detector's default
        # hangover window.
        for _ in range(10):
            ws.send_json({"event": "media", "media": {"payload": _speech_mulaw_frame()}})
        for _ in range(40):  # 40 * 20ms = 800ms > default 700ms hangover
            ws.send_json({"event": "media", "media": {"payload": _silence_mulaw_frame()}})

        response_audio = ws.receive_json()
        assert response_audio["event"] == "media"

        ws.send_json({"event": "stop"})

    from sqlalchemy import select

    result = await db_session.execute(select(Call).where(Call.call_sid == call_sid))
    call = result.scalar_one()
    assert call.outcome == CallOutcomeEnum.FAQ_ANSWERED
    assert call.end_time is not None
    assert "caller: What time do you close tonight?" in (call.transcript or "")


def test_websocket_rejects_unknown_call_sid(client):
    # No AI provider overrides needed: the handler closes the connection
    # before a CallSession (which would need them) is ever constructed.
    # The server never accepts the connection at all for an unrecognized
    # call_sid, so the disconnect surfaces at connect time, not on the
    # first receive.
    import pytest
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/webhooks/twilio/media-stream/CA_never_created"):
            pass
