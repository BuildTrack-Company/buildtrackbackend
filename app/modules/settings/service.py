from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional, Dict
from datetime import datetime, timezone
from app.modules.settings.models import TenantSetting, SystemSetting
from app.shared.ids import new_id


TENANT_SETTING_DEFAULTS: Dict[str, Optional[str]] = {
    "notification_on_upload_approved": "true",
    "notification_on_milestone_complete": "true",
    "notification_on_milestone_delayed": "true",
    "buyer_can_comment": "false",
    "upload_require_caption": "true",
    "upload_min_photos": "1",
    "upload_max_photos": "10",
}


# Platform-wide notification switches, managed by the admin. These act as a
# master gate on top of each developer's per-tenant preferences.
SYSTEM_SETTING_DEFAULTS: Dict[str, dict] = {
    "notify_buyer_on_approval": {
        "value": "true",
        "description": "Email registered buyers when a construction update is approved",
    },
    "notify_developer_on_rejection": {
        "value": "true",
        "description": "Email the developer when an upload is rejected",
    },
    "notify_buyer_on_milestone_revision": {
        "value": "true",
        "description": "Email buyers when a milestone target date is revised",
    },
    "notify_developer_welcome": {
        "value": "true",
        "description": "Send the welcome + credentials emails to new developers",
    },
}


async def is_notification_enabled(db: AsyncSession, key: str, default: bool = True) -> bool:
    """Check a platform-level notification switch. Missing key => default."""
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    setting = result.scalar_one_or_none()
    if setting is None or setting.value is None:
        return default
    return str(setting.value).strip().lower() in ("true", "1", "yes", "on")


async def get_tenant_settings(db: AsyncSession, developer_id: str) -> List[dict]:
    result = await db.execute(
        select(TenantSetting).where(TenantSetting.developer_id == developer_id).order_by(TenantSetting.key)
    )
    stored = {s.key: s for s in result.scalars().all()}

    settings = []
    for key, default_value in TENANT_SETTING_DEFAULTS.items():
        if key in stored:
            s = stored[key]
            settings.append({"key": s.key, "value": s.value, "updated_at": s.updated_at})
        else:
            now = datetime.now(timezone.utc)
            settings.append({"key": key, "value": default_value, "updated_at": now})
    return settings


async def update_tenant_setting(db: AsyncSession, developer_id: str, key: str, value: Optional[str], updated_by: str) -> dict:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(TenantSetting).where(TenantSetting.developer_id == developer_id, TenantSetting.key == key)
    )
    setting = result.scalar_one_or_none()

    if setting:
        setting.value = value
        setting.updated_by = updated_by
        setting.updated_at = now
    else:
        setting = TenantSetting(
            id=new_id(),
            developer_id=developer_id,
            key=key,
            value=value,
            updated_by=updated_by,
            updated_at=now,
            created_at=now,
        )
        db.add(setting)

    await db.commit()
    return {"key": setting.key, "value": setting.value, "updated_at": setting.updated_at}


async def bulk_update_tenant_settings(db: AsyncSession, developer_id: str, updates: Dict[str, Optional[str]], updated_by: str) -> List[dict]:
    results = []
    for key, value in updates.items():
        result = await update_tenant_setting(db, developer_id, key, value, updated_by)
        results.append(result)
    return results


async def get_system_settings(db: AsyncSession) -> List[dict]:
    result = await db.execute(select(SystemSetting).order_by(SystemSetting.key))
    stored = {s.key: s for s in result.scalars().all()}

    settings = []
    # Always surface the known platform defaults so the admin can manage them
    # even before they have ever been written to the DB.
    for key, meta in SYSTEM_SETTING_DEFAULTS.items():
        if key in stored:
            s = stored.pop(key)
            settings.append({"key": s.key, "value": s.value, "description": s.description or meta["description"], "updated_at": s.updated_at})
        else:
            now = datetime.now(timezone.utc)
            settings.append({"key": key, "value": meta["value"], "description": meta["description"], "updated_at": now})
    # Append any other stored settings not covered by defaults
    for s in stored.values():
        settings.append({"key": s.key, "value": s.value, "description": s.description, "updated_at": s.updated_at})
    return settings


async def update_system_setting(db: AsyncSession, key: str, value: Optional[str], description: Optional[str], updated_by: str) -> dict:
    now = datetime.now(timezone.utc)
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    setting = result.scalar_one_or_none()

    if setting:
        setting.value = value
        if description is not None:
            setting.description = description
        setting.updated_by = updated_by
        setting.updated_at = now
    else:
        setting = SystemSetting(
            id=new_id(),
            key=key,
            value=value,
            description=description,
            updated_by=updated_by,
            updated_at=now,
            created_at=now,
        )
        db.add(setting)

    await db.commit()
    return {"key": setting.key, "value": setting.value, "description": setting.description, "updated_at": setting.updated_at}
