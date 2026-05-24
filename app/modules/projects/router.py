from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.core.database import get_db
from app.core.deps import require_developer, get_tenant_context, TenantContext
from app.modules.auth.models import User
from app.modules.projects import service, schemas
from app.shared.response import ok
from app.shared.audit import log_action

router = APIRouter(tags=["projects"])


@router.get("/projects")
async def list_projects(
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    projects = await service.list_projects(db, ctx.developer_id)
    return ok([schemas.ProjectResponse.model_validate(p).model_dump() for p in projects], request=request)


@router.post("/projects", status_code=201)
async def create_project(
    req: schemas.ProjectCreate,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    project = await service.create_project(db, ctx.developer_id, req)

    await log_action(
        db,
        actor_user_id=ctx.user_id,
        actor_role=ctx.role,
        action="project.created",
        entity_type="project",
        entity_id=project.id,
        developer_id=ctx.developer_id,
        after={"name": project.name, "project_code": project.project_code},
        request_id=getattr(request.state, "request_id", None),
    )

    return ok(schemas.ProjectResponse.model_validate(project).model_dump(), request=request)


@router.get("/projects/{project_id}")
async def get_project(
    project_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    project = await service.get_project(db, project_id, ctx.developer_id)

    from app.modules.milestones.models import Milestone
    result = await db.execute(
        select(Milestone).where(Milestone.project_id == project_id).order_by(Milestone.order_index)
    )
    milestones = result.scalars().all()

    project_data = schemas.ProjectResponse.model_validate(project).model_dump()
    from app.modules.milestones.schemas import MilestoneResponse
    project_data["milestones"] = [MilestoneResponse.model_validate(m).model_dump() for m in milestones]

    return ok(project_data, request=request)


@router.patch("/projects/{project_id}")
async def update_project(
    project_id: str,
    req: schemas.ProjectUpdate,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    project = await service.update_project(db, project_id, ctx.developer_id, req)

    await log_action(
        db,
        actor_user_id=ctx.user_id,
        actor_role=ctx.role,
        action="project.updated",
        entity_type="project",
        entity_id=project.id,
        developer_id=ctx.developer_id,
        after=req.model_dump(exclude_none=True),
        request_id=getattr(request.state, "request_id", None),
    )

    return ok(schemas.ProjectResponse.model_validate(project).model_dump(), request=request)


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    await service.delete_project(db, project_id, ctx.developer_id)

    await log_action(
        db,
        actor_user_id=ctx.user_id,
        actor_role=ctx.role,
        action="project.deleted",
        entity_type="project",
        entity_id=project_id,
        developer_id=ctx.developer_id,
        request_id=getattr(request.state, "request_id", None),
    )


@router.get("/public/project-code/{code}")
async def lookup_project_by_code(
    code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    project = await service.get_project_by_code(db, code)
    return ok(schemas.ProjectResponse.model_validate(project).model_dump(), request=request)
