import os
from pathlib import Path
from typing import Optional
from jinja2 import Environment, FileSystemLoader, select_autoescape
import structlog
from app.core.config import settings

logger = structlog.get_logger(__name__)

# Setup Jinja2 template environment
TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "email"

jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "j2"]),
)


def render_template(template_name: str, context: dict) -> str:
    """Render a Jinja2 email template."""
    try:
        template = jinja_env.get_template(template_name)
        return template.render(**context)
    except Exception as e:
        logger.error("template_render_failed", template=template_name, error=str(e))
        # Fallback to plain text
        return f"<p>{context.get('message', 'Email from BuildTrack')}</p>"


def _send_via_gmail_smtp(to: str, subject: str, html_body: str) -> bool:
    """Send through Gmail SMTP using the stdlib (no extra dependency).
    Uses GMAIL_APP_PASSWORD and the configured from-address."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    if not settings.GMAIL_APP_PASSWORD:
        logger.warning("gmail_not_configured", reason="No GMAIL_APP_PASSWORD")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM_ADDRESS}>"
    msg["To"] = to
    msg["Reply-To"] = settings.EMAIL_REPLY_TO
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as server:
        server.starttls()
        server.login(settings.EMAIL_FROM_ADDRESS, settings.GMAIL_APP_PASSWORD)
        server.sendmail(settings.EMAIL_FROM_ADDRESS, [to], msg.as_string())
    return True


def _send_via_resend(to: str, subject: str, html_body: str) -> bool:
    if not settings.RESEND_API_KEY or settings.RESEND_API_KEY.startswith("re_placeholder"):
        logger.warning("email_not_sent_no_key", to=to, subject=subject, reason="No valid RESEND_API_KEY")
        return False
    import resend
    resend.api_key = settings.RESEND_API_KEY
    email = resend.Emails.send({
        "from": f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM_ADDRESS}>",
        "to": [to],
        "subject": subject,
        "html": html_body,
        "reply_to": settings.EMAIL_REPLY_TO,
    })
    logger.info("email_sent", to=to, subject=subject, email_id=email.get("id"), provider="resend")
    return True


async def send_email(
    to: str,
    subject: str,
    html_body: Optional[str] = None,
    template_name: Optional[str] = None,
    template_context: Optional[dict] = None,
) -> bool:
    """Send an email via the configured provider (resend | gmail).
    Same interface for all providers. Returns True on success."""
    import asyncio

    try:
        if template_name and template_context:
            html_body = render_template(template_name, template_context)
        if not html_body:
            logger.warning("send_email_no_body", to=to, subject=subject)
            return False

        provider = (settings.EMAIL_PROVIDER or "resend").lower()
        if provider == "gmail":
            sent = await asyncio.to_thread(_send_via_gmail_smtp, to, subject, html_body)
            if sent:
                logger.info("email_sent", to=to, subject=subject, provider="gmail")
            return sent
        return _send_via_resend(to, subject, html_body)

    except Exception as e:
        logger.error("email_send_failed", to=to, subject=subject, error=str(e))
        return False
