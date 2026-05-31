from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
import structlog

from app.modules.inquiries.models import Inquiry
from app.modules.inquiries.schemas import InquiryCreate
from app.modules.projects.models import Project
from app.core.exceptions import NotFoundError, DuplicateError, QuotaExceededError
from app.shared.ids import new_id

logger = structlog.get_logger(__name__)

RATE_LIMIT_PER_IP_PER_HOUR = 5


async def create_inquiry(
    db: AsyncSession,
    slug: str,
    req: InquiryCreate,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Inquiry:
    """Create a lead from a prospective buyer. Public, rate-limited, deduped."""
    project = (await db.execute(
        select(Project).where(Project.slug == slug, Project.deleted_at.is_(None))
    )).scalar_one_or_none()
    if not project:
        raise NotFoundError("Project not found")

    # Rate limit: max N per IP per hour
    if ip_address:
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        recent = (await db.execute(
            select(func.count()).select_from(Inquiry).where(
                Inquiry.ip_address == ip_address,
                Inquiry.created_at >= since,
            )
        )).scalar_one()
        if recent >= RATE_LIMIT_PER_IP_PER_HOUR:
            raise QuotaExceededError(
                "Too many inquiries from this address. Please try again later.",
                {"limit": RATE_LIMIT_PER_IP_PER_HOUR, "window": "1h"},
            )

    # Dedup: one inquiry per (project, email) lifetime
    existing = (await db.execute(
        select(Inquiry).where(
            Inquiry.project_id == project.id,
            func.lower(Inquiry.email) == req.email.lower(),
        )
    )).scalar_one_or_none()
    if existing:
        raise DuplicateError(
            "An inquiry from this email already exists for this project.",
            {"project_id": project.id},
        )

    inquiry = Inquiry(
        id=new_id(),
        project_id=project.id,
        developer_id=project.developer_id,
        first_name=req.first_name,
        last_name=req.last_name,
        email=req.email,
        phone=req.phone,
        location=req.location,
        message=req.message,
        source=req.source if req.source in ("visibility_page", "directory_card", "home_page") else "visibility_page",
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(inquiry)
    await db.commit()
    await db.refresh(inquiry)
    return inquiry


async def list_for_developer(
    db: AsyncSession, developer_id: str, project_id: Optional[str] = None,
    seen: Optional[bool] = None, page: int = 1, limit: int = 20,
) -> tuple[list[Inquiry], int]:
    conditions = [Inquiry.developer_id == developer_id]
    if project_id:
        conditions.append(Inquiry.project_id == project_id)
    if seen is not None:
        conditions.append(Inquiry.seen_by_developer == seen)

    total = (await db.execute(
        select(func.count()).select_from(Inquiry).where(and_(*conditions))
    )).scalar_one()
    rows = (await db.execute(
        select(Inquiry).where(and_(*conditions))
        .order_by(Inquiry.created_at.desc())
        .offset((page - 1) * limit).limit(limit)
    )).scalars().all()
    return rows, total


async def get_for_developer(db: AsyncSession, developer_id: str, inquiry_id: str) -> Inquiry:
    inquiry = (await db.execute(
        select(Inquiry).where(Inquiry.id == inquiry_id, Inquiry.developer_id == developer_id)
    )).scalar_one_or_none()
    if not inquiry:
        raise NotFoundError("Inquiry not found")
    return inquiry


async def mark_seen(db: AsyncSession, developer_id: str, inquiry_id: str) -> Inquiry:
    inquiry = await get_for_developer(db, developer_id, inquiry_id)
    if not inquiry.seen_by_developer:
        inquiry.seen_by_developer = True
        inquiry.seen_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(inquiry)
    return inquiry


async def mark_converted(db: AsyncSession, developer_id: str, inquiry_id: str) -> Inquiry:
    inquiry = await get_for_developer(db, developer_id, inquiry_id)
    if not inquiry.converted_at:
        inquiry.converted_at = datetime.now(timezone.utc)
        if not inquiry.seen_by_developer:
            inquiry.seen_by_developer = True
            inquiry.seen_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(inquiry)
    return inquiry


async def list_all_admin(
    db: AsyncSession, developer_id: Optional[str] = None, project_id: Optional[str] = None,
    page: int = 1, limit: int = 50,
) -> tuple[list[Inquiry], int]:
    conditions = []
    if developer_id:
        conditions.append(Inquiry.developer_id == developer_id)
    if project_id:
        conditions.append(Inquiry.project_id == project_id)
    where = and_(*conditions) if conditions else True

    total = (await db.execute(
        select(func.count()).select_from(Inquiry).where(where)
    )).scalar_one()
    rows = (await db.execute(
        select(Inquiry).where(where)
        .order_by(Inquiry.created_at.desc())
        .offset((page - 1) * limit).limit(limit)
    )).scalars().all()
    return rows, total
