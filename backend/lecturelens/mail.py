"""Outgoing email. Without SMTP configured, messages go to the log so local dev
and tests never need a mail server."""

import logging
import smtplib
from email.message import EmailMessage
from urllib.parse import unquote, urlparse

from .config import get_settings

log = logging.getLogger(__name__)

# tests read sent mail from here
outbox: list[EmailMessage] = []


def send(to: str, subject: str, body: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = s.mail_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    outbox.append(msg)
    del outbox[:-50]
    if not s.smtp_url:
        # print, not log: uvicorn doesn't show app loggers, and in local dev this is
        # the only way to get a sign-in link
        print(f"--- email to {to}: {subject}\n{body}\n---", flush=True)
        log.info("email to %s: %s", to, subject)
        return
    url = urlparse(s.smtp_url)
    with smtplib.SMTP(url.hostname, url.port or 587, timeout=10) as smtp:
        smtp.starttls()
        if url.username:
            smtp.login(unquote(url.username), unquote(url.password or ""))
        smtp.send_message(msg)
