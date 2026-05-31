from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import datetime, timezone, timedelta

from app.core.database import get_db
from app.core.deps import get_current_user, require_developer
from app.modules.auth.models import User
from app.modules.developers import service, schemas
from app.shared.response import ok

router = APIRouter(prefix="/developers", tags=["developers"])


@router.get("/stats")
async def get_developer_stats(
    request: Request,
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    """Dashboard stats for the logged-in developer."""
    from app.modules.developers.models import Developer
    from app.modules.projects.models import Project
    from app.modules.buyers.models import Buyer
    from app.modules.uploads.models import Upload, Photo

    dev = await service.get_developer_by_user_id(db, current_user.id)
    developer_id = dev.id

    # Projects for this developer
    projects_result = await db.execute(
        select(Project.id).where(Project.developer_id == developer_id, Project.deleted_at.is_(None))
    )
    project_ids = [r[0] for r in projects_result.all()]

    if not project_ids:
        return ok({"total_buyers": 0, "active_this_week": 0, "photos_uploaded": 0, "buyer_complaints": 0}, request=request)

    # Total buyers
    total_buyers = (await db.execute(
        select(func.count()).select_from(Buyer).where(
            Buyer.project_id.in_(project_ids), Buyer.deleted_at.is_(None)
        )
    )).scalar_one()

    # Uploads this week
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    active_this_week = (await db.execute(
        select(func.count()).select_from(Upload).where(
            Upload.developer_id == developer_id,
            Upload.created_at >= week_ago,
        )
    )).scalar_one()

    # Total photos
    photos_uploaded = (await db.execute(
        select(func.count()).select_from(Photo).join(Upload, Photo.upload_id == Upload.id).where(
            Upload.developer_id == developer_id
        )
    )).scalar_one()

    return ok({
        "total_buyers": total_buyers,
        "active_this_week": active_this_week,
        "photos_uploaded": photos_uploaded,
        "buyer_complaints": 0,
    }, request=request)


@router.get("/me/activity")
async def get_my_activity_feed(
    request: Request,
    limit: int = 20,
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    """Chronological 'what's been happening' feed for the developer dashboard,
    sourced from the audit log (last 90 days, scoped to this developer)."""
    from app.modules.admin.models import AuditLog

    dev = await service.get_developer_by_user_id(db, current_user.id)
    limit = max(1, min(limit, 100))
    since = datetime.now(timezone.utc) - timedelta(days=90)

    rows = (await db.execute(
        select(AuditLog).where(
            AuditLog.developer_id == dev.id,
            AuditLog.created_at >= since,
        ).order_by(AuditLog.created_at.desc()).limit(limit)
    )).scalars().all()

    summaries = {
        "upload.approved": "A construction update was approved",
        "upload.rejected.gps_outside_boundary": "An upload was rejected (outside site boundary)",
        "upload.rejectd": "An upload was rejected",
        "upload.rejected": "An upload was rejected",
        "milestone.completed": "A milestone was marked complete",
        "milestone.delayed": "A milestone was marked delayed",
        "buyer.invited": "A buyer was invited",
        "inquiry.created": "A new inquiry was received",
        "project.visibility.published": "A visibility page was published",
        "project.created": "A project was created",
        "member.invited": "A team member was invited",
    }
    feed = [{
        "id": r.id,
        "type": r.action,
        "entity_type": r.entity_type,
        "summary": summaries.get(r.action, r.action.replace(".", " ").replace("_", " ").capitalize()),
        "actor_role": r.actor_role,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]
    return ok(feed, request=request)


@router.get("/me")
async def get_my_developer_profile(
    request: Request,
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    dev = await service.get_developer_by_user_id(db, current_user.id)
    return ok(schemas.DeveloperResponse.model_validate(dev).model_dump(), request=request)


@router.patch("/me")
async def update_my_developer_profile(
    update: schemas.DeveloperUpdate,
    request: Request,
    current_user: User = Depends(require_developer),
    db: AsyncSession = Depends(get_db),
):
    dev = await service.get_developer_by_user_id(db, current_user.id)
    for field, value in update.model_dump(exclude_none=True).items():
        setattr(dev, field, value)
    await db.commit()
    await db.refresh(dev)
    return ok(schemas.DeveloperResponse.model_validate(dev).model_dump(), request=request)
