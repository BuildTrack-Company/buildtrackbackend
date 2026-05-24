from fastapi import APIRouter, Depends, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import json

from app.core.database import get_db
from app.modules.webhooks import service
from app.shared.response import ok

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/brevo")
async def brevo_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle Brevo (formerly Sendinblue) delivery-status webhook events."""
    try:
        body = await request.json()
        event_type = body.get("event", "unknown")
        message_id = body.get("message-id", f"brevo_{event_type}")
        await service.process_brevo_webhook(db, message_id, event_type, body)
        return ok({"received": True}, request=request)
    except Exception as e:
        import structlog
        logger = structlog.get_logger(__name__)
        logger.error("brevo_webhook_error", error=str(e))
        return ok({"received": False, "error": str(e)}, request=request)


@router.post("/resend")
async def resend_webhook(
    request: Request,
    svix_id: Optional[str] = Header(None),
    svix_timestamp: Optional[str] = Header(None),
    svix_signature: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """Handle Resend webhook events."""
    try:
        body = await request.json()
        event_type = body.get("type", "unknown")
        event_id = svix_id or body.get("id", f"resend_{event_type}")

        await service.process_resend_webhook(db, event_id, event_type, body)
        return ok({"received": True}, request=request)
    except Exception as e:
        import structlog
        logger = structlog.get_logger(__name__)
        logger.error("webhook_error", error=str(e))
        return ok({"received": False, "error": str(e)}, request=request)
