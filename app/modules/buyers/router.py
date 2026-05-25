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
    """Get the buyer's assigned project with milestones and uploads."""
    from sqlalchemy import select
    from app.modules.buyers.models import Buyer
    from app.modules.projects.models import Project
    from app.modules.milestones.models import Milestone
    from app.modules.milestones.schemas import MilestoneResponse
    from app.modules.uploads.models import Upload
    from app.modules.uploads.schemas import UploadResponse

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

    result = await db.execute(
        select(Project).where(
            Project.id == buyer.project_id,
            Project.deleted_at.is_(None),
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("Project not found")

    result = await db.execute(
        select(Milestone).where(Milestone.project_id == project.id).order_by(Milestone.order_index)
    )
    milestones = result.scalars().all()

    result = await db.execute(
        select(Upload).where(
            Upload.project_id == project.id,
            Upload.status == "approved",
        ).order_by(Upload.created_at.desc()).limit(20)
    )
    uploads = result.scalars().all()

    from app.modules.projects.schemas import ProjectResponse
    project_data = ProjectResponse.model_validate(project).model_dump()
    project_data["milestones"] = [MilestoneResponse.model_validate(m).model_dump() for m in milestones]
    project_data["recent_uploads"] = [UploadResponse.model_validate(u).model_dump() for u in uploads]
    project_data["unit_number"] = buyer.unit_number

    return ok(project_data, request=request)


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
