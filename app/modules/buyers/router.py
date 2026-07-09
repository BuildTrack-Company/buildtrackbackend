from fastapi import APIRouter, Depends, Request, UploadFile, File
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


@router.post("/projects/{project_id}/buyers/invite", status_code=201, dependencies=[require_permission("buyers", "invite")])
async def invite_buyer(
    project_id: str,
    req: schemas.BuyerInviteRequest,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    buyer = await service.invite_buyer(db, project_id, ctx.developer_id, req)
    return ok(schemas.BuyerResponse.model_validate(buyer).model_dump(), request=request)


@router.post("/projects/{project_id}/buyers/bulk-invite", status_code=201, dependencies=[require_permission("buyers", "invite")])
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


# ─── Project units (for buyer self-registration validation) ──────────────────

@router.get("/projects/{project_id}/units", dependencies=[require_permission("buyers", "read")])
async def list_units(
    project_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    units = await service.list_project_units(db, project_id, ctx.developer_id)
    return ok(units, request=request)


@router.post("/projects/{project_id}/units", status_code=201, dependencies=[require_permission("buyers", "invite")])
async def add_unit(
    project_id: str,
    req: schemas.AddUnitRequest,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    unit = await service.add_project_unit(db, project_id, ctx.developer_id, req.unit_number)
    return ok(unit, request=request)


@router.delete("/projects/{project_id}/units/{unit_id}", status_code=204, dependencies=[require_permission("buyers", "invite")])
async def delete_unit(
    project_id: str,
    unit_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    await service.delete_project_unit(db, unit_id, project_id, ctx.developer_id)


@router.post("/projects/{project_id}/buyers/{buyer_id}/resend", dependencies=[require_permission("buyers", "invite")])
async def resend_invitation(
    project_id: str,
    buyer_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    buyer = await service.resend_invitation(db, buyer_id, project_id, ctx.developer_id)
    return ok(schemas.BuyerResponse.model_validate(buyer).model_dump(), request=request)


@router.patch("/projects/{project_id}/buyers/{buyer_id}", dependencies=[require_permission("buyers", "update")])
async def update_buyer(
    project_id: str,
    buyer_id: str,
    req: schemas.BuyerUpdateRequest,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    buyer = await service.update_buyer(db, buyer_id, project_id, ctx.developer_id, req)
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

    # Single joined query for buyer + project + developer (saves 2 round-trips).
    row = (await db.execute(
        select(Buyer, Project, Developer)
        .join(Project, Project.id == Buyer.project_id)
        .outerjoin(Developer, Developer.id == Project.developer_id)
        .where(
            Buyer.user_id == current_user.id,
            Buyer.deleted_at.is_(None),
            Project.deleted_at.is_(None),
        )
    )).first()
    if not row:
        raise NotFoundError("Buyer profile not found")
    buyer, project, developer = row

    # Record buyer activity (shown as "last active" in developer + admin portals).
    from datetime import datetime as _dt, timezone as _tz
    buyer.last_active_at = _dt.now(_tz.utc)
    await db.commit()

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
    photos_by_upload: dict[str, list] = {}
    if upload_ids:
        photo_rows = (await db.execute(
            select(Photo).where(Photo.upload_id.in_(upload_ids)).order_by(Photo.created_at.desc())
        )).scalars().all()
        for ph in photo_rows:
            try:
                url = get_signed_url(ph.cloudinary_public_id, "display")
                thumb = get_signed_url(ph.cloudinary_public_id, "thumbnail")
            except Exception:
                url = ph.cloudinary_url
                thumb = ph.cloudinary_url
            entry = {
                "id": ph.id, "url": url, "thumbnail_url": thumb,
                "caption": None,
                "latitude": ph.capture_latitude, "longitude": ph.capture_longitude,
                "captured_at": ph.created_at.isoformat() if ph.created_at else None,
            }
            photos_by_upload.setdefault(ph.upload_id, []).append(entry)
            if len(photos) < 40:
                photos.append(entry)

    updates = [{
        "id": u.id,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "title": u.title,
        "category": u.category,
        "milestone_name": milestone_names.get(u.milestone_id) or u.title or u.category or "Update",
        "note": u.caption,
        "progress_at_upload": u.progress_at_upload,
        "latitude": u.capture_latitude,
        "longitude": u.capture_longitude,
        "photo_count": u.photo_count or 0,
        "photos": photos_by_upload.get(u.id, []),
    } for u in uploads]

    # Construction health: overdue if no approved update within the agreed cadence
    from datetime import datetime, timezone
    threshold_days = project.activity_overdue_threshold_days or 14
    last_update_at = max((u.created_at for u in uploads if u.created_at), default=None)
    if last_update_at is not None:
        ref = last_update_at if last_update_at.tzinfo else last_update_at.replace(tzinfo=timezone.utc)
        days_since_update = (datetime.now(timezone.utc) - ref).days
    else:
        days_since_update = None
    is_overdue = days_since_update is not None and days_since_update > threshold_days
    delay_count = sum(1 for m in milestones if m.status == "delayed")

    payload = {
        "id": project.id,
        "name": project.name,
        "project_code": project.project_code,
        "status": project.status,
        "developer_company": developer.company_name if developer else None,
        "developer_years_operating": developer.years_operating if developer else None,
        "developer_projects_completed": developer.projects_completed if developer else None,
        "developer_active_developments": developer.active_developments if developer else None,
        "developer_avg_update_frequency_days": developer.avg_update_frequency_days if developer else None,
        "developer_update_consistency_pct": developer.update_consistency_pct if developer else None,
        "developer_description": developer.company_overview if developer else None,
        "location_label": project.location_name,
        "unit_count": project.total_units or 0,
        "unit_number": buyer.unit_number,
        # Derived from milestones (completed / total) so the bar matches every
        # other portal and can't be hand-set by the developer.
        "construction_progress": round(
            sum(1 for m in milestones if m.status == "complete") / len(milestones) * 100
        ) if milestones else 0,
        "health_status": project.health_status,
        "construction_health": "overdue" if is_overdue else "on_track",
        "update_frequency_days": threshold_days,
        "days_since_last_update": days_since_update,
        "delay_count": delay_count,
        "notifications_enabled": buyer.notification_email,
        "milestones": [{
            "id": m.id, "name": m.name, "order": m.order_index, "status": m.status,
            "planned_date": m.expected_date.isoformat() if m.expected_date else None,
            "actual_date": m.completed_at.isoformat() if m.completed_at else None,
            "revised_date": m.delay_new_date.isoformat() if m.delay_new_date else None,
            "delay_reason": m.delay_reason,
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


@router.post("/projects/{project_id}/buyers/csv", status_code=201, dependencies=[require_permission("buyers", "invite")])
async def import_buyers_csv(
    project_id: str,
    request: Request,
    file: UploadFile = File(...),
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    """Bulk-invite buyers from an uploaded CSV.

    Accepts the documented column order (Full Name, Email, Phone, Unit Number)
    whether or not a header row is present, and tolerates natural header spellings
    like "Email Address". Only email is required per row.
    """
    import csv as _csv
    import io
    import re

    raw = (await file.read()).decode("utf-8-sig", errors="ignore")
    email_re = re.compile(r"[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+")

    def _norm(s: str) -> str:
        # Normalise a header so "Full Name", "full_name" and "full-name" all match.
        return "".join(ch for ch in (s or "").strip().lower() if ch.isalnum())

    known_headers = {
        "email", "emailaddress", "name", "fullname", "buyername",
        "phone", "phonenumber", "mobile", "mobilenumber", "tel",
        "unit", "unitnumber", "unitno", "housenumber",
    }

    all_rows = [r for r in _csv.reader(io.StringIO(raw)) if any((c or "").strip() for c in r)]
    if not all_rows:
        from app.core.exceptions import ValidationError
        raise ValidationError("The CSV file appears to be empty")

    first = all_rows[0]
    # A first row is a header only if it names a known column and holds no email value.
    has_header = (
        any(_norm(c) in known_headers for c in first)
        and not any(email_re.search(c or "") for c in first)
    )
    if has_header:
        headers = [c for c in first]
        body_rows = all_rows[1:]
        start_line = 2
    else:
        # Headerless file: map by position per the documented order.
        headers = ["full_name", "email", "phone", "unit_number"]
        body_rows = all_rows
        start_line = 1

    items: list[schemas.BuyerInviteRequest] = []
    parse_errors: list[str] = []

    def pick(row: dict, *keys: str) -> str | None:
        wanted = {_norm(k) for k in keys}
        for rk, rv in row.items():
            if rk and _norm(rk) in wanted:
                v = (rv or "").strip()
                if v:
                    return v
        return None

    for i, cols in enumerate(body_rows, start=start_line):
        row = dict(zip(headers, cols))
        email = pick(row, "email", "e-mail", "email address", "emailaddress")
        if not email:
            # Rescue: accept any cell that clearly holds an email address.
            email = next((c.strip() for c in cols if c and email_re.search(c)), None)
        if not email:
            continue
        try:
            items.append(schemas.BuyerInviteRequest(
                email=email,
                full_name=pick(row, "name", "full_name", "fullname", "full name", "buyer name"),
                phone=pick(row, "phone", "phone_number", "phone number", "mobile", "mobile number", "tel"),
                unit_number=pick(row, "unit", "unit_number", "unit number", "unit_no", "house number"),
            ))
        except Exception as e:  # noqa: BLE001
            parse_errors.append(f"Row {i}: {e}")

    if not items:
        from app.core.exceptions import ValidationError
        raise ValidationError(
            "No valid buyer rows found. Use columns: Full Name, Email, Phone, Unit Number."
        )

    buyers, errors = await service.bulk_invite_buyers(
        db, project_id, ctx.developer_id, schemas.BulkInviteRequest(buyers=items)
    )
    return ok(
        {
            "invited": [schemas.BuyerResponse.model_validate(b).model_dump() for b in buyers],
            "errors": parse_errors + list(errors),
        },
        request=request,
    )
