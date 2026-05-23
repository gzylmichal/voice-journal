"""
Email sender — SMTP.

Sends plaintext email via SMTP. Supports both STARTTLS (port 587) and
implicit TLS (port 465). Configure via .env:
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM, EMAIL_TO.

IMPORTANT — sending from an alias:
  If EMAIL_FROM is an alias (e.g. debrief@domain.com) different from
  SMTP_USER (e.g. michal@domain.com), the envelope sender is set to
  SMTP_USER (the authenticated identity), while the visible From: header
  is EMAIL_FROM (the alias). This is required by Zoho, Gmail and most
  modern SMTP providers — they reject sends where envelope sender doesn't
  match the authenticated user.
"""

import logging
import smtplib
import ssl
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid

logger = logging.getLogger("debrief.sender")


def send_email(cfg: dict, subject: str, body: str,
               content_subtype: str = "plain") -> None:
    """Send an email via SMTP with one retry on transient failures.

    content_subtype: 'plain' for plaintext, 'html' for HTML email.
    """

    host = cfg["smtp_host"]
    port = int(cfg["smtp_port"])
    user = cfg["smtp_user"]
    password = cfg["smtp_password"]
    email_from = cfg["email_from"]
    email_to = cfg["email_to"]

    if not all([host, user, password, email_from, email_to]):
        raise ValueError(
            "Email not configured. Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD, "
            "EMAIL_FROM, EMAIL_TO in .env"
        )

    # Build the message
    msg = MIMEMultipart()
    msg["From"] = email_from                   # what the recipient sees
    msg["To"] = email_to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)   # RFC 2822 format with tz
    msg["Message-ID"] = make_msgid(domain=email_from.split("@")[-1])
    msg.attach(MIMEText(body, content_subtype, "utf-8"))

    # Envelope sender MUST match the authenticated user, not the alias.
    # The From: header can still show the alias (that's what the user sees).
    envelope_from = user
    envelope_to = [addr.strip() for addr in email_to.split(",") if addr.strip()]

    last_exc: Exception | None = None
    for attempt in (1, 2):
        try:
            _send_once(host, port, user, password, envelope_from, envelope_to, msg)
            logger.info("Email sent to %s (attempt %d)", email_to, attempt)
            return
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError,
                TimeoutError, ConnectionError) as exc:
            last_exc = exc
            logger.warning("SMTP transient failure (attempt %d/2): %s", attempt, exc)
            if attempt == 1:
                time.sleep(5)
        except smtplib.SMTPAuthenticationError as exc:
            # No point retrying auth failures
            raise RuntimeError(
                f"SMTP auth failed ({exc.smtp_code}). Common causes: "
                "(1) using main password instead of app-specific password, "
                "(2) wrong region host (smtp.zoho.eu vs smtp.zoho.com), "
                "(3) paid plan needs smtppro.zoho.eu instead of smtp.zoho.eu."
            ) from exc
        except smtplib.SMTPSenderRefused as exc:
            raise RuntimeError(
                f"SMTP rejected sender {envelope_from}: {exc.smtp_error!r}. "
                "If EMAIL_FROM is an alias, make sure SMTP_USER is the main "
                "account that owns the alias."
            ) from exc

    raise RuntimeError(f"SMTP send failed after 2 attempts: {last_exc}")


def _send_once(host: str, port: int, user: str, password: str,
               envelope_from: str, envelope_to: list[str], msg) -> None:
    """Single send attempt. Chooses SSL vs STARTTLS based on port."""
    context = ssl.create_default_context()

    if port == 465:
        # Implicit TLS from connection start
        with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as server:
            server.login(user, password)
            server.sendmail(envelope_from, envelope_to, msg.as_string())
    else:
        # STARTTLS upgrade (port 587 is standard)
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(user, password)
            server.sendmail(envelope_from, envelope_to, msg.as_string())
