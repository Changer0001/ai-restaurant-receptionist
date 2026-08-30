"""Email Provider Package"""

import logging
from typing import Optional

from app.providers.email.base import EmailProvider

logger = logging.getLogger(__name__)

__all__ = ["EmailProvider", "get_email_provider"]

_email_provider: Optional[EmailProvider] = None


async def get_email_provider() -> EmailProvider:
    """
    Get the (lazily-initialized, process-wide) email provider. A FastAPI
    dependency — override with `app.dependency_overrides` in tests.
    """
    global _email_provider
    if _email_provider is None:
        from app.providers.email.smtp_provider import SMTPEmailProvider

        _email_provider = SMTPEmailProvider()
        logger.info("Email provider initialized: smtp")
    return _email_provider
