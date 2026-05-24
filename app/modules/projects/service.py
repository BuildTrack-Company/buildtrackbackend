from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.modules.projects.models import Project
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate
from app.core.exceptions import NotFoundError, ForbiddenError
from app.shared.ids import new_id
from app.shared.code_gen import generate_project_code
from app.shared.quotas import assert_can_create_project


async def create_project(db: AsyncSession, developer_id: str, req: ProjectCreate) -> Project:
    await assert_can_create_project(db, developer_id)

    # Generate unique project code
    for _ in range(10):
        code = generate_project_code()
        result = await db.execute(select(Project).where(Project.project_code == code))
        if not result.scalar_one_or_none():
            break

    project = Project(
        id=new_id(),
        developer_id=developer_id,
        project_code=code,
        name=req.name,
        description=req.description,
        location_name=req.location_name,
        site_latitude=req.site_latitude,
        site_longitude=req.site_longitude,
        gps_radius_metres=req.gps_radius_metres,
        total_units=req.total_units,
        estimated_completion=req.estimated_completion,
        status="planning",
    )
    db.add(project)
    await db.flush()

    # Seed milestones
    await seed_milestones(db, project.id)

    await db.commit()
    await db.refresh(project)
    return project


async def seed_milestones(db: AsyncSession, project_id: str):
    from app.modules.milestones.models import Milestone

    default_milestones = [
        ("Foundation", 1),
        ("Superstructure", 2),
        ("Roofing", 3),
        ("Finishing", 4),
        ("Handover", 5),
    ]
    for name, order in default_milestones:
        milestone = Milestone(
            id=new_id(),
            project_id=project_id,
            name=name,
            order_index=order,
            status="pending",
        )
        db.add(milestone)
    await db.flush()


async def list_projects(db: AsyncSession, developer_id: str) -> List[Project]:
    result = await db.execute(
        select(Project).where(
            Project.developer_id == developer_id,
            Project.deleted_at.is_(None),
        ).order_by(Project.created_at.desc())
    )
    return result.scalars().all()


async def get_project(db: AsyncSession, project_id: str, developer_id: str) -> Project:
    result = await db.execute(
        select(Project).where(
            Project.id == project_id,
            Project.developer_id == developer_id,
            Project.deleted_at.is_(None),
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise NotFoundError("Project not found")
    return project


async def get_project_by_code(db: AsyncSession, code: str) -> Project:
    result = await db.execute(
        select(Project).where(
            Project.project_code == code.upper(),
            Project.is_public.is_(True),
            Project.deleted_at.is_(None),
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise NotFoundError("Project not found")
    return project


async def update_project(db: AsyncSession, project_id: str, developer_id: str, req: ProjectUpdate) -> Project:
    project = await get_project(db, project_id, developer_id)
    for field, value in req.model_dump(exclude_none=True).items():
        setattr(project, field, value)
    project.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(project)
    return project


async def delete_project(db: AsyncSession, project_id: str, developer_id: str):
    project = await get_project(db, project_id, developer_id)
    project.deleted_at = datetime.now(timezone.utc)
    await db.commit()
