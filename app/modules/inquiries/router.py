from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
import structlog

from app.core.database import get_db
from app.core.deps import require_developer, require_admin, get_tenant_context, TenantContext
from app.modules.auth.models import User
from app.modules.inquiries import service, schemas
from app.modules.projects.models import Project
from app.modules.developers.models import Developer
from app.shared.response import ok, paginated
from app.shared.audit import log_action
from app.shared.email import send_email

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["inquiries"])


def _client_ip(request: Request) -> Optional[str]:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


# ─── Public: submit an inquiry ───────────────────────────────────────────────

@router.post("/public/projects/{slug}/inquiries", status_code=201)
async def submit_inquiry(
    slug: str,
    req: schemas.InquiryCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    inquiry = await service.create_inquiry(
        db, slug, req,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    await log_action(
        db,
        actor_user_id="public",
        actor_role="prospective_buyer",
        action="inquiry.created",
        entity_type="inquiry",
        entity_id=inquiry.id,
        developer_id=inquiry.developer_id,
        after={"email": inquiry.email, "source": inquiry.source},
        ip_address=inquiry.ip_address,
        request_id=getattr(request.state, "request_id", None),
    )

    # Notify the developer by email (best effort)
    try:
        project = (await db.execute(select(Project).where(Project.id == inquiry.project_id))).scalar_one_or_none()
        dev = (await db.execute(select(Developer).where(Developer.id == inquiry.developer_id))).scalar_one_or_none()
        if project and dev:
            dev_user = (await db.execute(select(User).where(User.id == dev.user_id))).scalar_one_or_none()
            if dev_user and dev_user.email:
                await send_email(
                    to=dev_user.email,
                    subject=f"New inquiry for {project.name}",
                    template_name="inquiry_received.html.j2",
                    template_context={
                        "project_name": project.name,
                        "first_name": inquiry.first_name,
                        "last_name": inquiry.last_name,
                        "email": inquiry.email,
                        "phone": inquiry.phone or "",
                        "location": inquiry.location or "",
                        "message": inquiry.message or "",
                    },
                )
    except Exception as e:
        logger.warning("inquiry_notify_failed", error=str(e), inquiry_id=inquiry.id)

    return ok({"id": inquiry.id, "status": "received"}, request=request)


# ─── Developer: own leads ────────────────────────────────────────────────────

@router.get("/developers/me/inquiries")
async def list_my_inquiries(
    request: Request,
    project_id: Optional[str] = None,
    seen: Optional[bool] = None,
    page: int = 1,
    limit: int = 20,
    _: User = Depends(require_developer),
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    rows, total = await service.list_for_developer(db, ctx.developer_id, project_id, seen, page, limit)
    return paginated(
        [schemas.InquiryResponse.model_validate(r).model_dump() for r in rows],
        total, page, limit, request=request,
    )


@router.get("/developers/me/inquiries/{inquiry_id}")
async def get_my_inquiry(
    inquiry_id: str,
    request: Request,
    _: User = Depends(require_developer),
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    inquiry = await service.get_for_developer(db, ctx.developer_id, inquiry_id)
    return ok(schemas.InquiryResponse.model_validate(inquiry).model_dump(), request=request)


@router.patch("/developers/me/inquiries/{inquiry_id}/seen")
async def mark_inquiry_seen(
    inquiry_id: str,
    request: Request,
    _: User = Depends(require_developer),
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    inquiry = await service.mark_seen(db, ctx.developer_id, inquiry_id)
    return ok(schemas.InquiryResponse.model_validate(inquiry).model_dump(), request=request)


@router.patch("/developers/me/inquiries/{inquiry_id}/converted")
async def mark_inquiry_converted(
    inquiry_id: str,
    request: Request,
    _: User = Depends(require_developer),
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    inquiry = await service.mark_converted(db, ctx.developer_id, inquiry_id)
    await log_action(
        db,
        actor_user_id=ctx.user_id,
        actor_role=ctx.role,
        action="inquiry.converted",
        entity_type="inquiry",
        entity_id=inquiry.id,
        developer_id=ctx.developer_id,
        request_id=getattr(request.state, "request_id", None),
    )
    return ok(schemas.InquiryResponse.model_validate(inquiry).model_dump(), request=request)


# ─── Admin: cross-tenant ─────────────────────────────────────────────────────

@router.get("/admin/inquiries")
async def list_all_inquiries(
    request: Request,
    developer_id: Optional[str] = None,
    project_id: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    rows, total = await service.list_all_admin(db, developer_id, project_id, page, limit)
    return paginated(
        [schemas.InquiryResponse.model_validate(r).model_dump() for r in rows],
        total, page, limit, request=request,
    )
