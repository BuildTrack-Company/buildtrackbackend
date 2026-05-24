from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.exceptions import QuotaExceededError
import structlog

logger = structlog.get_logger(__name__)

# Default tier limits
TIER_LIMITS = {
    "trial": {
        "max_projects": 2,
        "max_buyers_per_project": 10,
        "max_photos_per_upload": 5,
        "max_email_recipients_per_month": 100,
    },
    "starter": {
        "max_projects": 10,
        "max_buyers_per_project": 50,
        "max_photos_per_upload": 20,
        "max_email_recipients_per_month": 1000,
    },
    "professional": {
        "max_projects": 50,
        "max_buyers_per_project": 200,
        "max_photos_per_upload": 50,
        "max_email_recipients_per_month": 10000,
    },
    "enterprise": {
        "max_projects": 999999,
        "max_buyers_per_project": 999999,
        "max_photos_per_upload": 100,
        "max_email_recipients_per_month": 999999,
    },
}


async def get_developer_tier(db: AsyncSession, developer_id: str) -> str:
    """Get the subscription tier for a developer."""
    from app.modules.developers.models import Developer
    result = await db.execute(
        select(Developer.subscription_tier).where(Developer.id == developer_id)
    )
    tier = result.scalar_one_or_none()
    return tier or "trial"


async def assert_can_create_project(db: AsyncSession, developer_id: str):
    """Check if developer can create a new project."""
    from app.modules.projects.models import Project

    tier = await get_developer_tier(db, developer_id)
    limits = TIER_LIMITS.get(tier, TIER_LIMITS["trial"])
    max_projects = limits["max_projects"]

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


async def assert_can_invite_buyer(db: AsyncSession, project_id: str):
    """Check if more buyers can be invited to a project."""
    from app.modules.buyers.models import Buyer
    from app.modules.projects.models import Project

    result = await db.execute(
        select(Project.developer_id).where(Project.id == project_id)
    )
    developer_id = result.scalar_one_or_none()
    if not developer_id:
        return

    tier = await get_developer_tier(db, developer_id)
    limits = TIER_LIMITS.get(tier, TIER_LIMITS["trial"])
    max_buyers = limits["max_buyers_per_project"]

    result = await db.execute(
        select(func.count()).select_from(Buyer).where(
            Buyer.project_id == project_id,
            Buyer.deleted_at.is_(None),
        )
    )
    current_count = result.scalar_one()

    if current_count >= max_buyers:
        raise QuotaExceededError(
            f"Buyer limit reached. Your {tier} plan allows {max_buyers} buyers per project.",
            {"current": current_count, "limit": max_buyers, "tier": tier},
        )


async def assert_can_upload_photos(db: AsyncSession, developer_id: str, photo_count: int):
    """Check if developer can upload given number of photos."""
    tier = await get_developer_tier(db, developer_id)
    limits = TIER_LIMITS.get(tier, TIER_LIMITS["trial"])
    max_photos = limits["max_photos_per_upload"]

    if photo_count > max_photos:
        raise QuotaExceededError(
            f"Photo limit per upload exceeded. Your {tier} plan allows {max_photos} photos per upload.",
            {"requested": photo_count, "limit": max_photos, "tier": tier},
        )


async def assert_can_send_email(db: AsyncSession, developer_id: str, recipient_count: int):
    """Check if developer can send email to given number of recipients."""
    tier = await get_developer_tier(db, developer_id)
    limits = TIER_LIMITS.get(tier, TIER_LIMITS["trial"])
    max_recipients = limits["max_email_recipients_per_month"]

    if recipient_count > max_recipients:
        raise QuotaExceededError(
            f"Email recipient limit exceeded. Your {tier} plan allows {max_recipients} recipients per month.",
            {"requested": recipient_count, "limit": max_recipients, "tier": tier},
        )
