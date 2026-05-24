from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Optional
from pydantic import BaseModel
from app.core.database import get_db
from app.core.deps import require_admin, get_tenant_context, TenantContext
from app.modules.settings import service
from app.shared.response import ok

router = APIRouter(tags=["settings"])


class BulkSettingsRequest(BaseModel):
    settings: Dict[str, Optional[str]]


class SystemSettingRequest(BaseModel):
    value: Optional[str]
    description: Optional[str] = None


@router.get("/settings")
async def get_tenant_settings(db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    if not ctx.developer_id:
        from app.core.exceptions import ForbiddenError
        raise ForbiddenError("Developer access required")
    return ok(await service.get_tenant_settings(db, ctx.developer_id))


@router.put("/settings/{key}")
async def update_tenant_setting(key: str, req: SystemSettingRequest, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    if not ctx.developer_id:
        from app.core.exceptions import ForbiddenError
        raise ForbiddenError("Developer access required")
    data = await service.update_tenant_setting(db, ctx.developer_id, key, req.value, ctx.user_id)
    return ok(data)


@router.put("/settings")
async def bulk_update_settings(req: BulkSettingsRequest, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    if not ctx.developer_id:
        from app.core.exceptions import ForbiddenError
        raise ForbiddenError("Developer access required")
    data = await service.bulk_update_tenant_settings(db, ctx.developer_id, req.settings, ctx.user_id)
    return ok(data)


@router.get("/admin/system-settings")
async def get_system_settings(db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    return ok(await service.get_system_settings(db))


@router.put("/admin/system-settings/{key}")
async def update_system_setting(key: str, req: SystemSettingRequest, db: AsyncSession = Depends(get_db), ctx: TenantContext = Depends(get_tenant_context)):
    if ctx.role != "admin":
        from app.core.exceptions import ForbiddenError
        raise ForbiddenError("Admin access required")
    data = await service.update_system_setting(db, key, req.value, req.description, ctx.user_id)
    return ok(data)
