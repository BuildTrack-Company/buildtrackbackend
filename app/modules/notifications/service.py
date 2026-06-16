from datetime import datetime, timezone
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from app.modules.notifications.models import NotificationLog
from app.modules.uploads.models import Upload
from app.modules.buyers.models import Buyer
from app.modules.projects.models import Project
from app.shared.email import send_email
from app.shared.ids import new_id

logger = structlog.get_logger(__name__)


async def fanout_upload_notifications(upload_id: str, db: AsyncSession):
    """Fan out upload notifications to all buyers of a project."""
    result = await db.execute(
        select(Upload).where(Upload.id == upload_id)
    )
    upload = result.scalar_one_or_none()
    if not upload:
        logger.warning("fanout_upload_not_found", upload_id=upload_id)
        return

    result = await db.execute(
        select(Project).where(Project.id == upload.project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        return

    result = await db.execute(
        select(Buyer).where(
            Buyer.project_id == upload.project_id,
            Buyer.notification_email.is_(True),
            Buyer.deleted_at.is_(None),
        )
    )
    buyers = result.scalars().all()

    # Tier email quota check (entry of send path, brief Phase 4)
    try:
        from app.shared.quotas import assert_can_send_email
        await assert_can_send_email(db, upload.developer_id, len(buyers))
    except Exception as e:
        logger.warning("fanout_email_quota_exceeded", developer_id=upload.developer_id, error=str(e))
        return

    # Process in batches of 10
    BATCH_SIZE = 10
    success_count = 0
    fail_count = 0

    for i in range(0, len(buyers), BATCH_SIZE):
        batch = buyers[i:i + BATCH_SIZE]
        for buyer in batch:
            try:
                sent = await send_email(
                    to=buyer.email,
                    subject=f"Construction Update: {project.name}",
                    template_name="buyer_update_notification.html.j2",
                    template_context={
                        "first_name": buyer.full_name or "Buyer",
                        "project_name": project.name,
                        "update_title": upload.title or "New Site Photos",
                        "update_description": upload.caption or "New photos have been uploaded to track construction progress.",
                        "view_link": f"https://buildtrack.co.ke/project/{project.project_code}",
                    },
                )

                log_entry = NotificationLog(
                    id=new_id(),
                    upload_id=upload_id,
                    buyer_id=buyer.id,
                    developer_id=upload.developer_id,
                    notification_type="email",
                    recipient_email=buyer.email,
                    subject=f"Construction Update: {project.name}",
                    template_name="buyer_update_notification.html.j2",
                    status="sent" if sent else "failed",
                )
                db.add(log_entry)

                if sent:
                    success_count += 1
                else:
                    fail_count += 1

            except Exception as e:
                logger.error("notification_send_failed", buyer_id=buyer.id, error=str(e))
                fail_count += 1

    # Update upload fanout status
    upload.notification_fanout_status = "complete"
    upload.notification_fanout_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info(
        "fanout_complete",
        upload_id=upload_id,
        success=success_count,
        failed=fail_count,
        total=len(buyers),
    )


async def send_milestone_notification(milestone_id: str, event: str, db: AsyncSession):
    """Send milestone-related notifications to buyers."""
    from app.modules.milestones.models import Milestone

    result = await db.execute(
        select(Milestone).where(Milestone.id == milestone_id)
    )
    milestone = result.scalar_one_or_none()
    if not milestone:
        return

    result = await db.execute(
        select(Project).where(Project.id == milestone.project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        return

    result = await db.execute(
        select(Buyer).where(
            Buyer.project_id == milestone.project_id,
            Buyer.notification_email.is_(True),
            Buyer.deleted_at.is_(None),
        )
    )
    buyers = result.scalars().all()

    template_map = {
        "completed": "milestone_complete.html.j2",
        "delayed": "milestone_revision.html.j2",
    }
    template = template_map.get(event, "milestone_complete.html.j2")
    subject_map = {
        "completed": f"Milestone completed: {milestone.name}",
        "delayed": f"Schedule Update: {milestone.name} — {project.name}",
    }
    subject = subject_map.get(event, f"Milestone update: {milestone.name}")

    for buyer in buyers:
        try:
            await send_email(
                to=buyer.email,
                subject=subject,
                template_name=template,
                template_context={
                    "first_name": buyer.full_name or "Buyer",
                    "project_name": project.name,
                    "milestone_name": milestone.name,
                    "reason": milestone.delay_reason or "Unforeseen delays",
                    "new_date": milestone.delay_new_date.strftime("%d %b %Y") if milestone.delay_new_date else "TBD",
                },
            )
        except Exception as e:
            logger.error("milestone_notification_failed", buyer_id=buyer.id, error=str(e))

    await db.commit()
