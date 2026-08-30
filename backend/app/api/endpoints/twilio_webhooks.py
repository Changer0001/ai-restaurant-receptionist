"""
Twilio Webhooks

POST /webhooks/twilio/voice       - incoming call -> restaurant lookup -> TwiML
POST /webhooks/twilio/status      - call status changes (finalization backstop)
POST /webhooks/twilio/recording   - recording-complete callback (stores the URL)
POST /webhooks/twilio/transfer/{call_sid} - post-stream fallback: dial or hang up
WS   /webhooks/twilio/media-stream/{call_sid} - the live bidirectional audio session

Every POST endpoint validates X-Twilio-Signature before doing anything
else — an unvalidated request here could create fake Call records,
trigger a transfer to an arbitrary number, or (worst case) get treated
as if it were a real caller. None of these are protected by the
JWT/tenant-isolation dependencies used elsewhere in this API (a caller
has no account), so signature validation IS the entire authorization
boundary for this router.
"""

import base64
import logging

from fastapi import APIRouter, Depends, Request, Response, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import twilio_signature_failures_total
from app.db.session import get_db_session
from app.providers.embedding import get_embedding_provider
from app.providers.embedding.base import EmbeddingProvider
from app.providers.llm import get_llm_provider
from app.providers.llm.base import LLMProvider
from app.providers.stt import get_stt_provider
from app.providers.stt.base import STTProvider
from app.providers.telephony.twilio_provider import TwilioTelephonyProvider
from app.providers.telephony.twiml import (
    build_media_stream_twiml,
    build_rejection_twiml,
    build_transfer_or_hangup_twiml,
)
from app.providers.tts import get_tts_provider
from app.providers.tts.base import TTSProvider
from app.rag.vector_db import VectorDB, get_vector_db
from app.services import call_service, restaurant_service
from app.voice.session import CallSession

logger = logging.getLogger(__name__)

router = APIRouter()

_XML_MEDIA_TYPE = "application/xml"


def _get_telephony_provider() -> TwilioTelephonyProvider:
    return TwilioTelephonyProvider()


async def _validated_form(
    request: Request, telephony: TwilioTelephonyProvider
) -> dict[str, str] | None:
    """
    Parse a Twilio webhook's form body and validate its signature.
    Returns the params dict if valid, None if the signature check fails
    (already logged) — callers should respond with a rejection, not a
    500, since an unsigned/forged request is an expected occurrence on
    a public endpoint, not a server error.
    """
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    signature = request.headers.get("X-Twilio-Signature", "")

    # str(request.url) is only trustworthy here because uvicorn is run
    # with --proxy-headers (see docker-compose.yml) — it reports the
    # https:// URL Nginx terminated and Twilio actually signed against,
    # not uvicorn's own plain-http connection to Nginx.
    url = str(request.url)

    # TEMPORARY debug logging — remove once signature validation is
    # confirmed working. Never logs the actual auth token, only its
    # length (a real Twilio auth token is 32 hex characters).
    logger.warning(
        f"DEBUG signature check: url={url!r} sig_header={signature!r} "
        f"auth_token_len={len(telephony.auth_token)}"
    )

    if not await telephony.validate_webhook_signature(signature, url, params):
        twilio_signature_failures_total.inc()
        logger.warning(f"Rejected Twilio webhook with invalid signature: {url}")
        return None

    return params


@router.post("/voice")
async def voice_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    telephony: TwilioTelephonyProvider = Depends(_get_telephony_provider),
):
    params = await _validated_form(request, telephony)
    if params is None:
        return Response(
            content=build_rejection_twiml("Sorry, this request could not be verified."),
            media_type=_XML_MEDIA_TYPE,
            status_code=403,
        )

    call_sid = params.get("CallSid", "")
    caller_number = params.get("From", "")
    called_number = params.get("To", "")

    restaurant = await restaurant_service.get_restaurant_by_phone_number(db, called_number)
    if restaurant is None:
        logger.warning(f"No restaurant mapped to Twilio number {called_number!r} (call {call_sid})")
        # 200, not an error status: from Twilio's perspective this is a
        # valid, complete response (a spoken message, then hang up) —
        # the "no route" outcome is ours to handle gracefully, not a
        # webhook failure Twilio should retry.
        return Response(
            content=build_rejection_twiml("Sorry, this number is not currently in service."),
            media_type=_XML_MEDIA_TYPE,
        )

    await call_service.create_call(db, restaurant.id, call_sid, caller_number, called_number)
    await db.commit()

    return Response(content=build_media_stream_twiml(call_sid), media_type=_XML_MEDIA_TYPE)


@router.post("/status")
async def status_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    telephony: TwilioTelephonyProvider = Depends(_get_telephony_provider),
):
    params = await _validated_form(request, telephony)
    if params is None:
        return Response(status_code=403)

    call_sid = params.get("CallSid", "")
    call_status = params.get("CallStatus", "")

    await call_service.ensure_call_finalized_from_status(db, call_sid, call_status)
    await db.commit()

    return Response(status_code=204)


