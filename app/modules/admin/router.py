from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.deps import require_admin
from app.modules.auth.models import User
from app.modules.admin import service, schemas
from app.modules.developers.schemas import DeveloperResponse
from app.modules.projects.models import Project
from app.modules.projects.schemas import ProjectResponse, ProjectCreate
from app.modules.buyers.models import Buyer
from app.modules.buyers.schemas import BuyerResponse
from app.modules.uploads.models import Upload
from app.modules.uploads.schemas import UploadResponse
from app.modules.admin.models import AuditLog, AdminIpAllowlist
from app.modules.admin.schemas import AuditLogResponse
from app.modules.developers.models import Developer
from app.modules.notifications.models import NotificationLog
from app.modules.milestones.models import Milestone
from app.modules.milestones.schemas import MilestoneResponse
from app.core.security import hash_password, verify_password
from app.core.exceptions import NotFoundError, ValidationError
from app.shared.response import ok, paginated

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/developers")
async def list_developers(
    request: Request,
    page: int = 1,
    limit: int = 20,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    developers, total = await service.list_developers(db, page, limit)
    return paginated(
        [DeveloperResponse.model_validate(d).model_dump() for d in developers],
        total, page, limit, request=request,
    )


@router.post("/developers", status_code=201)
async def create_developer(
    req: schemas.CreateDeveloperAdminRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    dev = await service.create_developer_admin(db, req)
    return ok(DeveloperResponse.model_validate(dev).model_dump(), request=request)


@router.patch("/developers/{developer_id}")
async def update_developer(
    developer_id: str,
    req: dict,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    dev = await service.update_developer_admin(db, developer_id, req)
    return ok(DeveloperResponse.model_validate(dev).model_dump(), request=request)


@router.delete("/developers/{developer_id}", status_code=204)
async def delete_developer(
    developer_id: str,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await service.soft_delete_developer(db, developer_id)


@router.patch("/developers/{developer_id}/subscription")
async def update_subscription(
    developer_id: str,
    req: schemas.SubscriptionUpdate,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    updates = req.model_dump(exclude_none=True)
    dev = await service.update_developer_admin(db, developer_id, updates)
    return ok(DeveloperResponse.model_validate(dev).model_dump(), request=request)


@router.get("/projects")
async def list_projects(
    request: Request,
    page: int = 1,
    limit: int = 20,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * limit
    # One query: projects + developer columns (join) + buyer_count (correlated subquery).
    from app.modules.developers.models import Developer
    from app.modules.buyers.models import Buyer
    buyer_count_sq = (
        select(func.count()).select_from(Buyer)
        .where(Buyer.project_id == Project.id, Buyer.deleted_at.is_(None))
        .correlate(Project).scalar_subquery()
    )
    result = await db.execute(
        select(
            Project,
            Developer.company_name,
            Developer.subscription_tier,
            Developer.subscription_status,
            buyer_count_sq.label("buyer_count"),
        )
        .outerjoin(Developer, Developer.id == Project.developer_id)
        .where(Project.deleted_at.is_(None))
        .order_by(Project.created_at.desc())
        .offset(offset).limit(limit)
    )
    count = (await db.execute(
        select(func.count()).select_from(Project).where(Project.deleted_at.is_(None))
    )).scalar_one()

    rows = []
    for proj, company_name, tier, sub_status, buyer_count in result.all():
        data = ProjectResponse.model_validate(proj).model_dump()
        data["developer_name"] = company_name
        data["subscription_tier"] = tier
        data["subscription_status"] = sub_status
        data["buyer_count"] = buyer_count or 0
        rows.append(data)

    return paginated(rows, count, page, limit, request=request)


@router.post("/projects", status_code=201)
async def create_project_admin(
    req: schemas.AdminProjectCreate,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from app.modules.projects.service import create_project
    from app.shared.audit import log_action
    
    project_create = ProjectCreate(
        name=req.name,
        location_name=req.location_name or "",
        site_latitude=req.site_latitude or 0.0,
        site_longitude=req.site_longitude or 0.0,
        total_units=req.total_units or 0,
        gps_radius_metres=req.gps_radius_metres
    )
    project = await create_project(db, req.developer_id, project_create)

    await log_action(
        db,
        actor_user_id=current_user.id,
        actor_role="admin",
        action="project.created.admin",
        entity_type="project",
        entity_id=project.id,
        developer_id=req.developer_id,
        after={"name": project.name, "project_code": project.project_code},
        request_id=getattr(request.state, "request_id", None),
    )

    return ok(ProjectResponse.model_validate(project).model_dump(), request=request)


@router.get("/buyers")
async def list_buyers(
    request: Request,
    page: int = 1,
    limit: int = 20,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * limit
    result = await db.execute(
        select(Buyer).where(Buyer.deleted_at.is_(None)).offset(offset).limit(limit)
    )
    buyers = result.scalars().all()
    count = (await db.execute(select(func.count()).select_from(Buyer).where(Buyer.deleted_at.is_(None)))).scalar_one()
    return paginated(
        [BuyerResponse.model_validate(b).model_dump() for b in buyers],
        count, page, limit, request=request,
    )


@router.get("/uploads")
async def list_uploads(
    request: Request,
    page: int = 1,
    limit: int = 20,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * limit
    rows_result, count = await _query_uploads(db, offset, limit)
    return paginated(_enrich_uploads(rows_result), count, page, limit, request=request)


async def _query_uploads(db: AsyncSession, offset: int, limit: int, where=None):
    """One joined query for uploads + project name + developer name (no N+1)."""
    from app.modules.developers.models import Developer
    stmt = (
        select(Upload, Project.name, Developer.company_name)
        .outerjoin(Project, Project.id == Upload.project_id)
        .outerjoin(Developer, Developer.id == Upload.developer_id)
    )
    count_stmt = select(func.count()).select_from(Upload)
    if where is not None:
        stmt = stmt.where(where)
        count_stmt = count_stmt.where(where)
    stmt = stmt.order_by(Upload.created_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(stmt)).all()
    count = (await db.execute(count_stmt)).scalar_one()
    return rows, count


def _enrich_uploads(rows):
    out = []
    for u, project_name, company_name in rows:
        data = UploadResponse.model_validate(u).model_dump()
        data["project_name"] = project_name
        data["developer_name"] = company_name
        data["gps_distance_meters"] = u.distance_from_site_m
        data["fanout_status"] = u.notification_fanout_status
        data["is_flagged"] = u.status == "flagged"
        data["caption"] = u.caption
        out.append(data)
    return out


@router.get("/uploads/pending")
async def list_pending_uploads(
    request: Request,
    page: int = 1,
    limit: int = 20,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """All uploads awaiting admin review."""
    offset = (page - 1) * limit
    rows_result, count = await _query_uploads(db, offset, limit, where=(Upload.status == "pending"))
    return paginated(_enrich_uploads(rows_result), count, page, limit, request=request)


@router.get("/uploads/flagged")
async def list_flagged_uploads(
    request: Request,
    page: int = 1,
    limit: int = 20,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Flagged or rejected uploads needing attention."""
    offset = (page - 1) * limit
    rows_result, count = await _query_uploads(db, offset, limit, where=Upload.status.in_(["flagged", "rejected"]))
    return paginated(_enrich_uploads(rows_result), count, page, limit, request=request)


@router.post("/uploads/{upload_id}/review")
async def review_upload(
    upload_id: str,
    req: schemas.AdminUploadReview,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime, timezone
    from app.core.exceptions import NotFoundError
    from app.shared.audit import log_action
    result = await db.execute(select(Upload).where(Upload.id == upload_id))
    upload = result.scalar_one_or_none()
    if not upload:
        raise NotFoundError("Upload not found")

    if req.action == "approve":
        upload.status = "approved"
        upload.gps_validated = True

        # Update project construction progress from the approved record
        project = (await db.execute(select(Project).where(Project.id == upload.project_id))).scalar_one_or_none()
        if project and upload.progress_at_upload is not None:
            if upload.progress_at_upload > (project.construction_progress or 0):
                project.construction_progress = upload.progress_at_upload
            # On a completion record that takes the project to 100, credit the developer
            if upload.progress_at_upload >= 100 or (upload.category == "Milestone Completed" and project.construction_progress >= 100):
                from app.modules.developers.models import Developer
                dev = (await db.execute(select(Developer).where(Developer.id == upload.developer_id))).scalar_one_or_none()
                if dev:
                    dev.projects_completed = (dev.projects_completed or 0) + 1
    elif req.action == "reject":
        upload.status = "rejected"
        upload.flag_reason = req.reason
        
        # Notify developer of rejection in background (if admin enabled it)
        from app.modules.settings.service import is_notification_enabled
        if await is_notification_enabled(db, "notify_developer_on_rejection"):
            import asyncio
            asyncio.create_task(_notify_developer_rejection(upload.id, req.reason))

    upload.reviewed_at = datetime.now(timezone.utc)
    upload.reviewed_by = current_user.id
    await db.commit()
    await db.refresh(upload)

    await log_action(
        db,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action=f"upload.{'approved' if req.action == 'approve' else 'rejected'}",
        entity_type="upload",
        entity_id=upload_id,
        developer_id=upload.developer_id,
        after={"status": upload.status, "reason": req.reason},
        request_id=getattr(request.state, "request_id", None),
    )

    # On approval, fan out buyer notifications if requested (best effort, after
    # commit) and only when the admin has buyer-approval emails enabled.
    if req.action == "approve" and req.send_notification:
        from app.modules.settings.service import is_notification_enabled
        if await is_notification_enabled(db, "notify_buyer_on_approval"):
            try:
                from app.modules.notifications.service import fanout_upload_notifications
                await fanout_upload_notifications(upload.id, db)
            except Exception:
                pass

    return ok(UploadResponse.model_validate(upload).model_dump(), request=request)


@router.get("/uploads/{upload_id}")
async def get_admin_upload_detail(
    upload_id: str,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Full upload detail for the admin review queue, including the actual
    photos with per-image GPS coordinates and capture timestamp."""
    from app.modules.uploads.models import Photo
    from app.shared.storage import get_signed_url

    upload = (await db.execute(select(Upload).where(Upload.id == upload_id))).scalar_one_or_none()
    if not upload:
        raise NotFoundError("Upload not found")

    photos = (await db.execute(
        select(Photo).where(Photo.upload_id == upload_id).order_by(Photo.order_index)
    )).scalars().all()

    data = UploadResponse.model_validate(upload).model_dump()
    data["photos"] = [
        {
            "id": p.id,
            "signed_url": get_signed_url(p.cloudinary_public_id),
            "capture_latitude": p.capture_latitude,
            "capture_longitude": p.capture_longitude,
            "created_at": p.created_at,
        }
        for p in photos
    ]
    return ok(data, request=request)


@router.post("/projects/{project_id}/independent-verification")
async def record_independent_verification(
    project_id: str,
    req: dict,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin records a third-party spot-check outcome on a project."""
    from datetime import datetime, timezone
    from app.core.exceptions import NotFoundError
    from app.shared.audit import log_action
    project = (await db.execute(select(Project).where(Project.id == project_id, Project.deleted_at.is_(None)))).scalar_one_or_none()
    if not project:
        raise NotFoundError("Project not found")
    project.independent_verification_enabled = True
    project.last_independent_verification_at = datetime.now(timezone.utc)
    project.last_independent_verifier_name = req.get("verifier_name")
    project.last_independent_verifier_outcome = req.get("outcome")  # passed, issues_noted, failed
    project.last_independent_verifier_notes = req.get("notes")
    await db.commit()
    await log_action(
        db, actor_user_id=current_user.id, actor_role="admin",
        action="project.independent_verification.recorded", entity_type="project", entity_id=project_id,
        developer_id=project.developer_id, after={"outcome": project.last_independent_verifier_outcome},
        request_id=getattr(request.state, "request_id", None),
    )
    return ok({
        "project_id": project_id,
        "independent_verification_enabled": project.independent_verification_enabled,
        "last_independent_verification_at": project.last_independent_verification_at.isoformat(),
        "last_independent_verifier_name": project.last_independent_verifier_name,
        "last_independent_verifier_outcome": project.last_independent_verifier_outcome,
        "last_independent_verifier_notes": project.last_independent_verifier_notes,
    }, request=request)


@router.get("/audit-log")
async def list_audit_log(
    request: Request,
    page: int = 1,
    limit: int = 50,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * limit
    result = await db.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
    )
    logs = result.scalars().all()
    count = (await db.execute(select(func.count()).select_from(AuditLog))).scalar_one()

    # Resolve actor emails in one batched query so the UI can show who did what.
    actor_ids = {l.actor_user_id for l in logs if l.actor_user_id}
    email_by_id: dict[str, str] = {}
    if actor_ids:
        rows = (await db.execute(select(User.id, User.email).where(User.id.in_(actor_ids)))).all()
        email_by_id = {r.id: r.email for r in rows}

    items = []
    for l in logs:
        data = AuditLogResponse.model_validate(l).model_dump()
        data["actor_email"] = email_by_id.get(l.actor_user_id)
        items.append(data)
    return paginated(items, count, page, limit, request=request)


@router.get("/stats")
async def get_stats(
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stats = await service.get_platform_stats(db)
    return ok(stats, request=request)


@router.get("/analytics")
async def get_analytics(
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return ok(await service.get_platform_analytics(db), request=request)


async def _notify_developer_rejection(upload_id: str, reason: str):
    from app.core.database import async_session_factory
    from sqlalchemy import select
    from app.modules.projects.models import Project
    from app.modules.developers.models import Developer
    from app.modules.auth.models import User
    from app.shared.email import send_email
    import logging

    try:
        async with async_session_factory() as db:
            from app.modules.uploads.models import Upload
            result = await db.execute(select(Upload).where(Upload.id == upload_id))
            upload = result.scalar_one_or_none()
            if not upload:
                return

            project = (await db.execute(select(Project).where(Project.id == upload.project_id))).scalar_one_or_none()
            dev = (await db.execute(select(Developer).where(Developer.id == upload.developer_id))).scalar_one_or_none()
            user = (await db.execute(select(User).where(User.id == dev.user_id))).scalar_one_or_none() if dev else None
            
            if not user:
                return

            project_name = project.name if project else "Unknown Project"
            company_name = dev.company_name if dev else "Developer"

            await send_email(
                to=user.email,
                subject=f"Upload Revision Required: {project_name}",
                template_name="developer_upload_rejected.html.j2",
                template_context={
                    "company_name": company_name,
                    "project_name": project_name,
                    "reason": reason,
                }
            )
    except Exception as e:
        logging.error(f"failed to send upload rejection email: {e}")


# ============================================================
# Notification log (frontend calls /admin/notifications)
# ============================================================
@router.get("/notifications")
async def list_notifications(
    request: Request,
    page: int = 1,
    limit: int = 20,
    status: str | None = None,
    channel: str | None = None,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * limit
    stmt = select(NotificationLog)
    count_stmt = select(func.count()).select_from(NotificationLog)
    if status:
        stmt = stmt.where(NotificationLog.status == status)
        count_stmt = count_stmt.where(NotificationLog.status == status)
    if channel:
        stmt = stmt.where(NotificationLog.notification_type == channel)
        count_stmt = count_stmt.where(NotificationLog.notification_type == channel)
    stmt = stmt.order_by(NotificationLog.created_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    count = (await db.execute(count_stmt)).scalar_one()
    data = [
        {
            "id": n.id,
            "recipient_email": n.recipient_email,
            "channel": n.notification_type,
            "subject": n.subject,
            "template_name": n.template_name,
            "status": n.status,
            "error_message": n.error_message,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in rows
    ]
    return paginated(data, count, page, limit, request=request)


# ============================================================
# Subscriptions (developers viewed through a billing lens)
# ============================================================
@router.get("/subscriptions")
async def list_subscriptions(
    request: Request,
    page: int = 1,
    limit: int = 20,
    status: str | None = None,
    tier: str | None = None,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * limit
    stmt = select(Developer).where(Developer.deleted_at.is_(None))
    count_stmt = select(func.count()).select_from(Developer).where(Developer.deleted_at.is_(None))
    if status:
        stmt = stmt.where(Developer.subscription_status == status)
        count_stmt = count_stmt.where(Developer.subscription_status == status)
    if tier:
        stmt = stmt.where(Developer.subscription_tier == tier)
        count_stmt = count_stmt.where(Developer.subscription_tier == tier)
    stmt = stmt.order_by(Developer.created_at.desc()).offset(offset).limit(limit)
    devs = (await db.execute(stmt)).scalars().all()
    count = (await db.execute(count_stmt)).scalar_one()
    data = [
        {
            "developer_id": d.id,
            "developer_name": d.company_name,
            "tier": d.subscription_tier,
            "status": d.subscription_status,
            "trial_ends_at": d.trial_ends_at.isoformat() if d.trial_ends_at else None,
            "current_period_end": d.subscription_expires_at.isoformat() if d.subscription_expires_at else None,
            "storage_used_mb": 0,
        }
        for d in devs
    ]
    return paginated(data, count, page, limit, request=request)


# ============================================================
# Admin IP allow-list CRUD (frontend uses cidr/label aliases)
# ============================================================
@router.get("/settings/ip-allowlist")
async def list_ip_allowlist(
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(select(AdminIpAllowlist).order_by(AdminIpAllowlist.created_at.desc()))).scalars().all()
    data = [{"id": r.id, "cidr": r.ip_address, "label": r.description} for r in rows]
    return ok(data, request=request)


@router.post("/settings/ip-allowlist", status_code=201)
async def add_ip_allowlist(
    req: dict,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    cidr = (req.get("cidr") or "").strip()
    if not cidr:
        raise ValidationError("cidr is required")
    entry = AdminIpAllowlist(ip_address=cidr, description=req.get("label"))
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return ok({"id": entry.id, "cidr": entry.ip_address, "label": entry.description}, request=request)


@router.delete("/settings/ip-allowlist/{ip_id}", status_code=204)
async def delete_ip_allowlist(
    ip_id: str,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    entry = (await db.execute(select(AdminIpAllowlist).where(AdminIpAllowlist.id == ip_id))).scalar_one_or_none()
    if not entry:
        raise NotFoundError("IP allow-list entry not found")
    await db.delete(entry)
    await db.commit()


# ============================================================
# Admin profile (name + optional password change)
# ============================================================
@router.patch("/profile")
async def update_admin_profile(
    req: dict,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user = (await db.execute(select(User).where(User.id == current_user.id))).scalar_one()
    if req.get("full_name"):
        user.full_name = req["full_name"].strip()
    new_password = req.get("new_password")
    if new_password:
        current_password = req.get("current_password") or ""
        if not verify_password(current_password, user.hashed_password):
            raise ValidationError("Current password is incorrect")
        if len(new_password) < 8:
            raise ValidationError("New password must be at least 8 characters")
        user.hashed_password = hash_password(new_password)
    await db.commit()
    await db.refresh(user)
    return ok({"id": user.id, "full_name": user.full_name, "email": user.email}, request=request)


# ============================================================
# Buyer removal (soft delete)
# ============================================================
@router.delete("/buyers/{buyer_id}", status_code=204)
async def delete_buyer(
    buyer_id: str,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime, timezone
    buyer = (await db.execute(select(Buyer).where(Buyer.id == buyer_id, Buyer.deleted_at.is_(None)))).scalar_one_or_none()
    if not buyer:
        raise NotFoundError("Buyer not found")
    buyer.deleted_at = datetime.now(timezone.utc)
    await db.commit()


# ============================================================
# Project milestones (admin, cross-tenant)
# ============================================================
@router.get("/projects/{project_id}/milestones")
async def admin_project_milestones(
    project_id: str,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(Milestone).where(Milestone.project_id == project_id).order_by(Milestone.order_index)
    )).scalars().all()
    return ok([MilestoneResponse.model_validate(m).model_dump() for m in rows], request=request)


# ============================================================
# Developer detail (admin)
# ============================================================
@router.get("/developers/{developer_id}")
async def get_developer_detail(
    developer_id: str,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    dev = (await db.execute(
        select(Developer).where(Developer.id == developer_id, Developer.deleted_at.is_(None))
    )).scalar_one_or_none()
    if not dev:
        raise NotFoundError("Developer not found")
    project_count = (await db.execute(
        select(func.count()).select_from(Project).where(
            Project.developer_id == developer_id, Project.deleted_at.is_(None)
        )
    )).scalar_one()
    buyer_count = (await db.execute(
        select(func.count()).select_from(Buyer)
        .join(Project, Project.id == Buyer.project_id)
        .where(Project.developer_id == developer_id, Buyer.deleted_at.is_(None))
    )).scalar_one()
    data = {
        "id": dev.id,
        "user_id": dev.user_id,
        "company_name": dev.company_name,
        "contact_person_name": dev.contact_name,
        "contact_phone": getattr(dev, "contact_phone", None),
        "company_description": dev.company_overview,
        "years_operating": dev.years_operating,
        "projects_completed": dev.projects_completed,
        "website": dev.website,
        "address": dev.address,
        "logo_url": dev.logo_url,
        "subscription_tier": dev.subscription_tier,
        "subscription_status": dev.subscription_status,
        "subscription_expires_at": dev.subscription_expires_at.isoformat() if dev.subscription_expires_at else None,
        "trial_ends_at": dev.trial_ends_at.isoformat() if dev.trial_ends_at else None,
        "project_count": project_count,
        "buyer_count": buyer_count,
        "created_at": dev.created_at.isoformat() if dev.created_at else None,
    }
    return ok(data, request=request)


# ============================================================
# Project detail (admin)
# ============================================================
@router.get("/projects/{project_id}")
async def get_project_detail(
    project_id: str,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    proj = (await db.execute(
        select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
    )).scalar_one_or_none()
    if not proj:
        raise NotFoundError("Project not found")
    dev = (await db.execute(select(Developer).where(Developer.id == proj.developer_id))).scalar_one_or_none()
    buyer_count = (await db.execute(
        select(func.count()).select_from(Buyer).where(
            Buyer.project_id == project_id, Buyer.deleted_at.is_(None)
        )
    )).scalar_one()
    milestone_count = (await db.execute(
        select(func.count()).select_from(Milestone).where(Milestone.project_id == project_id)
    )).scalar_one()
    completed_milestones = (await db.execute(
        select(func.count()).select_from(Milestone).where(
            Milestone.project_id == project_id, Milestone.status == "complete"
        )
    )).scalar_one()
    data = {
        "id": proj.id,
        "name": proj.name,
        "status": proj.status,
        "location": proj.location_name,
        "total_units": proj.total_units or 0,
        "project_code": proj.project_code,
        "developer_id": proj.developer_id,
        "developer_name": dev.company_name if dev else None,
        "buyer_count": buyer_count,
        "milestone_count": milestone_count,
        "completed_milestones": completed_milestones,
        "construction_progress": proj.construction_progress,
        "created_at": proj.created_at.isoformat() if proj.created_at else None,
    }
    return ok(data, request=request)
