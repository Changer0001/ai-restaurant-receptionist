"""
Base Telephony Provider

Abstract interface for telephony providers.
Abstracts away provider-specific details (Twilio, SIP, etc.)
"""

from abc import ABC, abstractmethod
from typing import Any, Dict


class TelephonyProvider(ABC):
    """
    Abstract base class for telephony providers.

    Supports multiple providers (Twilio, SIP, FreeSWITCH, Asterisk, etc.)
    with a unified interface.
    """

    @abstractmethod
    async def validate_webhook_signature(
        self,
        signature: str,
        request_body: str,
    ) -> bool:
        """
        Validate webhook signature for security.

        Args:
            signature: Signature header from provider
            request_body: Raw request body

        Returns:
            True if signature is valid
        """
        pass

    @abstractmethod
    async def transfer_call(
        self,
        call_sid: str,
        target_number: str,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        Transfer an active call to another number.

        Args:
            call_sid: Call SID/ID
            target_number: Number to transfer to
            timeout: Timeout in seconds

        Returns:
            Transfer result details
        """
        pass

    @abstractmethod
    async def end_call(self, call_sid: str) -> bool:
        """End an active call."""
        pass

    @abstractmethod
    async def send_digits(self, call_sid: str, digits: str) -> bool:
        """Send DTMF digits to an active call."""
        pass

    @abstractmethod
    async def record_call(self, call_sid: str) -> str:
        """Start recording a call."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the telephony provider is accessible."""
        pass
