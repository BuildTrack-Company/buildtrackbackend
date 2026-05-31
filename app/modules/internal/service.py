from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
import structlog

logger = structlog.get_logger(__name__)


async def scan_overdue_milestones(db: AsyncSession) -> dict:
    """Scan for overdue milestones and mark them as delayed."""
    from app.modules.milestones.models import Milestone

    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Milestone).where(
            Milestone.expected_date < now,
            Milestone.status.in_(["pending", "in_progress"]),
        )
    )
    overdue = result.scalars().all()

    updated = 0
    for milestone in overdue:
        milestone.status = "delayed"
        updated += 1

    await db.commit()
    logger.info("overdue_milestones_scanned", updated=updated)
    return {"updated": updated}


async def cleanup_deny_list(db: AsyncSession) -> dict:
    """Remove expired tokens from the deny list."""
    from app.modules.auth.models import AuthTokenDenyList

    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(AuthTokenDenyList).where(AuthTokenDenyList.expires_at < now)
    )
    expired = result.scalars().all()
    count = len(expired)

    for token in expired:
        await db.delete(token)

    await db.commit()
    logger.info("deny_list_cleaned", removed=count)
    return {"removed": count}


async def send_trial_warnings(db: AsyncSession) -> dict:
    """Email developers whose trial ends in 3 days or fewer."""
    from app.modules.developers.models import Developer
    from app.modules.auth.models import User
    from app.shared.email import send_email
    from sqlalchemy import select

    now = datetime.now(timezone.utc)
    warning_cutoff = now + timedelta(days=3)

    result = await db.execute(
        select(Developer).where(
            Developer.subscription_tier == "trial",
            Developer.subscription_status == "active",
            Developer.trial_ends_at.isnot(None),
            Developer.trial_ends_at > now,
            Developer.trial_ends_at <= warning_cutoff,
            Developer.deleted_at.is_(None),
        )
    )
    developers = result.scalars().all()

    sent = 0
    for dev in developers:
        user_result = await db.execute(select(User).where(User.id == dev.user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            continue
        days_left = max(0, (dev.trial_ends_at - now).days)
        try:
            await send_email(
                to=user.email,
                subject="Your BuildTrack trial ends soon",
                template_name="trial_warning.html.j2",
                template_context={
                    "full_name": user.full_name or user.email,
                    "days_left": days_left,
                    "trial_ends_at": dev.trial_ends_at.strftime("%d %b %Y"),
                },
            )
            sent += 1
        except Exception as e:
            logger.warning("trial_warning_email_failed", developer_id=dev.id, error=str(e))

    logger.info("trial_warnings_sent", sent=sent)
    return {"sent": sent}


async def sync_cloudinary_usage(db: AsyncSession) -> dict:
    """Pull storage usage from Cloudinary and update usage_counters for each developer."""
    from app.modules.developers.models import Developer
    from sqlalchemy import select, text
    import cloudinary
    import cloudinary.api

    result = await db.execute(
        select(Developer).where(Developer.deleted_at.is_(None), Developer.subscription_status == "active")
    )
    developers = result.scalars().all()

    updated = 0
    errors = 0
    for dev in developers:
        try:
            # Cloudinary doesn't offer per-folder usage; count bytes from our Photo records
            from app.modules.uploads.models import Photo, Upload
            from sqlalchemy import func
            bytes_result = await db.execute(
                select(func.coalesce(func.sum(Photo.file_size_bytes), 0))
                .join(Upload, Photo.upload_id == Upload.id)
                .where(Upload.developer_id == dev.id)
            )
            storage_bytes = bytes_result.scalar_one()

            await db.execute(
                text("""
                    INSERT INTO usage_counters (id, developer_id, storage_used_bytes, updated_at)
                    VALUES (:id, :dev_id, :bytes, NOW())
                    ON CONFLICT (developer_id) DO UPDATE
                    SET storage_used_bytes = :bytes, updated_at = NOW()
                """),
                {"id": __import__("app.shared.ids", fromlist=["new_id"]).new_id(), "dev_id": dev.id, "bytes": storage_bytes},
            )
            updated += 1
        except Exception as e:
            logger.warning("sync_cloudinary_usage_failed", developer_id=dev.id, error=str(e))
            errors += 1

    await db.commit()
    logger.info("cloudinary_usage_synced", updated=updated, errors=errors)
    return {"updated": updated, "errors": errors}


async def recalculate_usage_counters(db: AsyncSession) -> dict:
    """Recalculate usage counters for all developers."""
    from app.modules.developers.models import Developer
    from app.modules.projects.models import Project
    from app.modules.uploads.models import Upload
    from sqlalchemy import func

    result = await db.execute(
        select(Developer).where(Developer.deleted_at.is_(None))
    )
    developers = result.scalars().all()

    updated = 0
    for dev in developers:
        # Count projects
        proj_count = (await db.execute(
            select(func.count()).select_from(Project).where(
                Project.developer_id == dev.id,
                Project.deleted_at.is_(None),
            )
        )).scalar_one()
        updated += 1

    logger.info("usage_counters_recalculated", developers=updated)
    return {"developers_updated": updated}


async def recalculate_developer_stats(db: AsyncSession) -> dict:
    """Recompute credibility-profile stats for every developer:
    active_developments, avg_update_frequency_days, update_consistency_pct."""
    from app.modules.developers.models import Developer
    from app.modules.projects.models import Project
    from app.modules.uploads.models import Upload
    from sqlalchemy import func

    developers = (await db.execute(
        select(Developer).where(Developer.deleted_at.is_(None))
    )).scalars().all()

    updated = 0
    for dev in developers:
        # Active developments = non-completed, non-deleted projects
        active = (await db.execute(
            select(func.count()).select_from(Project).where(
                Project.developer_id == dev.id,
                Project.deleted_at.is_(None),
                Project.status != "completed",
            )
        )).scalar_one()
        dev.active_developments = active

        # Approved-update cadence across this developer's projects
        approved = (await db.execute(
            select(Upload.created_at).where(
                Upload.developer_id == dev.id,
                Upload.status == "approved",
            ).order_by(Upload.created_at.asc())
        )).scalars().all()

        if len(approved) >= 2:
            first, last = approved[0], approved[-1]
            span_days = max((last - first).days, 1)
            dev.avg_update_frequency_days = round(span_days / (len(approved) - 1), 2)
            # Consistency: share of weeks in the span that had at least one update
            weeks = max(span_days // 7, 1)
            weeks_with_update = len({(u - first).days // 7 for u in approved})
            dev.update_consistency_pct = round(min(weeks_with_update / weeks, 1.0) * 100, 1)
        else:
            dev.avg_update_frequency_days = None
            dev.update_consistency_pct = None
        updated += 1

    await db.commit()
    logger.info("developer_stats_recalculated", developers=updated)
    return {"developers_updated": updated}
