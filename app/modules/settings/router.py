from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Optional
from pydantic import BaseModel
from app.core.database import get_db
from app.core.deps import require_admin, get_tenant_context, TenantContext
from app.modules.settings import service
from app.shared.response import ok
from app.core.exceptions import ForbiddenError, NotFoundError

router = APIRouter(tags=["settings"])


class BulkSettingsRequest(BaseModel):
    settings: Dict[str, Optional[str]]


class SystemSettingRequest(BaseModel):
    value: Optional[str]
    description: Optional[str] = None


@router.get("/settings")
async def get_tenant_settings(db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    if not ctx.developer_id:
        raise ForbiddenError("Developer access required")
    return ok(await service.get_tenant_settings(db, ctx.developer_id))


@router.get("/settings/{key}")
async def get_tenant_setting(key: str, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    if not ctx.developer_id:
        raise ForbiddenError("Developer access required")
    settings = await service.get_tenant_settings(db, ctx.developer_id)
    match = next((s for s in settings if s["key"] == key), None)
    if not match:
        raise NotFoundError(f"Setting '{key}' not found")
    return ok(match)


@router.put("/settings/{key}")
async def update_tenant_setting(key: str, req: SystemSettingRequest, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    if not ctx.developer_id:
        raise ForbiddenError("Developer access required")
    return ok(await service.update_tenant_setting(db, ctx.developer_id, key, req.value, ctx.user_id))


@router.put("/settings")
async def bulk_update_settings(req: BulkSettingsRequest, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    if not ctx.developer_id:
        raise ForbiddenError("Developer access required")
    return ok(await service.bulk_update_tenant_settings(db, ctx.developer_id, req.settings, ctx.user_id))


@router.get("/admin/system-settings")
async def get_system_settings(db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    return ok(await service.get_system_settings(db))


@router.put("/admin/system-settings/{key}")
async def update_system_setting(key: str, req: SystemSettingRequest, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    if ctx.role != "admin":
        raise ForbiddenError("Admin access required")
    return ok(await service.update_system_setting(db, key, req.value, req.description, ctx.user_id))
