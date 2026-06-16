from fastapi import APIRouter, Depends, Request, BackgroundTasks, Header
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import structlog

from app.core.database import get_db
from app.core.deps import get_tenant_context, TenantContext, require_permission
from app.core.exceptions import NotFoundError
from app.modules.uploads import service, schemas
from app.modules.uploads.models import Upload
from app.shared.response import ok, paginated
from app.shared.storage import get_signed_url
from app.shared.audit import log_action

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["uploads"])


@router.post("/uploads/sessions", dependencies=[require_permission("photos", "upload")])
async def create_upload_session(
    req: schemas.UploadSessionRequest,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    result = await service.create_upload_session(db, ctx.developer_id, req)
    return ok(result, request=request)


@router.post("/uploads", status_code=201, dependencies=[require_permission("photos", "upload")])
async def finalize_upload(
    req: schemas.FinalizeUploadRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    upload = await service.finalize_upload(db, ctx.developer_id, req, idempotency_key)

    await log_action(
        db,
        actor_user_id=ctx.user_id,
        actor_role=ctx.role,
        action="upload.created",
        entity_type="upload",
        entity_id=upload.id,
        developer_id=ctx.developer_id,
        after={"project_id": upload.project_id, "photo_count": upload.photo_count, "status": upload.status},
        request_id=getattr(request.state, "request_id", None),
    )

    background_tasks.add_task(_notify_admin_new_upload, upload_id=upload.id)

    return ok(schemas.UploadResponse.model_validate(upload).model_dump(), request=request)


@router.post("/uploads/{upload_id}/resend-emails", dependencies=[require_permission("buyers", "notify")])
async def resend_upload_emails(
    upload_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    result = await db.execute(
        select(Upload).where(Upload.id == upload_id, Upload.developer_id == ctx.developer_id)
    )
    upload = result.scalar_one_or_none()
    if not upload:
        raise NotFoundError("Upload not found")

    background_tasks.add_task(_notify_admin_new_upload, upload_id=upload.id)
    return ok({"queued": True, "upload_id": upload_id}, request=request)


async def _notify_admin_new_upload(upload_id: str):
    try:
        from app.core.database import async_session_factory
        from sqlalchemy import select
        from app.modules.projects.models import Project
        from app.modules.developers.models import Developer
        from app.shared.email import send_email
        from app.core.config import settings

        async with async_session_factory() as db:
            result = await db.execute(select(Upload).where(Upload.id == upload_id))
            upload = result.scalar_one_or_none()
            if not upload:
                return

            project = (await db.execute(select(Project).where(Project.id == upload.project_id))).scalar_one_or_none()
            dev = (await db.execute(select(Developer).where(Developer.id == upload.developer_id))).scalar_one_or_none()
            
            project_name = project.name if project else "Unknown Project"
            company_name = dev.company_name if dev else "Unknown Developer"

            await send_email(
                to=settings.EMAIL_FROM_ADDRESS, # Admin's email
                subject=f"New Upload Pending Review: {project_name}",
                template_name="admin_new_upload.html.j2",
                template_context={
                    "company_name": company_name,
                    "project_name": project_name,
                }
            )
    except Exception as e:
        logger.error("admin_notify_failed", upload_id=upload_id, error=str(e))


@router.get("/projects/{project_id}/uploads", dependencies=[require_permission("photos", "read")])
async def list_uploads(
    project_id: str,
    request: Request,
    page: int = 1,
    limit: int = 20,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    uploads, total = await service.list_uploads(db, project_id, ctx.developer_id, page, limit)
    return paginated(
        [schemas.UploadResponse.model_validate(u).model_dump() for u in uploads],
        total, page, limit, request=request,
    )


@router.get("/uploads/{upload_id}", dependencies=[require_permission("photos", "read")])
async def get_upload(
    upload_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    upload, photos = await service.get_upload_with_photos(db, upload_id, ctx.developer_id)
    upload_data = schemas.UploadResponse.model_validate(upload).model_dump()

    photo_list = []
    for p in photos:
        pd = schemas.PhotoResponse.model_validate(p).model_dump()
        pd["signed_url"] = get_signed_url(p.cloudinary_public_id)
        photo_list.append(pd)

    upload_data["photos"] = photo_list
    return ok(upload_data, request=request)


@router.get("/uploads/{upload_id}/whatsapp-draft", dependencies=[require_permission("buyers", "notify")])
async def get_whatsapp_draft(
    upload_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    upload, photos = await service.get_upload_with_photos(db, upload_id, ctx.developer_id)

    from app.modules.projects.models import Project
    from sqlalchemy import select
    result = await db.execute(select(Project).where(Project.id == upload.project_id))
    project = result.scalar_one_or_none()
    project_name = project.name if project else "Project"

    draft = service.generate_whatsapp_draft(upload, project_name, photos)
    return ok({"text": draft}, request=request)
