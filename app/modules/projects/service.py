import re
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.modules.projects.models import Project
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate
from app.core.exceptions import NotFoundError, ForbiddenError
from app.shared.ids import new_id
from app.shared.code_gen import generate_project_code
from app.shared.quotas import assert_within_unit_capacity


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "project"


async def generate_unique_slug(db: AsyncSession, name: str) -> str:
    """Kebab-case slug from the project name, with a collision check."""
    base = _slugify(name)
    candidate = base
    n = 2
    while True:
        existing = await db.execute(select(Project.id).where(Project.slug == candidate))
        if not existing.scalar_one_or_none():
            return candidate
        candidate = f"{base}-{n}"
        n += 1


async def create_project(db: AsyncSession, developer_id: str, req: ProjectCreate) -> Project:
    # New projects start on the "trial" tier until their subscription is configured
    # (subscriptions are scoped to the project, not the developer).
    await assert_within_unit_capacity(db, "trial", req.total_units)

    # Generate unique project code
    for _ in range(10):
        code = generate_project_code()
        result = await db.execute(select(Project).where(Project.project_code == code))
        if not result.scalar_one_or_none():
            break

    slug = await generate_unique_slug(db, req.name)

    # Resolve workflow template
    workflow_template_id = req.workflow_template_id
    project_type_id = None
    if workflow_template_id:
        from app.modules.project_types.models import WorkflowTemplate
        tmpl_result = await db.execute(select(WorkflowTemplate).where(WorkflowTemplate.id == workflow_template_id))
        tmpl = tmpl_result.scalar_one_or_none()
        if tmpl:
            project_type_id = tmpl.project_type_id

    project = Project(
        id=new_id(),
        developer_id=developer_id,
        project_code=code,
        slug=slug,
        name=req.name,
        description=req.description,
        location_name=req.location_name,
        site_latitude=req.site_latitude,
        site_longitude=req.site_longitude,
        gps_radius_metres=req.gps_radius_metres,
        total_units=req.total_units,
        estimated_completion=req.estimated_completion,
        status="planning",
        workflow_template_id=workflow_template_id,
        project_type_id=project_type_id,
    )
    db.add(project)
    await db.flush()

    # Seed milestones from template or defaults
    await seed_milestones(db, project.id, workflow_template_id)

    await db.commit()
    await db.refresh(project)
    return project


async def seed_milestones(db: AsyncSession, project_id: str, workflow_template_id: str = None):
    from app.modules.milestones.models import Milestone

    stages = []
    if workflow_template_id:
        from app.modules.project_types.models import WorkflowStage
        result = await db.execute(
            select(WorkflowStage)
            .where(WorkflowStage.workflow_template_id == workflow_template_id)
            .order_by(WorkflowStage.order_index)
        )
        stages = result.scalars().all()

    if stages:
        for stage in stages:
            milestone = Milestone(
                id=new_id(),
                project_id=project_id,
                name=stage.name,
                order_index=stage.order_index,
                status="pending",
                workflow_stage_id=stage.id,
            )
            db.add(milestone)
    else:
        # Default PRD milestone names
        default_milestones = [
            ("Pre-Construction", 1),
            ("Foundation", 2),
            ("Superstructure", 3),
            ("Building Envelope", 4),
            ("Practical Completion", 5),
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


async def update_visibility_page(
    db: AsyncSession, project_id: str, developer_id: str,
    description: str = None, tagline: str = None, starting_price: str = None, slug: str = None,
    estimated_completion=None,
) -> Project:
    """Update visibility-page content. Slug change validates uniqueness."""
    project = await get_project(db, project_id, developer_id)
    if description is not None:
        project.visibility_description = description
    if tagline is not None:
        project.visibility_tagline = tagline
    if starting_price is not None:
        project.starting_price = starting_price
    if estimated_completion is not None:
        project.estimated_completion = estimated_completion
    if slug is not None and slug != project.slug:
        desired = _slugify(slug)
        clash = await db.execute(
            select(Project.id).where(Project.slug == desired, Project.id != project_id)
        )
        if clash.scalar_one_or_none():
            from app.core.exceptions import DuplicateError
            raise DuplicateError("That slug is already in use", {"slug": desired})
        project.slug = desired
    project.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(project)
    return project


async def set_visibility_published(db: AsyncSession, project_id: str, developer_id: str, published: bool) -> Project:
    project = await get_project(db, project_id, developer_id)
    project.visibility_page_published = published
    project.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(project)
    return project
