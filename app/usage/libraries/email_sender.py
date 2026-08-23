from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from usage.constants.constants import Constants
from usage.libraries.email_texts import EmailTexts
from usage.structures.settings import Settings


class EmailSender:
    """Sends plain-text emails through the configured SMTP relay (Amazon SES)."""

    def __init__(self, settings: Settings) -> None:
        self._host = settings.smtp_host
        self._port = settings.smtp_port
        self._username = settings.smtp_username
        self._password = settings.smtp_password
        self._sender = settings.smtp_sender

    def is_configured(self) -> bool:
        return bool(self._host and self._username and self._password and self._sender)

    def send(self, recipient: str, subject: str, body_lines: list[str]) -> bool:
        if not self.is_configured():
            return False
        if self._is_test_recipient(recipient):
            # RFC 2606 reserves these domains for tests and documentation:
            # handing them to the relay only produces bounces.
            logging.getLogger("usage").info("[EMAIL] suppressed test recipient %s", recipient)
            return False
        message = EmailMessage()
        message["From"] = f"{Constants.app_name} <{self._sender}>"
        message["To"] = recipient
        message["Subject"] = subject
        message["Reply-To"] = Constants.contact_email
        message["List-Unsubscribe"] = f"<mailto:{Constants.contact_email}?subject=unsubscribe>"
        message.set_content("\n".join(body_lines + EmailTexts.footer(Constants.contact_email)))
        try:
            if self._port == 465:
                with smtplib.SMTP_SSL(self._host, self._port, timeout=20) as smtp:
                    smtp.login(self._username, self._password)
                    smtp.send_message(message)
            else:
                with smtplib.SMTP(self._host, self._port, timeout=20) as smtp:
                    smtp.starttls()
                    smtp.login(self._username, self._password)
                    smtp.send_message(message)
        except (smtplib.SMTPException, OSError) as exception:
            logging.getLogger("usage").warning("[EMAIL] send failed to %s: %s", recipient, exception)
            return False
        return True

    def _is_test_recipient(self, recipient: str) -> bool:
        normalized = recipient.strip().lower()
        return any(normalized.endswith(suffix) for suffix in Constants.email_test_suffixes)
