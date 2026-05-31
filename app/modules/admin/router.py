from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.deps import require_admin
from app.modules.auth.models import User
from app.modules.admin import service, schemas
from app.modules.developers.schemas import DeveloperResponse
from app.modules.projects.models import Project
from app.modules.projects.schemas import ProjectResponse
from app.modules.buyers.models import Buyer
from app.modules.buyers.schemas import BuyerResponse
from app.modules.uploads.models import Upload
from app.modules.uploads.schemas import UploadResponse
from app.modules.admin.models import AuditLog
from app.modules.admin.schemas import AuditLogResponse
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
    result = await db.execute(
        select(Project).where(Project.deleted_at.is_(None)).offset(offset).limit(limit)
    )
    projects = result.scalars().all()
    count = (await db.execute(select(func.count()).select_from(Project).where(Project.deleted_at.is_(None)))).scalar_one()

    # Enrich each project with developer name + tier + subscription + buyer count
    from app.modules.developers.models import Developer
    from app.modules.buyers.models import Buyer
    rows = []
    for p in projects:
        data = ProjectResponse.model_validate(p).model_dump()
        dev = (await db.execute(select(Developer).where(Developer.id == p.developer_id))).scalar_one_or_none()
        data["developer_name"] = dev.company_name if dev else None
        data["subscription_tier"] = dev.subscription_tier if dev else None
        data["subscription_status"] = dev.subscription_status if dev else None
        data["buyer_count"] = (await db.execute(
            select(func.count()).select_from(Buyer).where(Buyer.project_id == p.id, Buyer.deleted_at.is_(None))
        )).scalar_one()
        rows.append(data)

    return paginated(rows, count, page, limit, request=request)


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
    result = await db.execute(
        select(Upload).order_by(Upload.created_at.desc()).offset(offset).limit(limit)
    )
    uploads = result.scalars().all()
    count = (await db.execute(select(func.count()).select_from(Upload))).scalar_one()
    return paginated(
        [UploadResponse.model_validate(u).model_dump() for u in uploads],
        count, page, limit, request=request,
    )


@router.get("/uploads/pending")
async def list_pending_uploads(
    request: Request,
    page: int = 1,
    limit: int = 20,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """All uploads awaiting admin review (GPS-valid and GPS-flagged alike)."""
    offset = (page - 1) * limit
    result = await db.execute(
        select(Upload).where(Upload.status == "pending_review").order_by(Upload.created_at.desc()).offset(offset).limit(limit)
    )
    uploads = result.scalars().all()
    count = (await db.execute(select(func.count()).select_from(Upload).where(Upload.status == "pending_review"))).scalar_one()
    return paginated(
        [UploadResponse.model_validate(u).model_dump() for u in uploads],
        count, page, limit, request=request,
    )


@router.get("/uploads/flagged")
async def list_flagged_uploads(
    request: Request,
    page: int = 1,
    limit: int = 20,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """GPS-flagged uploads (subset of pending_review with flag_reason set)."""
    offset = (page - 1) * limit
    result = await db.execute(
        select(Upload).where(
            Upload.status == "pending_review",
            Upload.gps_validated.is_(False),
        ).order_by(Upload.created_at.desc()).offset(offset).limit(limit)
    )
    uploads = result.scalars().all()
    count = (await db.execute(
        select(func.count()).select_from(Upload).where(
            Upload.status == "pending_review",
            Upload.gps_validated.is_(False),
        )
    )).scalar_one()
    return paginated(
        [UploadResponse.model_validate(u).model_dump() for u in uploads],
        count, page, limit, request=request,
    )


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

    upload.reviewed_at = datetime.now(timezone.utc)
    upload.reviewed_by = current_user.id
    await db.commit()
    await db.refresh(upload)

    await log_action(
        db,
        actor_user_id=current_user.id,
        actor_role=current_user.role,
        action=f"upload.{req.action}d",
        entity_type="upload",
        entity_id=upload_id,
        developer_id=upload.developer_id,
        after={"status": upload.status, "reason": req.reason},
        request_id=getattr(request.state, "request_id", None),
    )

    # On approval, fan out buyer notifications (best effort, after commit)
    if req.action == "approve":
        try:
            from app.modules.notifications.service import fanout_upload_notifications
            await fanout_upload_notifications(upload.id, db)
        except Exception:
            pass

    return ok(UploadResponse.model_validate(upload).model_dump(), request=request)


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
    return paginated(
        [AuditLogResponse.model_validate(l).model_dump() for l in logs],
        count, page, limit, request=request,
    )


@router.get("/stats")
async def get_stats(
    request: Request,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stats = await service.get_platform_stats(db)
    return ok(stats, request=request)
