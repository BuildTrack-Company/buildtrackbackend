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


async def send_email(
    to: str,
    subject: str,
    html_body: Optional[str] = None,
    template_name: Optional[str] = None,
    template_context: Optional[dict] = None,
) -> bool:
    """Send an email using Resend. Returns True on success, False on failure."""
    try:
        if template_name and template_context:
            html_body = render_template(template_name, template_context)

        if not html_body:
            logger.warning("send_email_no_body", to=to, subject=subject)
            return False

        if not settings.RESEND_API_KEY or settings.RESEND_API_KEY.startswith("re_placeholder"):
            logger.warning(
                "email_not_sent_no_key",
                to=to,
                subject=subject,
                reason="No valid RESEND_API_KEY configured",
            )
            return False

        import resend

        resend.api_key = settings.RESEND_API_KEY

        params = {
            "from": f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM_ADDRESS}>",
            "to": [to],
            "subject": subject,
            "html": html_body,
            "reply_to": settings.EMAIL_REPLY_TO,
        }

        email = resend.Emails.send(params)
        logger.info("email_sent", to=to, subject=subject, email_id=email.get("id"))
        return True

    except Exception as e:
        logger.error("email_send_failed", to=to, subject=subject, error=str(e))
        return False
