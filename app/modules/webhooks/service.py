import json
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from app.modules.webhooks.models import WebhookEvent
from app.shared.ids import new_id

logger = structlog.get_logger(__name__)


async def process_resend_webhook(db: AsyncSession, event_id: str, event_type: str, payload: dict):
    """Process Resend webhook event idempotently."""
    # Check if already processed
    result = await db.execute(
        select(WebhookEvent).where(WebhookEvent.event_id == event_id)
    )
    if result.scalar_one_or_none():
        logger.info("webhook_already_processed", event_id=event_id)
        return

    event = WebhookEvent(
        id=new_id(),
        provider="resend",
        event_id=event_id,
        event_type=event_type,
        payload=json.dumps(payload),
    )
    db.add(event)

    # Update notification log status if applicable
    if event_type in ("email.delivered",):
        message_id = payload.get("data", {}).get("email_id")
        if message_id:
            from app.modules.notifications.models import NotificationLog
            result = await db.execute(
                select(NotificationLog).where(NotificationLog.provider_message_id == message_id)
            )
            log = result.scalar_one_or_none()
            if log:
                log.status = "delivered"

    elif event_type in ("email.bounced", "email.complained"):
        message_id = payload.get("data", {}).get("email_id")
        if message_id:
            from app.modules.notifications.models import NotificationLog
            result = await db.execute(
                select(NotificationLog).where(NotificationLog.provider_message_id == message_id)
            )
            log = result.scalar_one_or_none()
            if log:
                log.status = "bounced"

    await db.commit()
    logger.info("webhook_processed", provider="resend", event_type=event_type)


async def process_brevo_webhook(db: AsyncSession, message_id: str, event_type: str, payload: dict):
    """Process Brevo webhook event idempotently."""
    result = await db.execute(
        select(WebhookEvent).where(WebhookEvent.event_id == message_id)
    )
    if result.scalar_one_or_none():
        logger.info("webhook_already_processed", event_id=message_id)
        return

    event = WebhookEvent(
        id=new_id(),
        provider="brevo",
        event_id=message_id,
        event_type=event_type,
        payload=json.dumps(payload),
    )
    db.add(event)

    # Brevo event types: delivered, soft_bounce, hard_bounce, spam, unsubscribed
    status_map = {
        "delivered": "delivered",
        "soft_bounce": "bounced",
        "hard_bounce": "bounced",
        "spam": "bounced",
    }
    mapped_status = status_map.get(event_type)
    if mapped_status:
        from app.modules.notifications.models import NotificationLog
        result = await db.execute(
            select(NotificationLog).where(NotificationLog.provider_message_id == message_id)
        )
        log = result.scalar_one_or_none()
        if log:
            log.status = mapped_status

    await db.commit()
    logger.info("webhook_processed", provider="brevo", event_type=event_type)
