"""Email sending provider.

Prefers HTTPS transactional APIs on cloud deploys, then Gmail API, then SMTP;
otherwise runs in "console" mode (logs the message) so flows still work.
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings

logger = logging.getLogger(__name__)


def _mime(subject: str, body: str, html: str | None) -> MIMEText | MIMEMultipart:
    """Plain text alone, or multipart/alternative when an HTML part is given
    (text first, HTML last - clients render the last part they support)."""
    if not html:
        msg: MIMEText | MIMEMultipart = MIMEText(body)
    else:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain"))
        msg.attach(MIMEText(html, "html"))
    msg["Subject"] = subject
    return msg


class EmailProvider:
    def _gmail_env_configured(self) -> bool:
        client_id = settings.gmail_send_client_id or settings.google_client_id
        client_secret = settings.gmail_send_client_secret or settings.google_client_secret
        return bool(client_id and client_secret and settings.gmail_send_refresh_token)

    @property
    def mode(self) -> str:
        # HTTPS APIs take precedence: cloud hosts like Render's free tier block
        # outbound SMTP ports, so deploys should send over 443 instead.
        if self._gmail_env_configured():
            return "gmail"
        if settings.resend_api_key:
            return "resend"
        if settings.brevo_api_key:
            return "brevo"
        if settings.gmail_token_file and settings.gmail_credentials_file:
            return "gmail"
        if settings.smtp_host and settings.smtp_username and settings.smtp_password:
            return "smtp"
        return "console"

    @property
    def available(self) -> bool:
        return self.mode in ("resend", "brevo", "gmail", "smtp")

    def send(self, to: str, subject: str, body: str, html: str | None = None) -> bool:
        mode = self.mode
        if mode == "resend":
            return self._send_resend(to, subject, body, html)
        if mode == "brevo":
            return self._send_brevo(to, subject, body, html)
        if mode == "gmail":
            return self._send_gmail(to, subject, body, html)
        if mode == "smtp":
            return self._send_smtp(to, subject, body, html)
        logger.info("[console-email] To:%s | %s\n%s", to, subject, body)
        return True

    def _sender(self) -> tuple[str, str]:
        """(name, email) for the From address, parsed from `smtp_from` (falling
        back to `smtp_username`). For Brevo the email must be a verified sender."""
        from email.utils import parseaddr

        name, addr = parseaddr(settings.smtp_from or "")
        return (name or "SynthSales", addr or settings.smtp_username)

    def _send_resend(self, to: str, subject: str, body: str, html: str | None = None) -> bool:
        """Send via Resend's HTTPS email API."""
        import httpx

        name, sender = self._sender()
        from_addr = f"{name} <{sender}>" if name else sender
        payload: dict = {
            "from": from_addr,
            "to": [to],
            "subject": subject,
            "text": body,
        }
        if html:
            payload["html"] = html
        try:
            resp = httpx.post(
                "https://api.resend.com/emails",
                headers={
                    "authorization": f"Bearer {settings.resend_api_key}",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=20,
            )
            if resp.status_code in (200, 201):
                logger.info("Resend email sent to %s (%s)", to, subject)
                return True
            logger.warning(
                "Resend send to %s failed: HTTP %s %s",
                to, resp.status_code, resp.text[:300],
            )
            return False
        except Exception as exc:
            logger.warning("Resend send to %s failed: %s", to, exc)
            return False

    def _send_brevo(self, to: str, subject: str, body: str, html: str | None = None) -> bool:
        """Send via Brevo's transactional email API over HTTPS (443) — the path
        that works on hosts which block outbound SMTP (e.g. Render's free tier)."""
        import httpx

        name, sender = self._sender()
        payload: dict = {
            "sender": {"email": sender, "name": name},
            "to": [{"email": to}],
            "subject": subject,
            "textContent": body,
        }
        if html:
            payload["htmlContent"] = html
        try:
            resp = httpx.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={
                    "api-key": settings.brevo_api_key,
                    "accept": "application/json",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=20,
            )
            if resp.status_code in (200, 201):
                logger.info("Brevo email sent to %s (%s)", to, subject)
                return True
            logger.warning(
                "Brevo send to %s failed: HTTP %s %s",
                to, resp.status_code, resp.text[:300],
            )
            return False
        except Exception as exc:
            logger.warning("Brevo send to %s failed: %s", to, exc)
            return False

    def _send_smtp(self, to: str, subject: str, body: str, html: str | None = None) -> bool:
        msg = _mime(subject, body, html)
        # A valid From is required; fall back to the authenticated user.
        msg["From"] = settings.smtp_from or settings.smtp_username
        msg["To"] = to
        try:
            # Port 465 → implicit SSL; otherwise STARTTLS (e.g. Gmail 587).
            if settings.smtp_port == 465:
                with smtplib.SMTP_SSL(settings.smtp_host, 465, timeout=20) as server:
                    server.login(settings.smtp_username, settings.smtp_password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    server.login(settings.smtp_username, settings.smtp_password)
                    server.send_message(msg)
            logger.info("SMTP email sent to %s (%s)", to, subject)
            return True
        except Exception as exc:
            logger.warning("SMTP send to %s failed: %s", to, exc)
            return False

    def _send_gmail(self, to: str, subject: str, body: str, html: str | None = None) -> bool:
        try:
            import base64

            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            client_id = settings.gmail_send_client_id or settings.google_client_id
            client_secret = settings.gmail_send_client_secret or settings.google_client_secret
            if settings.gmail_send_refresh_token and client_id and client_secret:
                creds = Credentials(
                    token=None,
                    refresh_token=settings.gmail_send_refresh_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=client_id,
                    client_secret=client_secret,
                    scopes=["https://www.googleapis.com/auth/gmail.send"],
                )
            else:
                creds = Credentials.from_authorized_user_file(settings.gmail_token_file)
            service = build("gmail", "v1", credentials=creds)
            msg = _mime(subject, body, html)
            msg["From"] = settings.smtp_from or settings.smtp_username
            msg["To"] = to
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            service.users().messages().send(userId="me", body={"raw": raw}).execute()
            return True
        except Exception as exc:  # pragma: no cover
            logger.warning("Gmail send failed: %s", exc)
            return False


email_provider = EmailProvider()
