from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.modules.developers.models import Developer
from app.core.exceptions import NotFoundError


async def get_developer_by_user_id(db: AsyncSession, user_id: str) -> Developer:
    result = await db.execute(select(Developer).where(Developer.user_id == user_id))
    dev = result.scalar_one_or_none()
    if not dev:
        raise NotFoundError("Developer profile not found")
    return dev


async def get_developer_by_id(db: AsyncSession, developer_id: str) -> Developer:
    result = await db.execute(select(Developer).where(Developer.id == developer_id))
    dev = result.scalar_one_or_none()
    if not dev:
        raise NotFoundError("Developer not found")
    return dev
