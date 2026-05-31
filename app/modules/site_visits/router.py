from datetime import datetime, timezone, date
from typing import Optional
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import structlog

from app.core.database import get_db
from app.core.deps import require_developer, require_admin, require_buyer
from app.core.exceptions import NotFoundError, ValidationError
from app.modules.auth.models import User
from app.modules.projects.models import Project
from app.modules.site_visits.models import SiteVisitRequest, SITE_VISIT_STATUSES, TIME_SLOTS
from app.shared.response import ok, paginated
from app.shared.ids import new_id
from app.shared.audit import log_action

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["site-visits"])


class SiteVisitCreate(BaseModel):
    full_name: str
    email: EmailStr
    phone: str
    requested_date: date
    preferred_time_slot: Optional[str] = None
    party_size: int = 1
    purpose: Optional[str] = None

    @field_validator("preferred_time_slot")
    @classmethod
    def _slot(cls, v):
        if v and v not in TIME_SLOTS:
            raise ValueError(f"preferred_time_slot must be one of: {', '.join(TIME_SLOTS)}")
        return v


class SiteVisitUpdate(BaseModel):
    status: Optional[str] = None
    confirmed_datetime: Optional[datetime] = None
    developer_notes: Optional[str] = None
    cancellation_reason: Optional[str] = None

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        if v and v not in SITE_VISIT_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(SITE_VISIT_STATUSES)}")
        return v


def _serialize(sv: SiteVisitRequest) -> dict:
    return {
        "id": sv.id, "project_id": sv.project_id, "developer_id": sv.developer_id,
        "full_name": sv.full_name, "email": sv.email, "phone": sv.phone,
        "requested_date": sv.requested_date.isoformat() if sv.requested_date else None,
        "preferred_time_slot": sv.preferred_time_slot, "party_size": sv.party_size,
        "purpose": sv.purpose, "status": sv.status,
        "confirmed_datetime": sv.confirmed_datetime.isoformat() if sv.confirmed_datetime else None,
        "developer_notes": sv.developer_notes, "cancellation_reason": sv.cancellation_reason,
        "created_at": sv.created_at.isoformat() if sv.created_at else None,
    }


async def _create(db, project, req, requester_user_id):
    sv = SiteVisitRequest(
        id=new_id(), project_id=project.id, developer_id=project.developer_id,
        requester_user_id=requester_user_id, full_name=req.full_name, email=str(req.email),
        phone=req.phone, requested_date=req.requested_date,
        preferred_time_slot=req.preferred_time_slot, party_size=max(1, req.party_size),
        purpose=req.purpose, status="requested",
        created_at=datetime.now(timezone.utc),
    )
    db.add(sv)
    await db.commit()
    await db.refresh(sv)
    return sv


# ── Public: prospective buyer requests a visit via the visibility page ────────
@router.post("/public/projects/{slug}/site-visits", status_code=201)
async def public_request_visit(slug: str, req: SiteVisitCreate, request: Request, db: AsyncSession = Depends(get_db)):
    project = (await db.execute(
        select(Project).where(Project.slug == slug, Project.visibility_page_published == True, Project.deleted_at.is_(None))  # noqa: E712
    )).scalar_one_or_none()
    if not project:
        raise NotFoundError("Project not found")
    sv = await _create(db, project, req, None)
    await log_action(db, actor_user_id="public", actor_role="prospective_buyer",
                     action="site_visit.requested", entity_type="site_visit", entity_id=sv.id,
                     developer_id=project.developer_id)
    return ok(_serialize(sv), request=request)


# ── Registered buyer requests a visit ─────────────────────────────────────────
@router.post("/buyer/site-visits", status_code=201)
async def buyer_request_visit(req: SiteVisitCreate, request: Request,
                              current_user: User = Depends(require_buyer), db: AsyncSession = Depends(get_db)):
    from app.modules.buyers.models import Buyer
    buyer = (await db.execute(select(Buyer).where(Buyer.user_id == current_user.id, Buyer.deleted_at.is_(None)))).scalars().first()
    if not buyer:
        raise NotFoundError("No project associated with this buyer")
    project = (await db.execute(select(Project).where(Project.id == buyer.project_id))).scalar_one_or_none()
    if not project:
        raise NotFoundError("Project not found")
    sv = await _create(db, project, req, current_user.id)
    await log_action(db, actor_user_id=current_user.id, actor_role="buyer",
                     action="site_visit.requested", entity_type="site_visit", entity_id=sv.id,
                     developer_id=project.developer_id)
    return ok(_serialize(sv), request=request)


# ── Developer inbox ───────────────────────────────────────────────────────────
@router.get("/developers/me/site-visits")
async def list_developer_visits(request: Request, status: Optional[str] = None, page: int = 1, limit: int = 20,
                                current_user: User = Depends(require_developer), db: AsyncSession = Depends(get_db)):
    from app.modules.developers import service as dev_service
    dev = await dev_service.get_developer_by_user_id(db, current_user.id)
    q = select(SiteVisitRequest).where(SiteVisitRequest.developer_id == dev.id)
    cq = select(func.count()).select_from(SiteVisitRequest).where(SiteVisitRequest.developer_id == dev.id)
    if status:
        q = q.where(SiteVisitRequest.status == status)
        cq = cq.where(SiteVisitRequest.status == status)
    offset = (page - 1) * limit
    rows = (await db.execute(q.order_by(SiteVisitRequest.created_at.desc()).offset(offset).limit(limit))).scalars().all()
    total = (await db.execute(cq)).scalar_one()
    return paginated([_serialize(s) for s in rows], total, page, limit, request=request)


@router.patch("/developers/me/site-visits/{visit_id}")
async def update_developer_visit(visit_id: str, req: SiteVisitUpdate, request: Request,
                                 current_user: User = Depends(require_developer), db: AsyncSession = Depends(get_db)):
    from app.modules.developers import service as dev_service
    dev = await dev_service.get_developer_by_user_id(db, current_user.id)
    sv = (await db.execute(select(SiteVisitRequest).where(
        SiteVisitRequest.id == visit_id, SiteVisitRequest.developer_id == dev.id
    ))).scalar_one_or_none()
    if not sv:
        raise NotFoundError("Site visit request not found")
    for field, value in req.model_dump(exclude_none=True).items():
        setattr(sv, field, value)
    await db.commit()
    await db.refresh(sv)
    await log_action(db, actor_user_id=current_user.id, actor_role="developer",
                     action="site_visit.updated", entity_type="site_visit", entity_id=sv.id,
                     developer_id=dev.id, after={"status": sv.status})
    return ok(_serialize(sv), request=request)


# ── Admin overview ─────────────────────────────────────────────────────────────
@router.get("/admin/site-visits")
async def list_all_visits(request: Request, page: int = 1, limit: int = 50,
                          current_user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    offset = (page - 1) * limit
    rows = (await db.execute(
        select(SiteVisitRequest).order_by(SiteVisitRequest.created_at.desc()).offset(offset).limit(limit)
    )).scalars().all()
    total = (await db.execute(select(func.count()).select_from(SiteVisitRequest))).scalar_one()
    return paginated([_serialize(s) for s in rows], total, page, limit, request=request)
