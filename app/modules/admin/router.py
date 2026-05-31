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
