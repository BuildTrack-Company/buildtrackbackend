from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_tenant_context, TenantContext, require_permission
from app.modules.milestones import service, schemas
from app.shared.response import ok
from app.shared.audit import log_action

router = APIRouter(tags=["milestones"])


@router.get("/projects/{project_id}/milestones", dependencies=[require_permission("milestones", "read")])
async def list_milestones(
    project_id: str,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    milestones = await service.get_project_milestones(db, project_id, ctx.developer_id)
    return ok([schemas.MilestoneResponse.model_validate(m).model_dump() for m in milestones], request=request)


@router.patch("/projects/{project_id}/milestones/{milestone_id}", dependencies=[require_permission("milestones", "update")])
async def update_milestone(
    project_id: str,
    milestone_id: str,
    req: schemas.MilestoneUpdate,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    milestone = await service.update_milestone(db, milestone_id, project_id, ctx.developer_id, req)
    return ok(schemas.MilestoneResponse.model_validate(milestone).model_dump(), request=request)


@router.post("/projects/{project_id}/milestones/{milestone_id}/complete", dependencies=[require_permission("milestones", "update")])
async def complete_milestone(
    project_id: str,
    milestone_id: str,
    req: schemas.MilestoneCompleteRequest,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    milestone = await service.complete_milestone(db, milestone_id, project_id, ctx.developer_id, req.notes)

    await log_action(
        db,
        actor_user_id=ctx.user_id,
        actor_role=ctx.role,
        action="milestone.completed",
        entity_type="milestone",
        entity_id=milestone_id,
        developer_id=ctx.developer_id,
        after={"name": milestone.name, "completed_at": str(milestone.completed_at)},
        request_id=getattr(request.state, "request_id", None),
    )

    return ok(schemas.MilestoneResponse.model_validate(milestone).model_dump(), request=request)


@router.post("/projects/{project_id}/milestones/{milestone_id}/delay", dependencies=[require_permission("milestones", "update")])
async def delay_milestone(
    project_id: str,
    milestone_id: str,
    req: schemas.MilestoneDelayRequest,
    request: Request,
    ctx: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
):
    milestone = await service.delay_milestone(
        db, milestone_id, project_id, ctx.developer_id, req.reason, req.new_expected_date
    )

    await log_action(
        db,
        actor_user_id=ctx.user_id,
        actor_role=ctx.role,
        action="milestone.delayed",
        entity_type="milestone",
        entity_id=milestone_id,
        developer_id=ctx.developer_id,
        after={"name": milestone.name, "reason": req.reason, "new_expected_date": str(req.new_expected_date)},
        request_id=getattr(request.state, "request_id", None),
    )

    return ok(schemas.MilestoneResponse.model_validate(milestone).model_dump(), request=request)
