from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_developer, get_tenant_context, TenantContext
from app.modules.billing import schemas, service
from app.shared.response import ok

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/tier-limits")
async def get_my_tier_limits(
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    """Return tier limits for the current developer (stub)."""
    from app.shared.quotas import get_developer_tier
    tier = await get_developer_tier(db, ctx.developer_id)
    limits = service.get_tier_limits(tier)
    return ok({"tier": tier, **limits}, request=request)
