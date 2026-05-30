from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.exceptions import QuotaExceededError
import structlog

logger = structlog.get_logger(__name__)

# v2 brief tier limits (Section 1). max_units None = unlimited (enterprise).
# monthly_fee_kes is informational; max_projects None = unlimited.
TIER_LIMITS = {
    "trial": {
        "max_units": 80,
        "monthly_fee_kes": 0,
        "max_projects": 1,
        "max_photos_per_upload": 10,
        "max_storage_gb": 5,
        "max_emails_per_month": 1000,
    },
    "small": {
        "max_units": 80,
        "monthly_fee_kes": 20000,
        "max_projects": 3,
        "max_photos_per_upload": 20,
        "max_storage_gb": 20,
        "max_emails_per_month": 3000,
    },
    "medium": {
        "max_units": 200,
        "monthly_fee_kes": 32000,
        "max_projects": 5,
        "max_photos_per_upload": 20,
        "max_storage_gb": 50,
        "max_emails_per_month": 8000,
    },
    "large": {
        "max_units": 400,
        "monthly_fee_kes": 52000,
        "max_projects": 10,
        "max_photos_per_upload": 25,
        "max_storage_gb": 100,
        "max_emails_per_month": 15000,
    },
    "enterprise": {
        "max_units": None,
        "monthly_fee_kes": 75000,
        "max_projects": None,
        "max_photos_per_upload": 30,
        "max_storage_gb": 200,
        "max_emails_per_month": 30000,
    },
}


def _limits(tier: str) -> dict:
    return TIER_LIMITS.get(tier, TIER_LIMITS["trial"])


async def get_developer_tier(db: AsyncSession, developer_id: str) -> str:
    """Get the subscription tier for a developer."""
    from app.modules.developers.models import Developer
    result = await db.execute(
        select(Developer.subscription_tier).where(Developer.id == developer_id)
    )
    tier = result.scalar_one_or_none()
    return tier or "trial"


async def assert_can_create_project(db: AsyncSession, developer_id: str):
    """Raise QuotaExceededError if developer is at max_projects for their tier."""
    from app.modules.projects.models import Project

    tier = await get_developer_tier(db, developer_id)
    max_projects = _limits(tier)["max_projects"]
    if max_projects is None:
        return

    result = await db.execute(
        select(func.count()).select_from(Project).where(
            Project.developer_id == developer_id,
            Project.deleted_at.is_(None),
        )
    )
    current_count = result.scalar_one()
    if current_count >= max_projects:
        raise QuotaExceededError(
            f"Project limit reached. Your {tier} plan allows {max_projects} projects.",
            {"current": current_count, "limit": max_projects, "tier": tier},
        )


async def assert_within_unit_capacity(db: AsyncSession, developer_id: str, project_unit_count: int):
    """Per brief Section 1: a project's unit count must fit the developer's tier capacity.
    small<=80, medium<=200, large<=400, enterprise unlimited."""
    tier = await get_developer_tier(db, developer_id)
    max_units = _limits(tier)["max_units"]
    if max_units is None or project_unit_count is None:
        return
    if project_unit_count > max_units:
        raise QuotaExceededError(
            f"Unit capacity exceeded. Your {tier} plan supports up to {max_units} units per project.",
            {"requested": project_unit_count, "limit": max_units, "tier": tier},
        )


async def assert_can_invite_buyer(db: AsyncSession, project_id: str):
    """Raise if the project's buyer count is at the tier's per-project unit capacity."""
    from app.modules.buyers.models import Buyer
    from app.modules.projects.models import Project

    result = await db.execute(select(Project.developer_id).where(Project.id == project_id))
    developer_id = result.scalar_one_or_none()
    if not developer_id:
        return

    tier = await get_developer_tier(db, developer_id)
    max_units = _limits(tier)["max_units"]
    if max_units is None:
        return

    result = await db.execute(
        select(func.count()).select_from(Buyer).where(
            Buyer.project_id == project_id,
            Buyer.deleted_at.is_(None),
        )
    )
    current_count = result.scalar_one()
    if current_count >= max_units:
        raise QuotaExceededError(
            f"Buyer limit reached. Your {tier} plan allows {max_units} buyers per project.",
            {"current": current_count, "limit": max_units, "tier": tier},
        )


async def assert_can_upload_photos(db: AsyncSession, developer_id: str, photo_count: int):
    """Raise if photo_count exceeds the tier's max_photos_per_upload."""
    tier = await get_developer_tier(db, developer_id)
    max_photos = _limits(tier)["max_photos_per_upload"]
    if photo_count > max_photos:
        raise QuotaExceededError(
            f"Photo limit per upload exceeded. Your {tier} plan allows {max_photos} photos per upload.",
            {"requested": photo_count, "limit": max_photos, "tier": tier},
        )


async def assert_can_send_email(db: AsyncSession, developer_id: str, recipient_count: int):
    """Raise if recipient_count exceeds the tier's monthly email allowance."""
    tier = await get_developer_tier(db, developer_id)
    max_recipients = _limits(tier)["max_emails_per_month"]
    if recipient_count > max_recipients:
        raise QuotaExceededError(
            f"Email recipient limit exceeded. Your {tier} plan allows {max_recipients} recipients per month.",
            {"requested": recipient_count, "limit": max_recipients, "tier": tier},
        )
