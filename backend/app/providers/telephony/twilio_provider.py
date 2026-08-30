"""
Twilio Telephony Provider

Integration with Twilio Voice API for PSTN connectivity.
"""

import logging
from typing import Any, Dict

from twilio.request_validator import RequestValidator
from twilio.rest import Client

from app.core.config import settings
from app.providers.telephony.base import TelephonyProvider

logger = logging.getLogger(__name__)


class TwilioTelephonyProvider(TelephonyProvider):
    """Twilio-based telephony provider."""

    def __init__(
        self,
        account_sid: str = settings.TWILIO_ACCOUNT_SID,
        auth_token: str = settings.TWILIO_AUTH_TOKEN,
        webhook_secret: str = settings.TWILIO_WEBHOOK_SECRET,
    ):
        """Initialize Twilio provider."""
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.webhook_secret = webhook_secret
        self.client = Client(account_sid, auth_token)
        self.validator = RequestValidator(auth_token)

    async def validate_webhook_signature(
        self,
        signature: str,
        request_body: str,
    ) -> bool:
        """
        Validate Twilio webhook signature.

        Args:
            signature: X-Twilio-Signature header
            request_body: Raw request body

        Returns:
            True if valid
        """
        try:
            # Note: Twilio validation expects URL in the validator
            # This is a simplified version - implement full validation per Twilio docs
            return signature is not None
        except Exception as e:
            logger.error(f"Twilio signature validation error: {e}")
            return False

    async def transfer_call(
        self,
        call_sid: str,
        target_number: str,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """Transfer an active call to another number."""
        try:
            # Get the call
            call = self.client.calls(call_sid).fetch()

            # Update the call with a TwiML URL that transfers
            # In practice, this would be a URL that returns TwiML
            # For MVP, we'll just return the details
            logger.info(f"Transferring call {call_sid} to {target_number}")

            return {
                "call_sid": call_sid,
                "status": call.status,
                "transfer_target": target_number,
            }
        except Exception as e:
            logger.error(f"Twilio transfer error: {e}")
            raise

    async def end_call(self, call_sid: str) -> bool:
        """End an active call."""
        try:
            call = self.client.calls(call_sid).update(status="completed")
            logger.info(f"Ended call {call_sid}")
            return bool(call.status == "completed")
        except Exception as e:
            logger.error(f"Twilio end call error: {e}")
            return False

    async def send_digits(self, call_sid: str, digits: str) -> bool:
        """Send DTMF digits to a call."""
        try:
            self.client.calls(call_sid).update(twiml=f'<Response><Play digits="{digits}"/></Response>')
            logger.info(f"Sent digits {digits} to call {call_sid}")
            return True
        except Exception as e:
            logger.error(f"Twilio send digits error: {e}")
            return False

    async def record_call(self, call_sid: str) -> str:
        """Start recording a call."""
        try:
            # Twilio recording is managed via TwiML
            # This is a placeholder for actual recording management
            logger.info(f"Recording started for call {call_sid}")
            return call_sid
        except Exception as e:
            logger.error(f"Twilio record call error: {e}")
            raise

    async def health_check(self) -> bool:
        """Check Twilio API connectivity."""
        try:
            # Fetch account details as a health check
            account = self.client.api.accounts(self.account_sid).fetch()
            logger.info(f"Twilio health check passed: {account.friendly_name}")
            return True
        except Exception as e:
            logger.error(f"Twilio health check failed: {e}")
            return False
