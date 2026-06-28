from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_developer, get_tenant_context, TenantContext, require_permission
from app.modules.billing import schemas, service
from app.shared.response import ok

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/tier-limits", dependencies=[require_permission("billing", "read")])
async def get_my_tier_limits(
    request: Request,
    project_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    """Return tier limits for a project. Subscriptions are scoped to the
    project, not the developer, so a project_id is required."""
    from app.shared.quotas import get_project_tier
    tier = await get_project_tier(db, project_id)
    limits = service.get_tier_limits(tier)
    return ok({"tier": tier, **limits}, request=request)
