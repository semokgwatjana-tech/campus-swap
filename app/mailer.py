"""
Outgoing email.

Two providers are supported, both usable on a free PythonAnywhere account
(which blocks arbitrary SMTP servers but allows Gmail SMTP and HTTPS APIs):

  MAIL_PROVIDER=smtp      Gmail (or any SMTP server on a paid plan).
                          Needs MAIL_SMTP_USER and MAIL_SMTP_PASSWORD
                          (a Gmail "app password", never the normal password).
  MAIL_PROVIDER=sendgrid  SendGrid HTTPS API. Needs SENDGRID_API_KEY and a
                          verified sender in MAIL_FROM.

Only the standard library is used, so there is nothing extra to install.
send_email() never raises: a failed email must not break the page the
person is on. It returns True when the provider accepted the message.
"""

import json
import smtplib
import urllib.request
from email.message import EmailMessage

from flask import current_app


def mail_is_configured():
    cfg = current_app.config
    provider = cfg.get("MAIL_PROVIDER")
    if provider == "smtp":
        return bool(cfg.get("MAIL_SMTP_USER") and cfg.get("MAIL_SMTP_PASSWORD"))
    if provider == "sendgrid":
        return bool(cfg.get("SENDGRID_API_KEY") and cfg.get("MAIL_FROM"))
    return False


def send_email(to_address, subject, body):
    """Send a plain-text email. Returns True on success, False otherwise."""
    if not mail_is_configured():
        return False

    cfg = current_app.config
    sender = cfg.get("MAIL_FROM") or cfg.get("MAIL_SMTP_USER")

    try:
        if cfg["MAIL_PROVIDER"] == "smtp":
            message = EmailMessage()
            message["From"] = sender
            message["To"] = to_address
            message["Subject"] = subject
            message.set_content(body)
            with smtplib.SMTP(cfg["MAIL_SMTP_HOST"], cfg["MAIL_SMTP_PORT"], timeout=15) as server:
                server.starttls()
                server.login(cfg["MAIL_SMTP_USER"], cfg["MAIL_SMTP_PASSWORD"])
                server.send_message(message)
            return True

        if cfg["MAIL_PROVIDER"] == "sendgrid":
            payload = {
                "personalizations": [{"to": [{"email": to_address}]}],
                "from": {"email": sender},
                "subject": subject,
                "content": [{"type": "text/plain", "value": body}],
            }
            request = urllib.request.Request(
                "https://api.sendgrid.com/v3/mail/send",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {cfg['SENDGRID_API_KEY']}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                return 200 <= response.status < 300
    except Exception as exc:  # noqa: BLE001 - email must never crash a request
        current_app.logger.error("Email to %s failed: %s", to_address, exc)
        return False

    return False
