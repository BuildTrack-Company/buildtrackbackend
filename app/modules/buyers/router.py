from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_tenant_context, TenantContext, require_buyer, get_current_user, require_permission
from app.modules.auth.models import User
from app.modules.buyers import service, schemas
from app.shared.response import ok

router = APIRouter(tags=["buyers"])


@router.get("/projects/{project_id}/buyers", dependencies=[require_permission("buyers", "read")])
async def list_buyers(
    project_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    buyers = await service.list_buyers(db, project_id, ctx.developer_id)
    return ok([schemas.BuyerResponse.model_validate(b).model_dump() for b in buyers], request=request)


@router.post("/projects/{project_id}/buyers/invite", status_code=201, dependencies=[require_permission("buyers", "create")])
async def invite_buyer(
    project_id: str,
    req: schemas.BuyerInviteRequest,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    buyer = await service.invite_buyer(db, project_id, ctx.developer_id, req)
    return ok(schemas.BuyerResponse.model_validate(buyer).model_dump(), request=request)


@router.post("/projects/{project_id}/buyers/bulk-invite", status_code=201, dependencies=[require_permission("buyers", "create")])
async def bulk_invite_buyers(
    project_id: str,
    req: schemas.BulkInviteRequest,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    buyers, errors = await service.bulk_invite_buyers(db, project_id, ctx.developer_id, req)
    return ok(
        {
            "invited": [schemas.BuyerResponse.model_validate(b).model_dump() for b in buyers],
            "errors": errors,
        },
        request=request,
    )


@router.post("/projects/{project_id}/buyers/{buyer_id}/resend", dependencies=[require_permission("buyers", "create")])
async def resend_invitation(
    project_id: str,
    buyer_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    buyer = await service.resend_invitation(db, buyer_id, project_id, ctx.developer_id)
    return ok(schemas.BuyerResponse.model_validate(buyer).model_dump(), request=request)


@router.delete("/projects/{project_id}/buyers/{buyer_id}", status_code=204, dependencies=[require_permission("buyers", "delete")])
async def remove_buyer(
    project_id: str,
    buyer_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    await service.remove_buyer(db, buyer_id, project_id, ctx.developer_id)


# Buyer self-service routes
@router.get("/buyer/project")
async def get_buyer_project(
    request: Request,
    current_user: User = Depends(require_buyer),
    db: AsyncSession = Depends(get_db),
):
    """Get the buyer's assigned project: header, milestones, photos and update feed.
    Shaped to match the buyer dashboard contract (developer_company, photos, updates...)."""
    from sqlalchemy import select
    from app.modules.buyers.models import Buyer
    from app.modules.projects.models import Project
    from app.modules.developers.models import Developer
    from app.modules.milestones.models import Milestone
    from app.modules.uploads.models import Upload, Photo
    from app.shared.storage import get_signed_url
    from app.core.exceptions import NotFoundError

    buyer = (await db.execute(
        select(Buyer).where(Buyer.user_id == current_user.id, Buyer.deleted_at.is_(None))
    )).scalar_one_or_none()
    if not buyer:
        raise NotFoundError("Buyer profile not found")

    project = (await db.execute(
        select(Project).where(Project.id == buyer.project_id, Project.deleted_at.is_(None))
    )).scalar_one_or_none()
    if not project:
        raise NotFoundError("Project not found")

    developer = (await db.execute(
        select(Developer).where(Developer.id == project.developer_id)
    )).scalar_one_or_none()

    milestones = (await db.execute(
        select(Milestone).where(Milestone.project_id == project.id).order_by(Milestone.order_index)
    )).scalars().all()

    uploads = (await db.execute(
        select(Upload).where(
            Upload.project_id == project.id, Upload.status == "approved",
        ).order_by(Upload.created_at.desc()).limit(20)
    )).scalars().all()
    milestone_names = {m.id: m.name for m in milestones}

    # Photos for the gallery (signed Cloudinary URLs), newest first.
    upload_ids = [u.id for u in uploads]
    photos = []
    if upload_ids:
        photo_rows = (await db.execute(
            select(Photo).where(Photo.upload_id.in_(upload_ids)).order_by(Photo.created_at.desc())
        )).scalars().all()
        for ph in photo_rows[:40]:
            try:
                url = get_signed_url(ph.cloudinary_public_id, "display")
                thumb = get_signed_url(ph.cloudinary_public_id, "thumbnail")
            except Exception:
                url = ph.cloudinary_url
                thumb = ph.cloudinary_url
            photos.append({
                "id": ph.id, "url": url, "thumbnail_url": thumb,
                "caption": None,
                "latitude": ph.capture_latitude, "longitude": ph.capture_longitude,
                "captured_at": ph.created_at.isoformat() if ph.created_at else None,
            })

    updates = [{
        "id": u.id,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "milestone_name": milestone_names.get(u.milestone_id) or u.title or u.category or "Update",
        "note": u.caption,
        "photo_count": u.photo_count or 0,
    } for u in uploads]

    payload = {
        "id": project.id,
        "name": project.name,
        "status": project.status,
        "developer_company": developer.company_name if developer else None,
        "developer_years_operating": developer.years_operating if developer else None,
        "developer_projects_completed": developer.projects_completed if developer else None,
        "developer_description": developer.company_description if developer else None,
        "location_label": project.location_name,
        "unit_count": project.total_units or 0,
        "unit_number": buyer.unit_number,
        "construction_progress": project.construction_progress,
        "health_status": project.health_status,
        "notifications_enabled": buyer.notification_email,
        "milestones": [{
            "id": m.id, "name": m.name, "order": m.order_index, "status": m.status,
            "planned_date": m.expected_date.isoformat() if m.expected_date else None,
            "actual_date": m.completed_at.isoformat() if m.completed_at else None,
        } for m in milestones],
        "photos": photos,
        "updates": updates,
    }
    return ok(payload, request=request)


async def _buyer_and_project(db, user_id):
    from sqlalchemy import select
    from app.modules.buyers.models import Buyer
    from app.modules.projects.models import Project
    from app.core.exceptions import NotFoundError
    buyer = (await db.execute(select(Buyer).where(Buyer.user_id == user_id, Buyer.deleted_at.is_(None)))).scalar_one_or_none()
    if not buyer:
        raise NotFoundError("Buyer profile not found")
    project = (await db.execute(select(Project).where(Project.id == buyer.project_id, Project.deleted_at.is_(None)))).scalar_one_or_none()
    if not project:
        raise NotFoundError("Project not found")
    return buyer, project


@router.get("/buyer/milestones/pending-approval")
async def buyer_pending_milestone_approvals(
    request: Request,
    current_user: User = Depends(require_buyer),
    db: AsyncSession = Depends(get_db),
):
    """Completed milestones in the buyer's project that this buyer has not yet signed off."""
    from sqlalchemy import select
    from app.modules.milestones.models import Milestone, MilestoneApproval
    from app.modules.milestones.schemas import MilestoneResponse
    _buyer, project = await _buyer_and_project(db, current_user.id)
    milestones = (await db.execute(
        select(Milestone).where(Milestone.project_id == project.id, Milestone.status == "complete").order_by(Milestone.order_index)
    )).scalars().all()
    approved_ids = set((await db.execute(
        select(MilestoneApproval.milestone_id).where(MilestoneApproval.buyer_user_id == current_user.id)
    )).scalars().all())
    pending = [MilestoneResponse.model_validate(m).model_dump() for m in milestones if m.id not in approved_ids]
    return ok(pending, request=request)


@router.post("/buyer/milestones/{milestone_id}/approve")
async def buyer_approve_milestone(
    milestone_id: str,
    request: Request,
    current_user: User = Depends(require_buyer),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.modules.milestones.models import Milestone, MilestoneApproval
    from app.core.exceptions import NotFoundError
    from app.shared.audit import log_action
    from app.shared.ids import new_id
    _buyer, project = await _buyer_and_project(db, current_user.id)
    ms = (await db.execute(select(Milestone).where(Milestone.id == milestone_id, Milestone.project_id == project.id))).scalar_one_or_none()
    if not ms:
        raise NotFoundError("Milestone not found")
    db.add(MilestoneApproval(
        id=new_id(), milestone_id=milestone_id, buyer_user_id=current_user.id,
        decision="approved", decided_at=datetime.now(timezone.utc),
    ))
    await db.commit()
    await log_action(db, actor_user_id=current_user.id, actor_role="buyer",
                     action="milestone.buyer_approved", entity_type="milestone", entity_id=milestone_id,
                     developer_id=project.developer_id)
    return ok({"milestone_id": milestone_id, "decision": "approved"}, request=request)


@router.post("/buyer/milestones/{milestone_id}/request-clarification")
async def buyer_request_clarification(
    milestone_id: str,
    req: dict,
    request: Request,
    current_user: User = Depends(require_buyer),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.modules.milestones.models import Milestone, MilestoneApproval
    from app.core.exceptions import NotFoundError
    from app.shared.audit import log_action
    from app.shared.ids import new_id
    _buyer, project = await _buyer_and_project(db, current_user.id)
    ms = (await db.execute(select(Milestone).where(Milestone.id == milestone_id, Milestone.project_id == project.id))).scalar_one_or_none()
    if not ms:
        raise NotFoundError("Milestone not found")
    db.add(MilestoneApproval(
        id=new_id(), milestone_id=milestone_id, buyer_user_id=current_user.id,
        decision="clarification_requested", reason=req.get("reason"), decided_at=datetime.now(timezone.utc),
    ))
    await db.commit()
    await log_action(db, actor_user_id=current_user.id, actor_role="buyer",
                     action="milestone.clarification_requested", entity_type="milestone", entity_id=milestone_id,
                     developer_id=project.developer_id, after={"reason": req.get("reason")})
    return ok({"milestone_id": milestone_id, "decision": "clarification_requested"}, request=request)


@router.get("/buyer/notifications/preferences")
async def get_notification_preferences(
    request: Request,
    current_user: User = Depends(require_buyer),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    from app.modules.buyers.models import Buyer

    result = await db.execute(
        select(Buyer).where(
            Buyer.user_id == current_user.id,
            Buyer.deleted_at.is_(None),
        )
    )
    buyer = result.scalar_one_or_none()
    if not buyer:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("Buyer profile not found")

    return ok({
        "notification_email": buyer.notification_email,
        "notification_sms": buyer.notification_sms,
        "notification_whatsapp": buyer.notification_whatsapp,
    }, request=request)


@router.patch("/buyer/notifications/preferences")
async def update_notification_preferences(
    req: schemas.NotificationPreferencesUpdate,
    request: Request,
    current_user: User = Depends(require_buyer),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    from app.modules.buyers.models import Buyer

    result = await db.execute(
        select(Buyer).where(
            Buyer.user_id == current_user.id,
            Buyer.deleted_at.is_(None),
        )
    )
    buyer = result.scalar_one_or_none()
    if not buyer:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("Buyer profile not found")

    for field, value in req.model_dump(exclude_none=True).items():
        setattr(buyer, field, value)
    await db.commit()
    await db.refresh(buyer)

    return ok({
        "notification_email": buyer.notification_email,
        "notification_sms": buyer.notification_sms,
        "notification_whatsapp": buyer.notification_whatsapp,
    }, request=request)
