from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from app.modules.settings.models import TenantSetting, SystemSetting
from app.modules.settings.service import TENANT_SETTING_DEFAULTS


async def get_tenant_setting(db: AsyncSession, developer_id: str, key: str) -> Optional[str]:
    result = await db.execute(
        select(TenantSetting).where(TenantSetting.developer_id == developer_id, TenantSetting.key == key)
    )
    setting = result.scalar_one_or_none()
    if setting:
        return setting.value
    return TENANT_SETTING_DEFAULTS.get(key)


async def get_system_setting(db: AsyncSession, key: str) -> Optional[str]:
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    setting = result.scalar_one_or_none()
    return setting.value if setting else None
