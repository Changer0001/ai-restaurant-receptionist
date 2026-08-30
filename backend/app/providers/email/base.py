"""
Base Email Provider

Abstract interface for outbound email providers. SMTP is the only
implementation this project needs (see .env.example's SMTP_* settings),
but the abstraction still earns its keep the same way the other
providers do: a restaurant operator could plausibly want to route
notification email through a transactional provider (SES, SendGrid,
Postmark) instead of raw SMTP without anything above this interface
changing.
"""

from abc import ABC, abstractmethod


class EmailProvider(ABC):
    """Abstract base class for email providers."""

    @abstractmethod
    async def send_email(self, to: str, subject: str, body: str) -> None:
        """
        Send a plain-text email.

        Args:
            to: Recipient email address
            subject: Email subject line
            body: Plain-text email body

        Raises:
            Exception: on any failure to send — callers (the
                notification worker) are expected to catch this and
                record it rather than have it propagate, since a
                single bad address/SMTP outage must never crash the
                whole notification sweep.
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is reachable (e.g. SMTP handshake)."""
        pass
