from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional

from app.modules.developers.models import Developer
from app.modules.auth.models import User
from app.modules.projects.models import Project
from app.modules.buyers.models import Buyer
from app.modules.uploads.models import Upload
from app.core.exceptions import NotFoundError
from app.shared.ids import new_id
from app.core.security import hash_password


async def list_developers(db: AsyncSession, page: int = 1, limit: int = 20):
    offset = (page - 1) * limit
    result = await db.execute(
        select(Developer).where(Developer.deleted_at.is_(None)).offset(offset).limit(limit)
    )
    developers = result.scalars().all()
    count = await db.execute(select(func.count()).select_from(Developer).where(Developer.deleted_at.is_(None)))
    total = count.scalar_one()
    return developers, total


async def create_developer_admin(db: AsyncSession, req) -> Developer:
    from app.core.exceptions import DuplicateError

    result = await db.execute(select(User).where(User.email == req.email.lower()))
    if result.scalar_one_or_none():
        raise DuplicateError("Email already registered")

    user = User(
        id=new_id(),
        email=req.email.lower(),
        hashed_password=hash_password(req.password),
        role="developer",
        full_name=req.full_name,
        is_active=True,
        email_verified=True,
    )
    db.add(user)
    await db.flush()

    developer = Developer(
        id=new_id(),
        user_id=user.id,
        company_name=req.company_name,
        subscription_tier=req.subscription_tier,
        subscription_status="active",
    )
    db.add(developer)
    await db.commit()
    await db.refresh(developer)
    return developer


async def update_developer_admin(db: AsyncSession, developer_id: str, updates: dict) -> Developer:
    result = await db.execute(
        select(Developer).where(Developer.id == developer_id, Developer.deleted_at.is_(None))
    )
    dev = result.scalar_one_or_none()
    if not dev:
        raise NotFoundError("Developer not found")

    for field, value in updates.items():
        if hasattr(dev, field):
            setattr(dev, field, value)

    dev.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(dev)
    return dev


async def soft_delete_developer(db: AsyncSession, developer_id: str):
    result = await db.execute(
        select(Developer).where(Developer.id == developer_id)
    )
    dev = result.scalar_one_or_none()
    if not dev:
        raise NotFoundError("Developer not found")
    dev.deleted_at = datetime.now(timezone.utc)
    await db.commit()


async def get_platform_stats(db: AsyncSession) -> dict:
    total_devs = (await db.execute(select(func.count()).select_from(Developer).where(Developer.deleted_at.is_(None)))).scalar_one()
    total_projects = (await db.execute(select(func.count()).select_from(Project).where(Project.deleted_at.is_(None)))).scalar_one()
    total_buyers = (await db.execute(select(func.count()).select_from(Buyer).where(Buyer.deleted_at.is_(None)))).scalar_one()
    total_uploads = (await db.execute(select(func.count()).select_from(Upload))).scalar_one()
    flagged = (await db.execute(select(func.count()).select_from(Upload).where(Upload.status == "flagged"))).scalar_one()

    return {
        "total_developers": total_devs,
        "total_projects": total_projects,
        "total_buyers": total_buyers,
        "total_uploads": total_uploads,
        "flagged_uploads": flagged,
    }
