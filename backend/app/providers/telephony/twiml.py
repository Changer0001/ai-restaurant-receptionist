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


def build_transfer_or_hangup_twiml(
    transfer_number: str | None, caller_id: str | None = None
) -> str:
    """
    TwiML for after the media stream ends: dial the restaurant's
    transfer number if one was requested and configured, else hang up.

    caller_id should be the restaurant's own number. Without it, Twilio
    puts the *caller's* number on the outbound leg, which is wrong in two
    ways: whoever picks up sees the customer's number rather than the
    restaurant's, and — hit live during testing — if the caller and the
    transfer target are the same phone (someone calling their own
    restaurant line to test it), the carrier sees a call from your number
    to your number, routes it to your mailbox, and asks the *customer*
    for the voicemail password. Dialing as the restaurant avoids that
    whole class of self-call weirdness.
    """
    response = VoiceResponse()
    if transfer_number:
        response.dial(
            transfer_number,
            # Falls back to Twilio's default (the inbound caller's
            # number) when the restaurant has no number on file.
            caller_id=caller_id or None,
            # Twilio's default is 30s of ringing with the customer
            # hearing nothing. 20 gets them back to a hangup sooner when
            # nobody picks up.
            timeout=20,
            # The customer hears real ringing instead of dead air while
            # the restaurant's phone rings.
            answer_on_bridge=True,
        )
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
