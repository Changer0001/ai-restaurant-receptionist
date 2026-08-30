"""
TwiML Generation

Uses Twilio's own SDK to build response markup (twilio.twiml.voice_response)
rather than hand-building XML strings — that SDK handles attribute
escaping correctly, which matters here since restaurant.transfer_number
and generated URLs both end up in TwiML attributes.
"""

from twilio.twiml.voice_response import Connect, VoiceResponse

from app.core.config import settings


def build_media_stream_twiml(call_id: str) -> str:
    """
    TwiML for a fresh inbound call: open a bidirectional Media Stream to
    our WebSocket for the live conversation, then — once that stream
    ends (call transferred or conversation concluded) — redirect to the
    transfer endpoint, which decides whether to <Dial> or <Hangup/>
    based on what happened during the call (see call_service.py).

    <Connect><Stream> (not <Start><Stream>) is required for bidirectional
    audio — <Start><Stream> is inbound-only and can't play synthesized
    speech back to the caller.
    """
    response = VoiceResponse()

    connect = Connect()
    ws_scheme = "wss" if settings.PUBLIC_BASE_URL.startswith("https") else "ws"
    ws_host = settings.PUBLIC_BASE_URL.split("://", 1)[-1]
    connect.stream(url=f"{ws_scheme}://{ws_host}/webhooks/twilio/media-stream/{call_id}")
    response.append(connect)

    response.redirect(f"{settings.PUBLIC_BASE_URL}/webhooks/twilio/transfer/{call_id}")

    return str(response)


def build_transfer_or_hangup_twiml(transfer_number: str | None) -> str:
    """TwiML for after the media stream ends: dial the restaurant's
    transfer number if one was requested and configured, else hang up."""
    response = VoiceResponse()
    if transfer_number:
        response.dial(transfer_number)
    else:
        response.hangup()
    return str(response)


def build_rejection_twiml(message: str) -> str:
    """
    TwiML for a call we can't route at all (unknown number, invalid
    signature) — say something brief and hang up rather than silently
    dropping the call or leaving it hanging.

    Uses Twilio's own <Say> (their cloud TTS), not the local Kokoro/Piper
    pipeline — deliberately, and only here: this path means the call
    never reached the point of having a restaurant, a conversation
    engine, or anything else to run locally in the first place (an
    unrecognized number, or a request that failed signature validation
    and so isn't trusted as being from Twilio at all). Standing up the
    full local TTS pipeline for one static safety-net sentence on a path
    that by definition has no restaurant context isn't local inference
    being skipped, there's nothing local to run.
    """
    response = VoiceResponse()
    response.say(message)
    response.hangup()
    return str(response)
