from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional
from pydantic import BaseModel

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
    search: Optional[str] = None,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    developers, total = await service.list_developers(db, page, limit, search=search)
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
    for proj, company_name, buyer_count in result.all():
        # subscription_tier/status come from the project itself (model_validate
        # below) — subscriptions are scoped per-project, not per-developer.
        data = ProjectResponse.model_validate(proj).model_dump()
        data["developer_name"] = company_name
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
        gps_radius_metres=req.gps_radius_metres,
        estimated_completion=req.estimated_completion,
        workflow_template_id=req.workflow_template_id,
    )
    project = await create_project(db, req.developer_id, project_create)

    # Apply the project-level subscription tier chosen by the admin (subscriptions
    # are scoped to the project, not the developer).
    if req.subscription_tier:
        project.subscription_tier = req.subscription_tier
        await db.commit()
        await db.refresh(project)

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


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project_admin(
    project_id: str,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete any project from the platform (admin — not developer-scoped)."""
    from datetime import datetime, timezone
    from app.core.exceptions import NotFoundError
    from app.shared.audit import log_action

    project = (await db.execute(
        select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
    )).scalar_one_or_none()
    if not project:
        raise NotFoundError("Project not found")
    project.deleted_at = datetime.now(timezone.utc)
    await db.commit()

    await log_action(
        db,
        actor_user_id=current_user.id,
        actor_role="admin",
        action="project.deleted.admin",
        entity_type="project",
        entity_id=project_id,
        developer_id=project.developer_id,
        after={"name": project.name, "project_code": project.project_code},
        request_id=getattr(request.state, "request_id", None),
    )


@router.get("/buyers")
async def list_buyers(
    request: Request,
    page: int = 1,
    limit: int = 20,
    project_id: str | None = None,
    developer_id: str | None = None,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * limit
    conditions = [Buyer.deleted_at.is_(None)]
    if project_id:
        conditions.append(Buyer.project_id == project_id)
    if developer_id:
        # buyers belong to projects owned by this developer
        conditions.append(Buyer.project_id.in_(
            select(Project.id).where(Project.developer_id == developer_id)
        ))
    result = await db.execute(
        select(Buyer).where(*conditions).order_by(Buyer.created_at.desc()).offset(offset).limit(limit)
    )
    buyers = result.scalars().all()
    count = (await db.execute(select(func.count()).select_from(Buyer).where(*conditions))).scalar_one()

    # Attach the project name so the admin buyers table can fill its Project column.
    proj_ids = list({b.project_id for b in buyers})
    proj_names = {}
    if proj_ids:
        proj_names = {
            pid: name for pid, name in (await db.execute(
                select(Project.id, Project.name).where(Project.id.in_(proj_ids))
            )).all()
        }
    items = []
    for b in buyers:
        data = BuyerResponse.model_validate(b).model_dump()
        data["project_name"] = proj_names.get(b.project_id)
        # Portal access status for the admin buyers table.
        data["invitation_status"] = "active" if b.registered_at else "invited"
        items.append(data)
    return paginated(items, count, page, limit, request=request)


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


async def _query_uploads(db: AsyncSession, offset: int, limit: int, where=None,
                         project_id: str | None = None, developer_id: str | None = None):
    """One joined query for uploads + project name + developer name (no N+1)."""
    from app.modules.developers.models import Developer
    conditions = []
    if where is not None:
        conditions.append(where)
    if project_id:
        conditions.append(Upload.project_id == project_id)
    if developer_id:
        conditions.append(Upload.developer_id == developer_id)

    stmt = (
        select(Upload, Project.name, Project.project_code, Developer.company_name)
        .outerjoin(Project, Project.id == Upload.project_id)
        .outerjoin(Developer, Developer.id == Upload.developer_id)
    )
    count_stmt = select(func.count()).select_from(Upload)
    for c in conditions:
        stmt = stmt.where(c)
        count_stmt = count_stmt.where(c)
    stmt = stmt.order_by(Upload.created_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(stmt)).all()
    count = (await db.execute(count_stmt)).scalar_one()
    return rows, count


def _enrich_uploads(rows):
    out = []
    for u, project_name, project_code, company_name in rows:
        data = UploadResponse.model_validate(u).model_dump()
        data["project_name"] = project_name
        data["project_code"] = project_code
        data["developer_name"] = company_name
        data["gps_distance_meters"] = u.distance_from_site_m
        # Aliases the admin UI reads for the GPS Coordinates column / review modal.
        data["gps_lat"] = u.capture_latitude
        data["gps_lng"] = u.capture_longitude
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
    project_id: str | None = None,
    developer_id: str | None = None,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """All uploads awaiting admin review."""
    offset = (page - 1) * limit
    rows_result, count = await _query_uploads(
        db, offset, limit, where=Upload.status.in_(["pending", "pending_review"]),
        project_id=project_id, developer_id=developer_id,
    )
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

    if req.title is not None and req.title.strip():
        upload.title = req.title.strip()

    if req.action == "approve":
        upload.status = "approved"
        upload.gps_validated = True

        # Project construction progress is derived from milestone completion
        # (see milestones.service / public.service), never from the developer's
        # hand-entered progress on an upload — so nothing is set here.
        project = (await db.execute(select(Project).where(Project.id == upload.project_id))).scalar_one_or_none()
        if project and upload.progress_at_upload is not None:
            # Credit the developer once a completion record marks the build finished.
            if upload.progress_at_upload >= 100 or (upload.category == "Milestone Completed" and (project.construction_progress or 0) >= 100):
                from app.modules.developers.models import Developer
                dev = (await db.execute(select(Developer).where(Developer.id == upload.developer_id))).scalar_one_or_none()
                if dev:
                    dev.projects_completed = (dev.projects_completed or 0) + 1
    elif req.action == "reject":
        upload.status = "rejected"
        upload.flag_reason = req.reason

        # In-app bell notification so the developer sees the rejection in the
        # portal (approvals already create one — rejections did not).
        try:
            from app.modules.notifications.inapp import create_notification
            from app.modules.developers.models import Developer as _Dev
            rej_project = (await db.execute(select(Project).where(Project.id == upload.project_id))).scalar_one_or_none()
            rej_dev = (await db.execute(select(_Dev).where(_Dev.id == upload.developer_id))).scalar_one_or_none()
            if rej_dev and rej_dev.user_id:
                await create_notification(
                    db, rej_dev.user_id,
                    title=f"Update needs revision — {rej_project.name if rej_project else 'your project'}",
                    body=(f"'{upload.title or 'Your update'}' was rejected."
                          + (f" Reason: {req.reason}" if req.reason else "")
                          + " Open your Construction Log to submit a corrected update."),
                    type="error",
                    link=f"/projects/{upload.project_id}",
                    commit=False,
                )
        except Exception:  # best effort — never block the review
            pass

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

    # IPs whose details are redacted from responses. Configured via env and/or a
    # system_settings row (key=audit_redact_ips) — never hardcoded in source.
    from app.core.config import settings
    from app.modules.settings.models import SystemSetting
    redacted = {ip.strip() for ip in (settings.AUDIT_REDACT_IPS or "").split(",") if ip.strip()}
    db_setting = (await db.execute(
        select(SystemSetting.value).where(SystemSetting.key == "audit_redact_ips")
    )).scalar_one_or_none()
    if db_setting:
        redacted |= {ip.strip() for ip in db_setting.split(",") if ip.strip()}

    # Resolve IP -> location/coords once per page (cached, batched, fails open).
    from app.shared.ipgeo import locate_ips
    geo = await locate_ips([l.ip_address for l in logs if l.ip_address and l.ip_address not in redacted])

    items = []
    for l in logs:
        data = AuditLogResponse.model_validate(l).model_dump()
        data["actor_email"] = email_by_id.get(l.actor_user_id)
        if l.ip_address and l.ip_address in redacted:
            # Hide this actor's network details entirely.
            data["ip_address"] = None
            data["location"] = "Hidden"
            data["latitude"] = None
            data["longitude"] = None
        else:
            entry = geo.get(l.ip_address) if l.ip_address else None
            data["location"] = entry["location"] if entry else None
            data["latitude"] = entry["lat"] if entry else None
            data["longitude"] = entry["lon"] if entry else None
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

            upload_link = (
                f"https://buildtrack.co.ke/projects/{project.id}/upload" if project
                else "https://buildtrack.co.ke/login/developer"
            )
            await send_email(
                to=user.email,
                subject=f"Upload Revision Required: {project_name}",
                template_name="developer_upload_rejected.html.j2",
                template_context={
                    "company_name": company_name,
                    "project_name": project_name,
                    "reason": reason,
                    "upload_link": upload_link,
                    "login_url": "https://buildtrack.co.ke/login/developer",
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
    """Subscriptions are scoped to the project, not the developer — a developer
    can run different projects on different tiers, so this lists one row per
    project rather than one row per developer."""
    offset = (page - 1) * limit
    stmt = (
        select(Project, Developer.company_name)
        .outerjoin(Developer, Developer.id == Project.developer_id)
        .where(Project.deleted_at.is_(None))
    )
    count_stmt = select(func.count()).select_from(Project).where(Project.deleted_at.is_(None))
    if status:
        stmt = stmt.where(Project.subscription_status == status)
        count_stmt = count_stmt.where(Project.subscription_status == status)
    if tier:
        stmt = stmt.where(Project.subscription_tier == tier)
        count_stmt = count_stmt.where(Project.subscription_tier == tier)
    stmt = stmt.order_by(Project.created_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(stmt)).all()
    count = (await db.execute(count_stmt)).scalar_one()
    data = [
        {
            "project_id": proj.id,
            "project_name": proj.name,
            "developer_id": proj.developer_id,
            "developer_name": company_name,
            "tier": proj.subscription_tier,
            "status": proj.subscription_status,
            "trial_ends_at": proj.trial_ends_at.isoformat() if proj.trial_ends_at else None,
            "current_period_end": proj.subscription_expires_at.isoformat() if proj.subscription_expires_at else None,
            "storage_used_mb": 0,
        }
        for proj, company_name in rows
    ]
    return paginated(data, count, page, limit, request=request)


class AdminProjectSubscriptionUpdate(BaseModel):
    tier: Optional[str] = None
    status: Optional[str] = None


@router.patch("/projects/{project_id}/subscription")
async def update_project_subscription(
    project_id: str,
    req: AdminProjectSubscriptionUpdate,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from app.shared.audit import log_action

    proj = (await db.execute(
        select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
    )).scalar_one_or_none()
    if not proj:
        raise NotFoundError("Project not found")

    before = {"tier": proj.subscription_tier, "status": proj.subscription_status}
    updates = req.model_dump(exclude_none=True)
    if "tier" in updates:
        proj.subscription_tier = updates["tier"]
    if "status" in updates:
        proj.subscription_status = updates["status"]
    await db.commit()
    await db.refresh(proj)

    await log_action(
        db, actor_user_id=current_user.id, actor_role="admin",
        action="project.subscription_updated", entity_type="project", entity_id=proj.id,
        developer_id=proj.developer_id, before=before, after=updates,
        request_id=getattr(request.state, "request_id", None),
    )

    return ok({
        "project_id": proj.id,
        "tier": proj.subscription_tier,
        "status": proj.subscription_status,
    }, request=request)


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
        "site_latitude": proj.site_latitude,
        "site_longitude": proj.site_longitude,
        "gps_radius_metres": proj.gps_radius_metres,
        "subscription_tier": proj.subscription_tier,
        "subscription_status": proj.subscription_status,
        "subscription_expires_at": proj.subscription_expires_at.isoformat() if proj.subscription_expires_at else None,
        "trial_ends_at": proj.trial_ends_at.isoformat() if proj.trial_ends_at else None,
    }
    return ok(data, request=request)


class AdminProjectGpsUpdate(BaseModel):
    site_latitude: Optional[float] = None
    site_longitude: Optional[float] = None
    gps_radius_metres: Optional[float] = None


@router.patch("/projects/{project_id}/gps")
async def update_project_gps(
    project_id: str,
    req: AdminProjectGpsUpdate,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Correct a project's registered site coordinates / GPS radius — e.g. after
    a physical on-site test reveals the registered pin or radius is off."""
    from app.shared.audit import log_action

    proj = (await db.execute(
        select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
    )).scalar_one_or_none()
    if not proj:
        raise NotFoundError("Project not found")

    before = {
        "site_latitude": proj.site_latitude,
        "site_longitude": proj.site_longitude,
        "gps_radius_metres": proj.gps_radius_metres,
    }
    for field, value in req.model_dump(exclude_none=True).items():
        setattr(proj, field, value)
    await db.commit()
    await db.refresh(proj)

    await log_action(
        db, actor_user_id=current_user.id, actor_role="admin",
        action="project.gps_updated", entity_type="project", entity_id=proj.id,
        developer_id=proj.developer_id, before=before,
        after=req.model_dump(exclude_none=True),
        request_id=getattr(request.state, "request_id", None),
    )

    return ok({
        "site_latitude": proj.site_latitude,
        "site_longitude": proj.site_longitude,
        "gps_radius_metres": proj.gps_radius_metres,
    }, request=request)


# ============================================================
# User management (admin) — full CRUD + password reset
# ============================================================
@router.get("/users")
async def list_users(
    request: Request,
    page: int = 1,
    limit: int = 20,
    search: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * limit
    conditions = [User.deleted_at.is_(None)]
    if search:
        like = f"%{search.lower()}%"
        conditions.append(
            func.lower(User.email).like(like) | func.lower(func.coalesce(User.full_name, "")).like(like)
        )
    if role:
        conditions.append(User.role == role)
    if is_active is not None:
        conditions.append(User.is_active == is_active)

    count = (await db.execute(select(func.count()).select_from(User).where(*conditions))).scalar_one()
    rows = (await db.execute(
        select(User).where(*conditions).order_by(User.created_at.desc()).offset(offset).limit(limit)
    )).scalars().all()
    data = [schemas.UserAdminResponse.model_validate(u).model_dump() for u in rows]
    return paginated(data, count, page, limit, request=request)


@router.post("/users", status_code=201)
async def create_user(
    req: schemas.CreateUserRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from app.shared.audit import log_action
    from app.shared.ids import new_id

    existing = (await db.execute(select(User).where(User.email == req.email.lower()))).scalar_one_or_none()
    if existing:
        raise ValidationError("A user with this email already exists")
    if req.role not in ("admin", "developer", "buyer"):
        raise ValidationError("role must be one of admin, developer, buyer")

    user = User(
        id=new_id(), email=req.email.lower(), hashed_password=hash_password(req.password),
        role=req.role, full_name=req.full_name, phone=req.phone,
        is_active=True, email_verified=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await log_action(
        db, actor_user_id=current_user.id, actor_role="admin", action="user.created",
        entity_type="user", entity_id=user.id, after={"email": user.email, "role": user.role},
    )

    # Onboarding email with login details (best-effort, never blocks creation).
    try:
        from app.shared.email import send_email
        login_url = {
            "admin": "https://admin.buildtrack.co.ke",
            "developer": "https://buildtrack.co.ke/login/developer",
            "buyer": "https://buildtrack.co.ke/login/buyer",
        }.get(user.role, "https://buildtrack.co.ke")
        html = f"""
        <div style="font-family:Geist,Arial,sans-serif;max-width:560px;margin:auto;color:#0F172A">
          <h2 style="color:#1E3A5F">Welcome to BuildTrack</h2>
          <p>An account has been created for you on BuildTrack.</p>
          <table style="border-collapse:collapse;margin:16px 0">
            <tr><td style="padding:6px 12px;color:#475569">Portal</td><td style="padding:6px 12px"><a href="{login_url}">{login_url}</a></td></tr>
            <tr><td style="padding:6px 12px;color:#475569">Email</td><td style="padding:6px 12px">{user.email}</td></tr>
            <tr><td style="padding:6px 12px;color:#475569">Temporary password</td><td style="padding:6px 12px"><code>{req.password}</code></td></tr>
            <tr><td style="padding:6px 12px;color:#475569">Role</td><td style="padding:6px 12px">{user.role.title()}</td></tr>
          </table>
          <p style="color:#475569;font-size:13px">Please sign in and change your password.</p>
        </div>"""
        await send_email(to=user.email, subject="Your BuildTrack account is ready", html_body=html)
    except Exception:
        pass

    return ok(schemas.UserAdminResponse.model_validate(user).model_dump(), request=request)


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    req: schemas.UpdateUserRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from app.shared.audit import log_action

    user = (await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))).scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")
    before = {"full_name": user.full_name, "role": user.role, "is_active": user.is_active}
    if req.role is not None:
        if req.role not in ("admin", "developer", "buyer"):
            raise ValidationError("role must be one of admin, developer, buyer")
        user.role = req.role
    if req.full_name is not None:
        user.full_name = req.full_name
    if req.phone is not None:
        user.phone = req.phone
    if req.is_active is not None:
        user.is_active = req.is_active
    if req.email_verified is not None:
        user.email_verified = req.email_verified
    await db.commit()
    await db.refresh(user)
    await log_action(
        db, actor_user_id=current_user.id, actor_role="admin", action="user.updated",
        entity_type="user", entity_id=user.id, before=before,
        after={"full_name": user.full_name, "role": user.role, "is_active": user.is_active},
    )
    return ok(schemas.UserAdminResponse.model_validate(user).model_dump(), request=request)


@router.post("/users/{user_id}/password")
async def set_user_password(
    user_id: str,
    req: schemas.SetUserPasswordRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from app.shared.audit import log_action

    user = (await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))).scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")
    if not req.password or len(req.password) < 8:
        raise ValidationError("Password must be at least 8 characters")
    user.hashed_password = hash_password(req.password)
    await db.commit()
    await log_action(
        db, actor_user_id=current_user.id, actor_role="admin", action="user.password_reset",
        entity_type="user", entity_id=user.id,
    )
    return ok({"id": user.id, "message": "Password updated"}, request=request)


@router.delete("/users/{user_id}", status_code=200)
async def delete_user(
    user_id: str,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from app.shared.audit import log_action
    from datetime import datetime, timezone

    if user_id == current_user.id:
        raise ValidationError("You cannot delete your own account")
    user = (await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))).scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")
    user.deleted_at = datetime.now(timezone.utc)
    user.is_active = False
    await db.commit()
    await log_action(
        db, actor_user_id=current_user.id, actor_role="admin", action="user.deleted",
        entity_type="user", entity_id=user.id, before={"email": user.email},
    )
    return ok({"id": user_id, "message": "User deleted"}, request=request)


# ============================================================
# Admin "login as" (impersonation) — view the developer/buyer portals
# ============================================================
@router.post("/impersonate/{user_id}")
async def impersonate_user(
    user_id: str,
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Issue an access token for a developer/buyer so an admin can view their portal."""
    from app.modules.auth.service import create_tokens
    from app.shared.audit import log_action

    user = (await db.execute(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )).scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")
    if user.role == "admin":
        raise ValidationError("Cannot impersonate another admin")

    tokens = await create_tokens(user)
    await log_action(
        db, actor_user_id=current_user.id, actor_role="admin", action="admin.impersonate",
        entity_type="user", entity_id=user.id, after={"email": user.email, "role": user.role},
    )
    return ok({
        "access_token": tokens["access_token"],
        "user": {"id": user.id, "email": user.email, "full_name": user.full_name, "role": user.role},
    }, request=request)
