"""
SMTP Email Provider

Sends real email over SMTP using aiosmtplib (a genuinely async SMTP
client — not smtplib wrapped in a thread), configured from the
SMTP_* settings (see .env.example). Works against any standard SMTP
server: a real provider (Gmail, SES SMTP, SendGrid SMTP relay) in
production, or a local dev SMTP catcher (e.g. MailHog/Mailpit) with
SMTP_USERNAME/SMTP_PASSWORD left blank.
"""

import logging
from email.headerregistry import Address
from email.message import EmailMessage

import aiosmtplib

from app.core.config import settings
from app.providers.email.base import EmailProvider

logger = logging.getLogger(__name__)

# Port 465 is "implicit TLS" (the connection is TLS from the first byte);
# every other port (587, the default; 25) is expected to speak plaintext
# then upgrade via STARTTLS, which is what SMTP_PORT defaults to here.
_IMPLICIT_TLS_PORT = 465


class SMTPEmailProvider(EmailProvider):
    def __init__(
        self,
        host: str = settings.SMTP_HOST,
        port: int = settings.SMTP_PORT,
        username: str = settings.SMTP_USERNAME,
        password: str = settings.SMTP_PASSWORD,
        from_email: str = settings.SMTP_FROM_EMAIL,
        from_name: str = settings.SMTP_FROM_NAME,
    ):
        self.host = host
        self.port = port
        self.username = username or None
        self.password = password or None
        self.from_email = from_email
        self.from_name = from_name

    def _build_message(self, to: str, subject: str, body: str) -> EmailMessage:
        message = EmailMessage()
        message["From"] = Address(display_name=self.from_name, addr_spec=self.from_email)
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        return message

    async def send_email(self, to: str, subject: str, body: str) -> None:
        message = self._build_message(to, subject, body)
        use_tls = self.port == _IMPLICIT_TLS_PORT
        await aiosmtplib.send(
            message,
            hostname=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            use_tls=use_tls,
            start_tls=None if use_tls else True,
        )
        logger.info(f"Sent email to {to!r} (subject={subject!r})")

    async def health_check(self) -> bool:
        """Connect and immediately disconnect — proves the SMTP server
        is reachable and (if credentials are configured) that auth
        succeeds, without sending a message. connect() logs in
        automatically when username/password are set, so a bad
        credential surfaces here as a connect() failure."""
        use_tls = self.port == _IMPLICIT_TLS_PORT
        client = aiosmtplib.SMTP(
            hostname=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            use_tls=use_tls,
            start_tls=None if use_tls else True,
        )
        try:
            await client.connect()
            return True
        except Exception as e:
            logger.error(f"SMTP health check failed: {e}")
            return False
        finally:
            try:
                await client.quit()
            except Exception:
                pass  # already disconnected — nothing to clean up
