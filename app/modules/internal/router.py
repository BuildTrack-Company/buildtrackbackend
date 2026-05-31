from fastapi import APIRouter, Depends, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.database import get_db
from app.core.config import settings
from app.core.exceptions import UnauthorizedError
from app.modules.internal import service
from app.shared.response import ok

router = APIRouter(prefix="/internal", tags=["internal"])


def verify_cron_token(x_cron_token: Optional[str] = Header(None)):
    if not x_cron_token or x_cron_token != settings.INTERNAL_CRON_TOKEN:
        raise UnauthorizedError("Invalid or missing cron token")


@router.post("/scan-overdue-milestones")
async def scan_overdue_milestones(
    request: Request,
    _: None = Depends(verify_cron_token),
    db: AsyncSession = Depends(get_db),
):
    result = await service.scan_overdue_milestones(db)
    return ok(result, request=request)


@router.post("/cleanup-deny-list")
async def cleanup_deny_list(
    request: Request,
    _: None = Depends(verify_cron_token),
    db: AsyncSession = Depends(get_db),
):
    result = await service.cleanup_deny_list(db)
    return ok(result, request=request)


@router.post("/recalculate-usage-counters")
async def recalculate_usage_counters(
    request: Request,
    _: None = Depends(verify_cron_token),
    db: AsyncSession = Depends(get_db),
):
    result = await service.recalculate_usage_counters(db)
    return ok(result, request=request)


@router.post("/trial-warnings")
async def send_trial_warnings(
    request: Request,
    _: None = Depends(verify_cron_token),
    db: AsyncSession = Depends(get_db),
):
    """Send 'trial ending soon' emails to developers with ≤ 3 days remaining."""
    result = await service.send_trial_warnings(db)
    return ok(result, request=request)


@router.post("/sync-cloudinary-usage")
async def sync_cloudinary_usage(
    request: Request,
    _: None = Depends(verify_cron_token),
    db: AsyncSession = Depends(get_db),
):
    """Recalculate storage_used_bytes in usage_counters from Photo records."""
    result = await service.sync_cloudinary_usage(db)
    return ok(result, request=request)


@router.post("/recalculate-developer-stats")
async def recalculate_developer_stats(
    request: Request,
    _: None = Depends(verify_cron_token),
    db: AsyncSession = Depends(get_db),
):
    """Recompute avg_update_frequency_days, update_consistency_pct, and
    active_developments for every developer (brief credibility profile)."""
    result = await service.recalculate_developer_stats(db)
    return ok(result, request=request)
