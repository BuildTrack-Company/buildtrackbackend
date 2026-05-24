from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.modules.milestones.models import Milestone
from app.modules.projects.models import Project
from app.core.exceptions import NotFoundError, ForbiddenError


async def get_project_milestones(db: AsyncSession, project_id: str, developer_id: str) -> List[Milestone]:
    # Verify project belongs to developer
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.developer_id == developer_id,
            Project.deleted_at.is_(None),
        )
    )
    if not result.scalar_one_or_none():
        raise NotFoundError("Project not found")

    result = await db.execute(
        select(Milestone).where(Milestone.project_id == project_id).order_by(Milestone.order_index)
    )
    return result.scalars().all()


async def get_milestone(db: AsyncSession, milestone_id: str, project_id: str, developer_id: str) -> Milestone:
    # Verify project ownership
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.developer_id == developer_id,
            Project.deleted_at.is_(None),
        )
    )
    if not result.scalar_one_or_none():
        raise NotFoundError("Project not found")

    result = await db.execute(
        select(Milestone).where(
            Milestone.id == milestone_id,
            Milestone.project_id == project_id,
        )
    )
    milestone = result.scalar_one_or_none()
    if not milestone:
        raise NotFoundError("Milestone not found")
    return milestone


async def update_milestone(
    db: AsyncSession, milestone_id: str, project_id: str, developer_id: str, req
) -> Milestone:
    milestone = await get_milestone(db, milestone_id, project_id, developer_id)
    for field, value in req.model_dump(exclude_none=True).items():
        setattr(milestone, field, value)
    milestone.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(milestone)
    return milestone


async def complete_milestone(
    db: AsyncSession, milestone_id: str, project_id: str, developer_id: str, notes: str = None
) -> Milestone:
    milestone = await get_milestone(db, milestone_id, project_id, developer_id)
    milestone.status = "completed"
    milestone.completed_at = datetime.now(timezone.utc)
    if notes:
        milestone.description = notes
    milestone.updated_at = datetime.now(timezone.utc)

    # Update project status if all milestones complete
    result = await db.execute(
        select(Milestone).where(
            Milestone.project_id == project_id,
            Milestone.status != "completed",
            Milestone.id != milestone_id,
        )
    )
    remaining = result.scalars().all()
    if not remaining:
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if project:
            project.status = "completed"

    await db.commit()
    await db.refresh(milestone)
    return milestone


async def delay_milestone(
    db: AsyncSession, milestone_id: str, project_id: str, developer_id: str, reason: str, new_date
) -> Milestone:
    milestone = await get_milestone(db, milestone_id, project_id, developer_id)
    milestone.status = "delayed"
    milestone.delay_reason = reason
    milestone.delay_new_date = new_date
    milestone.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(milestone)
    return milestone
