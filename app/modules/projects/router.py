from fastapi import APIRouter, Depends, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.core.deps import require_developer, get_tenant_context, TenantContext, require_permission
from app.modules.auth.models import User
from app.modules.projects import service, schemas
from app.modules.projects import workflow_service
from app.shared.response import ok
from app.shared.audit import log_action

router = APIRouter(tags=["projects"])


@router.get("/projects", dependencies=[require_permission("projects", "read")])
async def list_projects(
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    projects = await service.list_projects(db, ctx.developer_id)
    return ok([schemas.ProjectResponse.model_validate(p).model_dump() for p in projects], request=request)


@router.post("/projects", status_code=201, dependencies=[require_permission("projects", "create")])
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


@router.get("/projects/{project_id}", dependencies=[require_permission("projects", "read")])
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


@router.patch("/projects/{project_id}", dependencies=[require_permission("projects", "update")])
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


@router.delete("/projects/{project_id}", status_code=204, dependencies=[require_permission("projects", "delete")])
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


# ─── Workflow runtime ────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/workflow", dependencies=[require_permission("workflow", "read")])
async def get_project_workflow(
    project_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    data = await workflow_service.get_project_workflow(
        db, project_id, ctx.developer_id, ctx.user_id, ctx.role
    )
    return ok(data, request=request)


@router.get("/projects/{project_id}/workflow/next-stages", dependencies=[require_permission("workflow", "read")])
async def get_workflow_next_stages(
    project_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    data = await workflow_service.get_next_stages(
        db, project_id, ctx.developer_id, ctx.user_id, ctx.role
    )
    return ok(data, request=request)


@router.get("/projects/{project_id}/workflow/history", dependencies=[require_permission("workflow", "read")])
async def get_workflow_history(
    project_id: str,
    request: Request,
    page: int = 1,
    limit: int = 20,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    data = await workflow_service.get_workflow_history(
        db, project_id, ctx.developer_id, ctx.user_id, ctx.role, page, limit
    )
    return ok(data, request=request)


class AdvanceWorkflowRequest(BaseModel):
    to_stage_id: str
    notes: Optional[str] = None


@router.post("/projects/{project_id}/workflow/advance", dependencies=[require_permission("workflow", "advance")])
async def advance_project_workflow(
    project_id: str,
    req: AdvanceWorkflowRequest,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    if not idempotency_key:
        from app.core.exceptions import ValidationError
        raise ValidationError("Idempotency-Key header is required")

    data = await workflow_service.advance_workflow(
        db,
        project_id,
        ctx.developer_id,
        ctx.user_id,
        ctx.role,
        req.to_stage_id,
        req.notes,
        idempotency_key,
        getattr(request.state, "request_id", None),
    )
    return ok(data, request=request)
