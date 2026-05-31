from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import structlog

from app.modules.projects.models import Project
from app.modules.developers.models import Developer
from app.modules.milestones.models import Milestone
from app.modules.uploads.models import Upload, Photo
from app.modules.inquiries.models import Inquiry, VisibilityPageView
from app.modules.buyers.models import Buyer
from app.core.exceptions import NotFoundError
from app.shared.ids import new_id
from app.shared.storage import get_signed_url

logger = structlog.get_logger(__name__)


def _days_since(dt: Optional[datetime]) -> Optional[int]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).days


async def _latest_approved_update(db: AsyncSession, project_id: str) -> Optional[Upload]:
    return (await db.execute(
        select(Upload).where(Upload.project_id == project_id, Upload.status == "approved")
        .order_by(Upload.created_at.desc()).limit(1)
    )).scalar_one_or_none()


def compute_activity_status(threshold_days: int, last_update_at: Optional[datetime]) -> str:
    """active / no_activity / update_overdue based on the configured threshold."""
    if not last_update_at:
        return "no_activity"
    days = _days_since(last_update_at)
    if days is not None and days > threshold_days:
        return "update_overdue"
    return "active"


async def _project_card(db: AsyncSession, project: Project) -> dict:
    dev = (await db.execute(select(Developer).where(Developer.id == project.developer_id))).scalar_one_or_none()
    milestone_count = (await db.execute(
        select(func.count()).select_from(Milestone).where(Milestone.project_id == project.id)
    )).scalar_one()
    verified_records = (await db.execute(
        select(func.count()).select_from(Upload).where(
            Upload.project_id == project.id, Upload.status == "approved"
        )
    )).scalar_one()
    last = await _latest_approved_update(db, project.id)
    last_at = last.created_at if last else None
    activity = compute_activity_status(project.activity_overdue_threshold_days, last_at)

    # Update frequency label from approved records over their span
    if verified_records >= 2 and last_at:
        first = (await db.execute(
            select(Upload.created_at).where(Upload.project_id == project.id, Upload.status == "approved")
            .order_by(Upload.created_at.asc()).limit(1)
        )).scalar_one_or_none()
        span_days = max((_days_since(first) or 0), 1)
        per_week = (verified_records / span_days) * 7
        freq_label = f"{per_week:.1f} updates/week" if per_week >= 1 else "Periodic updates"
    else:
        freq_label = "New project"

    return {
        "slug": project.slug,
        "project_name": project.name,
        "developer_name": dev.company_name if dev else None,
        "location": project.location_name,
        "unit_count": project.total_units,
        "health_status": project.health_status,
        "construction_progress": project.construction_progress,
        "milestone_count": milestone_count,
        "verified_records_count": verified_records,
        "completion_date": project.estimated_completion,
        "update_frequency_label": freq_label,
        "last_verified_at": last_at,
        "last_verified_days_ago": _days_since(last_at),
        "activity_status": activity,
        "verification_badge": "Site Progress Verified" if verified_records else "Awaiting First Update",
    }


