"""
Notification Worker

Standalone process that polls the `notifications` table and sends due
rows via the real SMS/email providers (app/providers/telephony,
app/providers/email) — see app/services/notification_service.py for
the actual send/retry/backoff logic this just loops on.

Runs out-of-process from the API server (see docker-compose.yml's
`worker` service) rather than inline during a live call: notification
delivery has nothing to do with a phone call's latency budget, and a
slow or down SMTP server / Twilio outage must never add delay to what
a caller hears.

    python -m app.worker
"""

import asyncio
import logging

from app.core.config import settings
from app.db.session import async_session_maker
from app.providers.email import get_email_provider
from app.providers.telephony.twilio_provider import TwilioTelephonyProvider
from app.services.notification_service import process_pending_notifications

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_once() -> int:
    """Process one batch of due notifications. Returns how many sends
    were attempted (success or failure)."""
    telephony = TwilioTelephonyProvider()
    email_provider = await get_email_provider()
    async with async_session_maker() as db:
        count = await process_pending_notifications(db, telephony, email_provider)
        await db.commit()
        return count


async def main() -> None:
    logger.info(
        "Notification worker starting "
        f"(poll interval={settings.NOTIFICATION_POLL_INTERVAL_SECONDS}s)"
    )
    while True:
        try:
            attempted = await run_once()
            if attempted:
                logger.info(f"Processed {attempted} due notification(s)")
        except Exception:
            # A single bad iteration (e.g. a transient DB connection
            # blip) must not kill the whole worker process — log it and
            # try again next poll rather than exiting and silently
            # stopping all notification delivery until someone notices
            # the container died.
            logger.exception("Notification worker iteration failed")
        await asyncio.sleep(settings.NOTIFICATION_POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