@router.post("/recording")
async def recording_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    telephony: TwilioTelephonyProvider = Depends(_get_telephony_provider),
):
    """
    Twilio's recording-complete callback. Only relevant when call
    recording is actually requested for a call (FEATURE_CALL_RECORDING /
    CALL_RECORDING_ENABLED) — this project does not itself request
    recording anywhere yet (Phase 5 doesn't start one), so this endpoint
    exists for when that's wired up, matching the API surface Twilio
    expects to be able to call.
    """
    params = await _validated_form(request, telephony)
    if params is None:
        return Response(status_code=403)

    call_sid = params.get("CallSid", "")
    recording_url = params.get("RecordingUrl", "")

    call = await call_service.get_call_by_sid(db, call_sid)
    if call is not None and recording_url:
        call.recording_path = recording_url
        await db.commit()

    return Response(status_code=204)


@router.post("/transfer/{call_sid}")
async def transfer_webhook(
    call_sid: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    telephony: TwilioTelephonyProvider = Depends(_get_telephony_provider),
):
    """
    Where the original TwiML <Redirect>s once the media stream ends.
    Dials the restaurant's transfer number if the call needs a human
    handoff, otherwise hangs up — decided by what the Call row's
    was_transferred flag says happened during the conversation.
    """
    params = await _validated_form(request, telephony)
    if params is None:
        return Response(
            content=build_rejection_twiml("Sorry, this request could not be verified."),
            media_type=_XML_MEDIA_TYPE,
            status_code=403,
        )

    call = await call_service.get_call_by_sid(db, call_sid)
    transfer_number = None
    if call is not None and call.was_transferred:
        restaurant = await restaurant_service.get_restaurant_or_404(db, call.restaurant_id)
        transfer_number = restaurant.transfer_number

    return Response(
        content=build_transfer_or_hangup_twiml(transfer_number), media_type=_XML_MEDIA_TYPE
    )


async def _handle_stream_event(
    session: CallSession, db: AsyncSession, message: dict, stream_sid_ref: list
) -> bool:
    """Process one Media Streams protocol message. Returns True if the caller loop should stop."""
    event = message.get("event")

    if event == "start":
        stream_sid_ref[0] = message["start"]["streamSid"]
        await session.start()
        await db.commit()
        return False

    if event == "media":
        await session.handle_media(message["media"]["payload"])
        await db.commit()
        return session.should_close

    return event == "stop"


@router.websocket("/media-stream/{call_sid}")
async def media_stream(
    websocket: WebSocket,
    call_sid: str,
    db: AsyncSession = Depends(get_db_session),
    llm: LLMProvider = Depends(get_llm_provider),
    stt: STTProvider = Depends(get_stt_provider),
    tts: TTSProvider = Depends(get_tts_provider),
    embedder: EmbeddingProvider = Depends(get_embedding_provider),
    vector_db: VectorDB = Depends(get_vector_db),
):
    """
    The live call. Twilio opens this WebSocket per <Connect><Stream> and
    speaks its Media Streams protocol (JSON text frames: connected,
    start, media, stop) for the lifetime of the call.

    Note: this endpoint intentionally does not itself validate a Twilio
    signature — Media Streams WebSocket connections don't carry one (the
    signature scheme is HTTP-webhook-specific). The call_sid path segment
    was handed out by us, inside the TwiML returned from the
    already-validated /voice webhook, to a URL only Twilio's own platform
    calls next — there's no separate untrusted party that could discover
    and connect to this URL with a call_sid of their choosing before we
    issued it.
    """
    call = await call_service.get_call_by_sid(db, call_sid)
    if call is None:
        logger.warning(f"Media stream requested for unknown call_sid={call_sid}")
        await websocket.close(code=1008)
        return

    restaurant = await restaurant_service.get_restaurant_or_404(db, call.restaurant_id)

    await websocket.accept()

    # A single-item list, not a plain variable: send_audio's closure needs
    # to see stream_sid as set by the "start" event, which arrives (and is
    # assigned, inside _handle_stream_event) after send_audio is defined.
    stream_sid_ref: list[str | None] = [None]

    async def send_audio(mulaw_bytes: bytes) -> None:
        await websocket.send_json(
            {
                "event": "media",
                "streamSid": stream_sid_ref[0],
                "media": {"payload": base64.b64encode(mulaw_bytes).decode("ascii")},
            }
        )

    session = CallSession(db, call, restaurant, stt, tts, llm, embedder, vector_db, send_audio)

    try:
        while True:
            message = await websocket.receive_json()
            if await _handle_stream_event(session, db, message, stream_sid_ref):
                break

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception(f"Error in media stream for call {call_sid}")
    finally:
        await session.end()
        await db.commit()
        try:
            await websocket.close()
        except RuntimeError:
            pass  # already closed
