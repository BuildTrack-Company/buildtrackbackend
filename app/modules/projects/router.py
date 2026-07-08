from fastapi import APIRouter, Depends, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.core.deps import require_developer, get_tenant_context, TenantContext, require_permission
from app.modules.auth.models import User
from app.modules.projects import service, schemas
from app.modules.projects import workflow_service
from app.shared.response import ok
from app.shared.audit import log_action

router = APIRouter(tags=["projects"])


@router.get("/projects", dependencies=[require_permission("projects", "read")])
async def list_projects(
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import case
    from app.modules.buyers.models import Buyer
    from app.modules.milestones.models import Milestone
    from app.modules.uploads.models import Upload, Photo
    from app.shared.storage import get_signed_url

    projects = await service.list_projects(db, ctx.developer_id)
    if not projects:
        return ok([], request=request)

    pids = [p.id for p in projects]

    # Batched counts/progress/images (one query each — no per-project N+1).
    buyer_rows = (await db.execute(
        select(Buyer.project_id, func.count()).where(
            Buyer.project_id.in_(pids), Buyer.deleted_at.is_(None)
        ).group_by(Buyer.project_id)
    )).all()
    buyer_counts = {r[0]: r[1] for r in buyer_rows}

    ms_rows = (await db.execute(
        select(
            Milestone.project_id,
            func.count().label("total"),
            func.sum(case((Milestone.status == "complete", 1), else_=0)).label("done"),
        ).where(Milestone.project_id.in_(pids)).group_by(Milestone.project_id)
    )).all()
    ms_total = {r.project_id: int(r.total or 0) for r in ms_rows}
    ms_done = {r.project_id: int(r.done or 0) for r in ms_rows}

    latest = (await db.execute(
        select(Upload.id, Upload.project_id, Upload.created_at)
        .where(Upload.project_id.in_(pids), Upload.status == "approved")
        .order_by(Upload.project_id, Upload.created_at.desc())
    )).all()
    latest_upload = {}
    latest_upload_at = {}
    for uid, pid, created_at in latest:
        latest_upload.setdefault(pid, uid)
        latest_upload_at.setdefault(pid, created_at)
    images = {}
    if latest_upload:
        photo_rows = (await db.execute(
            select(Photo.upload_id, Photo.cloudinary_public_id)
            .where(Photo.upload_id.in_(list(latest_upload.values())))
            .order_by(Photo.upload_id, Photo.order_index)
        )).all()
        photo_by_upload = {}
        for up_id, pub in photo_rows:
            photo_by_upload.setdefault(up_id, pub)
        for pid, up_id in latest_upload.items():
            if up_id in photo_by_upload:
                images[pid] = get_signed_url(photo_by_upload[up_id], "display")

    from app.modules.public.service import compute_activity_status, _days_since

    out = []
    for p in projects:
        data = schemas.ProjectResponse.model_validate(p).model_dump()
        total = ms_total.get(p.id, 0)
        done = ms_done.get(p.id, 0)
        data["buyer_count"] = buyer_counts.get(p.id, 0)
        data["milestone_progress"] = round((done / total) * 100) if total else (p.construction_progress or 0)
        data["completed_milestones"] = done
        data["milestone_count"] = total
        data["card_image"] = images.get(p.id)
        last_at = latest_upload_at.get(p.id)
        data["activity_status"] = compute_activity_status(p.activity_overdue_threshold_days or 14, last_at)
        data["days_since_last_update"] = _days_since(last_at)
        out.append(data)
    return ok(out, request=request)


@router.post("/projects", status_code=201, dependencies=[require_permission("projects", "create")])
async def create_project(
    req: schemas.ProjectCreate,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    project = await service.create_project(db, ctx.developer_id, req)

    await log_action(
        db,
        actor_user_id=ctx.user_id,
        actor_role=ctx.role,
        action="project.created",
        entity_type="project",
        entity_id=project.id,
        developer_id=ctx.developer_id,
        after={"name": project.name, "project_code": project.project_code},
        request_id=getattr(request.state, "request_id", None),
    )

    return ok(schemas.ProjectResponse.model_validate(project).model_dump(), request=request)


@router.get("/projects/{project_id}", dependencies=[require_permission("projects", "read")])
async def get_project(
    project_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    project = await service.get_project(db, project_id, ctx.developer_id)

    from app.modules.milestones.models import Milestone
    from app.modules.buyers.models import Buyer
    from app.modules.uploads.models import Upload, Photo
    from sqlalchemy import func
    result = await db.execute(
        select(Milestone).where(Milestone.project_id == project_id).order_by(Milestone.order_index)
    )
    milestones = result.scalars().all()

    project_data = schemas.ProjectResponse.model_validate(project).model_dump()
    from app.modules.milestones.schemas import MilestoneResponse
    project_data["milestones"] = [MilestoneResponse.model_validate(m).model_dump() for m in milestones]

    # Header/stat cards: Units, Buyers, Photos.
    buyer_count = (await db.execute(
        select(func.count()).select_from(Buyer).where(
            Buyer.project_id == project_id, Buyer.deleted_at.is_(None)
        )
    )).scalar_one()
    photo_count = (await db.execute(
        select(func.count()).select_from(Photo)
        .join(Upload, Upload.id == Photo.upload_id)
        .where(Upload.project_id == project_id)
    )).scalar_one()
    project_data["unit_count"] = project.total_units or 0
    project_data["buyer_count"] = buyer_count
    project_data["photo_count"] = photo_count

    return ok(project_data, request=request)


@router.patch("/projects/{project_id}", dependencies=[require_permission("projects", "update")])
async def update_project(
    project_id: str,
    req: schemas.ProjectUpdate,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    project = await service.update_project(db, project_id, ctx.developer_id, req)

    await log_action(
        db,
        actor_user_id=ctx.user_id,
        actor_role=ctx.role,
        action="project.updated",
        entity_type="project",
        entity_id=project.id,
        developer_id=ctx.developer_id,
        after=req.model_dump(exclude_none=True),
        request_id=getattr(request.state, "request_id", None),
    )

    return ok(schemas.ProjectResponse.model_validate(project).model_dump(), request=request)


@router.delete("/projects/{project_id}", status_code=204, dependencies=[require_permission("projects", "delete")])
async def delete_project(
    project_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    await service.delete_project(db, project_id, ctx.developer_id)

    await log_action(
        db,
        actor_user_id=ctx.user_id,
        actor_role=ctx.role,
        action="project.deleted",
        entity_type="project",
        entity_id=project_id,
        developer_id=ctx.developer_id,
        request_id=getattr(request.state, "request_id", None),
    )


@router.get("/public/project-code/{code}")
async def lookup_project_by_code(
    code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    project = await service.get_project_by_code(db, code)
    return ok(schemas.ProjectResponse.model_validate(project).model_dump(), request=request)


# ─── Visibility-page management (developer) ──────────────────────────────────

class VisibilityPageUpdate(BaseModel):
    description: Optional[str] = None
    tagline: Optional[str] = None
    starting_price: Optional[str] = None
    slug: Optional[str] = None


@router.patch("/projects/{project_id}/visibility-page", dependencies=[require_permission("projects", "update")])
async def update_visibility_page(
    project_id: str,
    req: VisibilityPageUpdate,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    project = await service.update_visibility_page(
        db, project_id, ctx.developer_id,
        description=req.description, tagline=req.tagline,
        starting_price=req.starting_price, slug=req.slug,
    )
    await log_action(
        db, actor_user_id=ctx.user_id, actor_role=ctx.role,
        action="visibility_page.updated", entity_type="project", entity_id=project_id,
        developer_id=ctx.developer_id, after=req.model_dump(exclude_none=True),
        request_id=getattr(request.state, "request_id", None),
    )
    return ok(schemas.ProjectResponse.model_validate(project).model_dump(), request=request)


@router.post("/projects/{project_id}/visibility-page/publish", dependencies=[require_permission("projects", "update")])
async def publish_visibility_page(
    project_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    project = await service.set_visibility_published(db, project_id, ctx.developer_id, True)
    await log_action(
        db, actor_user_id=ctx.user_id, actor_role=ctx.role,
        action="visibility_page.published", entity_type="project", entity_id=project_id,
        developer_id=ctx.developer_id, request_id=getattr(request.state, "request_id", None),
    )
    return ok(schemas.ProjectResponse.model_validate(project).model_dump(), request=request)


@router.post("/projects/{project_id}/visibility-page/unpublish", dependencies=[require_permission("projects", "update")])
async def unpublish_visibility_page(
    project_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    project = await service.set_visibility_published(db, project_id, ctx.developer_id, False)
    await log_action(
        db, actor_user_id=ctx.user_id, actor_role=ctx.role,
        action="visibility_page.unpublished", entity_type="project", entity_id=project_id,
        developer_id=ctx.developer_id, request_id=getattr(request.state, "request_id", None),
    )
    return ok(schemas.ProjectResponse.model_validate(project).model_dump(), request=request)


@router.get("/developers/me/projects/{project_id}/analytics", dependencies=[require_permission("projects", "read")])
async def get_project_visibility_analytics(
    project_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    from app.modules.public import service as public_service
    data = await public_service.get_project_analytics(db, ctx.developer_id, project_id)
    return ok(data, request=request)


# ─── Workflow runtime ────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/workflow", dependencies=[require_permission("workflow", "read")])
async def get_project_workflow(
    project_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    data = await workflow_service.get_project_workflow(
        db, project_id, ctx.developer_id, ctx.user_id, ctx.role
    )
    return ok(data, request=request)


@router.get("/projects/{project_id}/workflow/next-stages", dependencies=[require_permission("workflow", "read")])
async def get_workflow_next_stages(
    project_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    data = await workflow_service.get_next_stages(
        db, project_id, ctx.developer_id, ctx.user_id, ctx.role
    )
    return ok(data, request=request)


@router.get("/projects/{project_id}/workflow/history", dependencies=[require_permission("workflow", "read")])
async def get_workflow_history(
    project_id: str,
    request: Request,
    page: int = 1,
    limit: int = 20,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    data = await workflow_service.get_workflow_history(
        db, project_id, ctx.developer_id, ctx.user_id, ctx.role, page, limit
    )
    return ok(data, request=request)


class AdvanceWorkflowRequest(BaseModel):
    to_stage_id: str
    notes: Optional[str] = None


@router.post("/projects/{project_id}/workflow/advance", dependencies=[require_permission("workflow", "advance")])
async def advance_project_workflow(
    project_id: str,
    req: AdvanceWorkflowRequest,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    if not idempotency_key:
        from app.core.exceptions import ValidationError
        raise ValidationError("Idempotency-Key header is required")

    data = await workflow_service.advance_workflow(
        db,
        project_id,
        ctx.developer_id,
        ctx.user_id,
        ctx.role,
        req.to_stage_id,
        req.notes,
        idempotency_key,
        getattr(request.state, "request_id", None),
    )
    return ok(data, request=request)


@router.post("/projects/{project_id}/delay", dependencies=[require_permission("projects", "update")])
async def log_project_delay(
    project_id: str,
    req: schemas.DelayRequest,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    from app.modules.milestones.models import Milestone
    from app.core.exceptions import NotFoundError
    from app.shared.audit import log_action
    from app.modules.notifications.service import send_milestone_notification
    
    project = await service.get_project(db, project_id, ctx.developer_id)
    project.health_status = "minor_delay"
    
    milestone = (await db.execute(select(Milestone).where(Milestone.id == req.milestone_id, Milestone.project_id == project_id))).scalar_one_or_none()
    if not milestone:
        raise NotFoundError("Milestone not found")
        
    milestone.delay_reason = req.delay_reason
    if req.new_date:
        milestone.delay_new_date = req.new_date
        
    await db.commit()
    
    await log_action(
        db,
        actor_user_id=ctx.user_id,
        actor_role=ctx.role,
        action="project.delay_logged",
        entity_type="project",
        entity_id=project.id,
        developer_id=ctx.developer_id,
        after={"milestone_id": req.milestone_id, "reason": req.delay_reason},
        request_id=getattr(request.state, "request_id", None),
    )
    
    # Notify buyers
    try:
        await send_milestone_notification(milestone.id, "delayed", db)
    except Exception:
        pass
        
    return ok({"status": "delay_logged"}, request=request)


# ============================================================
# Latest-update panel — email preview + one-click send to buyers
# ============================================================
@router.get("/projects/{project_id}/latest-update/preview", dependencies=[require_permission("buyers", "read")])
async def latest_update_preview(
    project_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    from app.modules.uploads.models import Upload, Photo
    from app.modules.buyers.models import Buyer
    from app.modules.uploads import service as upload_service
    from app.core.exceptions import NotFoundError

    project = await service.get_project(db, project_id, ctx.developer_id)
    if not project:
        raise NotFoundError("Project not found")

    upload = (await db.execute(
        select(Upload)
        .where(Upload.project_id == project_id, Upload.status == "approved")
        .order_by(Upload.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    if upload is None:
        upload = (await db.execute(
            select(Upload).where(Upload.project_id == project_id)
            .order_by(Upload.created_at.desc()).limit(1)
        )).scalar_one_or_none()

    recipient_count = (await db.execute(
        select(func.count()).select_from(Buyer).where(
            Buyer.project_id == project_id,
            Buyer.deleted_at.is_(None),
            Buyer.notification_email.is_(True),
        )
    )).scalar_one()

    if upload is None:
        return ok({
            "subject": f"Construction Update — {project.name}",
            "body_html": "<p>No site updates have been published yet.</p>",
            "body_text": "No site updates have been published yet.",
            "recipient_count": recipient_count,
            "whatsapp_message": "",
            "has_update": False,
        }, request=request)

    photos = (await db.execute(
        select(Photo).where(Photo.upload_id == upload.id).order_by(Photo.order_index)
    )).scalars().all()

    caption = upload.caption or upload.title or "New progress on site."
    progress = upload.progress_at_upload or project.construction_progress or 0
    subject = f"Construction Update — {project.name}"
    body_text = (
        f"{project.name}\n\nProgress: {progress}%\n\n{caption}\n\n"
        f"{len(photos)} new photo(s) added. Log in to BuildTrack to view the full update."
    )
    body_html = (
        f"<h2>{project.name}</h2>"
        f"<p><strong>Progress:</strong> {progress}%</p>"
        f"<p>{caption}</p>"
        f"<p>{len(photos)} new photo(s) added. Log in to BuildTrack to view the full update.</p>"
    )
    try:
        whatsapp_message = upload_service.generate_whatsapp_draft(upload, project.name, photos)
    except Exception:  # noqa: BLE001
        whatsapp_message = f"{project.name} — {progress}% complete. {caption}"

    return ok({
        "subject": subject,
        "body_html": body_html,
        "body_text": body_text,
        "recipient_count": recipient_count,
        "whatsapp_message": whatsapp_message,
        "has_update": True,
        "upload_id": upload.id,
    }, request=request)


@router.post("/projects/{project_id}/latest-update/send", dependencies=[require_permission("buyers", "notify")])
async def latest_update_send(
    project_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    from app.modules.uploads.models import Upload
    from app.modules.buyers.models import Buyer
    from app.core.exceptions import NotFoundError, ValidationError

    project = await service.get_project(db, project_id, ctx.developer_id)
    if not project:
        raise NotFoundError("Project not found")

    upload = (await db.execute(
        select(Upload).where(Upload.project_id == project_id, Upload.status == "approved")
        .order_by(Upload.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    if upload is None:
        raise ValidationError("No approved update available to send")

    recipient_count = (await db.execute(
        select(func.count()).select_from(Buyer).where(
            Buyer.project_id == project_id,
            Buyer.deleted_at.is_(None),
            Buyer.notification_email.is_(True),
        )
    )).scalar_one()

    try:
        from app.modules.notifications.service import fanout_upload_notifications
        await fanout_upload_notifications(upload.id, db)
    except Exception:  # noqa: BLE001
        pass

    await log_action(
        db, actor_user_id=ctx.user_id, actor_role=ctx.role,
        action="project.latest_update.sent", entity_type="project", entity_id=project_id,
        developer_id=ctx.developer_id, after={"upload_id": upload.id, "recipients": recipient_count},
        request_id=getattr(request.state, "request_id", None),
    )
    return ok({"sent": True, "recipient_count": recipient_count, "upload_id": upload.id}, request=request)