async def get_directory(db: AsyncSession, area: Optional[str] = None, sort: str = "latest") -> list[dict]:
    conditions = [Project.visibility_page_published == True, Project.deleted_at.is_(None)]
    if area and area.lower() != "all areas":
        conditions.append(func.lower(Project.location_name) == area.lower())

    projects = (await db.execute(select(Project).where(*conditions))).scalars().all()
    cards = [await _project_card(db, p) for p in projects]

    if sort == "completion":
        cards.sort(key=lambda c: (c["completion_date"] is None, c["completion_date"]))
    elif sort == "progress":
        cards.sort(key=lambda c: c["construction_progress"], reverse=True)
    else:  # latest
        cards.sort(key=lambda c: (c["last_verified_at"] is None, c["last_verified_at"] or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    return cards


async def _photo_payload(db: AsyncSession, upload_ids: list[str]) -> list[dict]:
    if not upload_ids:
        return []
    photos = (await db.execute(
        select(Photo).where(Photo.upload_id.in_(upload_ids)).order_by(Photo.created_at.desc())
    )).scalars().all()
    out = []
    for p in photos:
        out.append({
            "id": p.id,
            "upload_id": p.upload_id,
            "signed_url": get_signed_url(p.cloudinary_public_id, "display"),
            "thumbnail_url": get_signed_url(p.cloudinary_public_id, "thumbnail"),
            "capture_latitude": p.capture_latitude,
            "capture_longitude": p.capture_longitude,
            "captured_at": p.created_at,
        })
    return out


async def get_visibility_page(db: AsyncSession, slug: str) -> dict:
    project = (await db.execute(
        select(Project).where(
            Project.slug == slug,
            Project.visibility_page_published == True,
            Project.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if not project:
        raise NotFoundError("Visibility page not found")

    dev = (await db.execute(select(Developer).where(Developer.id == project.developer_id))).scalar_one_or_none()

    milestones = (await db.execute(
        select(Milestone).where(Milestone.project_id == project.id).order_by(Milestone.order_index)
    )).scalars().all()

    approved = (await db.execute(
        select(Upload).where(Upload.project_id == project.id, Upload.status == "approved")
        .order_by(Upload.created_at.desc())
    )).scalars().all()

    last = approved[0] if approved else None
    last_at = last.created_at if last else None
    last_milestone = (await db.execute(
        select(Milestone).where(Milestone.project_id == project.id, Milestone.status == "complete")
        .order_by(Milestone.completed_at.desc().nullslast()).limit(1)
    )).scalar_one_or_none()

    next_milestone = (await db.execute(
        select(Milestone).where(Milestone.project_id == project.id, Milestone.status != "complete")
        .order_by(Milestone.order_index).limit(1)
    )).scalar_one_or_none()

    timeline = []
    for u in approved:
        photo_count = (await db.execute(
            select(func.count()).select_from(Photo).where(Photo.upload_id == u.id)
        )).scalar_one()
        timeline.append({
            "id": u.id,
            "title": u.title,
            "category": u.category,
            "description": u.caption,
            "photo_count": photo_count,
            "capture_latitude": u.capture_latitude,
            "capture_longitude": u.capture_longitude,
            "within_boundary": u.within_boundary,
            "progress_at_upload": u.progress_at_upload,
            "created_at": u.created_at,
        })

    photos = await _photo_payload(db, [u.id for u in approved])

    return {
        "project": {
            "name": project.name,
            "slug": project.slug,
            "location": project.location_name,
            "completion_date": project.estimated_completion,
            "description": project.visibility_description or project.description,
            "tagline": project.visibility_tagline,
            "starting_price": project.starting_price,
            "unit_count": project.total_units,
            "developer_name": dev.company_name if dev else None,
        },
        "intelligence_status": {
            "health_status": project.health_status,
            "construction_progress": project.construction_progress,
            "last_activity_days_ago": _days_since(last_at),
            "site_active": compute_activity_status(project.activity_overdue_threshold_days, last_at) != "update_overdue",
            "last_milestone": last_milestone.name if last_milestone else None,
            "next_milestone_date": next_milestone.expected_date if next_milestone else None,
            "activity_status": compute_activity_status(project.activity_overdue_threshold_days, last_at),
        },
        "milestones": [
            {
                "sequence": m.order_index,
                "name": m.name,
                "status": m.status,
                "expected_date": m.expected_date,
                "completed_at": m.completed_at,
            } for m in milestones
        ],
        "photo_gallery": photos,
        "verified_timeline": timeline,
        "developer_credibility": {
            "company_name": dev.company_name if dev else None,
            "years_operating": dev.years_operating if dev else 0,
            "projects_completed": dev.projects_completed if dev else 0,
            "active_developments": dev.active_developments if dev else 0,
            "avg_update_frequency_days": dev.avg_update_frequency_days if dev else None,
            "update_consistency_pct": dev.update_consistency_pct if dev else None,
            "company_overview": dev.company_overview if dev else None,
        },
        "verification_badges": {"gps_verified_records": len(approved)},
        "independent_verification": {
            "enabled": getattr(project, "independent_verification_enabled", False),
            "last_verified_at": getattr(project, "last_independent_verification_at", None),
            "verifier_name": getattr(project, "last_independent_verifier_name", None),
            "outcome": getattr(project, "last_independent_verifier_outcome", None),
        },
    }


async def log_view(
    db: AsyncSession, slug: str, session_id: str,
    country_code: Optional[str] = None, duration_seconds: Optional[int] = None,
    referrer: Optional[str] = None,
) -> None:
    project = (await db.execute(
        select(Project).where(Project.slug == slug, Project.deleted_at.is_(None))
    )).scalar_one_or_none()
    if not project:
        raise NotFoundError("Project not found")

    db.add(VisibilityPageView(
        id=new_id(),
        project_id=project.id,
        session_id=session_id,
        country_code=country_code,
        duration_seconds=duration_seconds,
        referrer=referrer,
    ))
    # Atomic counter increment
    project.visibility_page_views = (project.visibility_page_views or 0) + 1
    await db.commit()


async def get_photo_signed_url(db: AsyncSession, slug: str, photo_id: str) -> str:
    project = (await db.execute(
        select(Project).where(
            Project.slug == slug, Project.visibility_page_published == True, Project.deleted_at.is_(None)
        )
    )).scalar_one_or_none()
    if not project:
        raise NotFoundError("Visibility page not found")

    photo = (await db.execute(select(Photo).where(Photo.id == photo_id))).scalar_one_or_none()
    if not photo:
        raise NotFoundError("Photo not found")
    upload = (await db.execute(select(Upload).where(Upload.id == photo.upload_id))).scalar_one_or_none()
    if not upload or upload.project_id != project.id or upload.status != "approved":
        raise NotFoundError("Photo not found")
    return get_signed_url(photo.cloudinary_public_id, "display")


async def get_project_analytics(db: AsyncSession, developer_id: str, project_id: str) -> dict:
    project = (await db.execute(
        select(Project).where(Project.id == project_id, Project.developer_id == developer_id)
    )).scalar_one_or_none()
    if not project:
        raise NotFoundError("Project not found")

    from datetime import timedelta
    total_views = (await db.execute(
        select(func.count()).select_from(VisibilityPageView).where(VisibilityPageView.project_id == project_id)
    )).scalar_one()
    last30 = datetime.now(timezone.utc) - timedelta(days=30)
    views_30 = (await db.execute(
        select(func.count()).select_from(VisibilityPageView).where(
            VisibilityPageView.project_id == project_id, VisibilityPageView.viewed_at >= last30
        )
    )).scalar_one()
    avg_time = (await db.execute(
        select(func.avg(VisibilityPageView.duration_seconds)).where(
            VisibilityPageView.project_id == project_id
        )
    )).scalar_one()
    abroad = (await db.execute(
        select(func.count()).select_from(VisibilityPageView).where(
            VisibilityPageView.project_id == project_id,
            VisibilityPageView.country_code.isnot(None),
            VisibilityPageView.country_code != "KE",
        )
    )).scalar_one()
    countries = (await db.execute(
        select(VisibilityPageView.country_code, func.count().label("c")).where(
            VisibilityPageView.project_id == project_id, VisibilityPageView.country_code.isnot(None)
        ).group_by(VisibilityPageView.country_code).order_by(func.count().desc()).limit(5)
    )).fetchall()

    total_inquiries = (await db.execute(
        select(func.count()).select_from(Inquiry).where(Inquiry.project_id == project_id)
    )).scalar_one()
    converted = (await db.execute(
        select(func.count()).select_from(Inquiry).where(
            Inquiry.project_id == project_id, Inquiry.converted_at.isnot(None)
        )
    )).scalar_one()

    return {
        "total_views": total_views,
        "views_last_30_days": views_30,
        "percent_from_abroad": round((abroad / total_views) * 100, 1) if total_views else 0.0,
        "avg_time_on_page_seconds": int(avg_time) if avg_time else 0,
        "total_inquiries": total_inquiries,
        "inquiry_conversion_rate": round((converted / total_inquiries) * 100, 1) if total_inquiries else 0.0,
        "top_countries": [{"country_code": c[0], "count": c[1]} for c in countries],
    }
