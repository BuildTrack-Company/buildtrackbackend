from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List
from pydantic import BaseModel

from app.core.database import get_db
from app.core.deps import require_admin, get_current_user, get_tenant_context, TenantContext, require_permission
from app.modules.project_types import service
from app.modules.project_types.models import ProjectType, WorkflowTemplate, WorkflowStage, WorkflowTransition
from app.shared.response import ok
from app.shared.ids import new_id
from app.core.exceptions import NotFoundError, ForbiddenError, DuplicateError

router = APIRouter(prefix="/project-types", tags=["project-types"])
admin_router = APIRouter(prefix="/admin", tags=["project-types"])


# ─── Request schemas ──────────────────────────────────────────────────────────

class ProjectTypeCreate(BaseModel):
    name: str
    description: Optional[str] = None


class ProjectTypeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class StageIn(BaseModel):
    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    order_index: int
    expected_duration_days: Optional[int] = None
    requires_buyer_approval: bool = False
    requires_photo: bool = False
    requires_file: bool = False


class TransitionIn(BaseModel):
    from_stage_id: Optional[str] = None
    to_stage_id: str
    name: Optional[str] = None
    condition_type: Optional[str] = None


class WorkflowTemplateCreate(BaseModel):
    project_type_id: str
    name: str
    description: Optional[str] = None
    stages: List[StageIn] = []
    transitions: List[TransitionIn] = []


class WorkflowTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    stages: Optional[List[StageIn]] = None
    transitions: Optional[List[TransitionIn]] = None


# ─── Tenant project type routes ───────────────────────────────────────────────

@router.get("", dependencies=[require_permission("project_types", "read")])
async def list_project_types(
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
):
    return ok(await service.list_project_types(db, ctx.developer_id))


@router.post("", status_code=201, dependencies=[require_permission("project_types", "manage")])
async def create_project_type(
    req: ProjectTypeCreate,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
):
    if not ctx.developer_id:
        raise ForbiddenError("Developer access required")
    return ok(await service.create_project_type(db, ctx.developer_id, req.name, req.description))


@router.patch("/{type_id}", dependencies=[require_permission("project_types", "manage")])
async def update_project_type(
    type_id: str,
    req: ProjectTypeUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
):
    return ok(await service.update_project_type(db, type_id, ctx.developer_id, req.name, req.description))


@router.delete("/{type_id}", status_code=204, dependencies=[require_permission("project_types", "manage")])
async def delete_project_type(
    type_id: str,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
):
    await service.delete_project_type(db, type_id, ctx.developer_id)


# ─── Workflow template routes (specific paths before /{template_id}) ──────────

@router.get("/templates/project-type/{project_type_id}/default", dependencies=[require_permission("project_types", "read")])
async def get_default_template_for_type(
    project_type_id: str,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
):
    data = await service.get_default_template_for_type(db, project_type_id, ctx.developer_id)
    if not data:
        raise NotFoundError("No default template found for this project type")
    return ok(data)


@router.get("/templates", dependencies=[require_permission("project_types", "read")])
async def list_workflow_templates(
    project_type_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
):
    return ok(await service.list_workflow_templates(db, ctx.developer_id, project_type_id))


@router.post("/templates", status_code=201, dependencies=[require_permission("project_types", "manage")])
async def create_workflow_template(
    req: WorkflowTemplateCreate,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
):
    if not ctx.developer_id:
        raise ForbiddenError("Developer access required")
    return ok(await service.create_workflow_template(
        db, ctx.developer_id, req.project_type_id, req.name, req.description,
        [s.model_dump() for s in req.stages], [t.model_dump() for t in req.transitions],
    ))


@router.post("/templates/{template_id}/duplicate", status_code=201, dependencies=[require_permission("project_types", "manage")])
async def duplicate_workflow_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
):
    if not ctx.developer_id:
        raise ForbiddenError("Developer access required")
    return ok(await service.duplicate_workflow_template(db, template_id, ctx.developer_id))


@router.get("/templates/{template_id}/stages", dependencies=[require_permission("project_types", "read")])
async def get_template_stages(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
):
    data = await service.get_template_stages(db, template_id, ctx.developer_id)
    if not data:
        raise NotFoundError("Workflow template not found")
    return ok(data)


@router.get("/templates/{template_id}/transitions", dependencies=[require_permission("project_types", "read")])
async def get_template_transitions(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
):
    data = await service.get_template_transitions(db, template_id, ctx.developer_id)
    if not data:
        raise NotFoundError("Workflow template not found")
    return ok(data)


@router.get("/templates/{template_id}", dependencies=[require_permission("project_types", "read")])
async def get_workflow_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
):
    data = await service.get_workflow_template(db, template_id, ctx.developer_id)
    if not data:
        raise NotFoundError("Workflow template not found")
    return ok(data)


@router.put("/templates/{template_id}", dependencies=[require_permission("project_types", "manage")])
async def update_workflow_template(
    template_id: str,
    req: WorkflowTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
):
    return ok(await service.update_workflow_template(
        db, template_id, ctx.developer_id, req.name, req.description,
        [s.model_dump() for s in req.stages] if req.stages is not None else None,
        [t.model_dump() for t in req.transitions] if req.transitions is not None else None,
    ))


@router.delete("/templates/{template_id}", status_code=204, dependencies=[require_permission("project_types", "manage")])
async def delete_workflow_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    ctx: TenantContext = Depends(get_tenant_context),
):
    await service.delete_workflow_template(db, template_id, ctx.developer_id)


# ─── Admin project-type routes ────────────────────────────────────────────────

@admin_router.get("/project-types")
async def admin_list_project_types(db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    return ok(await service.list_project_types(db, developer_id=None))


@admin_router.post("/project-types", status_code=201)
async def admin_create_project_type(
    req: ProjectTypeCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    existing = (await db.execute(select(ProjectType).where(ProjectType.name == req.name))).scalar_one_or_none()
    if existing:
        raise DuplicateError(f"Project type '{req.name}' already exists")
    now = datetime.now(timezone.utc)
    pt = ProjectType(id=new_id(), name=req.name, description=req.description, is_system=True, developer_id=None, created_at=now, updated_at=now)
    db.add(pt)
    await db.commit()
    return ok({"id": pt.id, "name": pt.name, "description": pt.description, "is_system": pt.is_system, "templates": []})


@admin_router.patch("/project-types/{type_id}")
async def admin_update_project_type(
    type_id: str,
    req: ProjectTypeUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    return ok(await service.update_project_type(db, type_id, None, req.name, req.description, is_admin=True))


@admin_router.delete("/project-types/{type_id}", status_code=204)
async def admin_delete_project_type(
    type_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    await service.delete_project_type(db, type_id, None, is_admin=True)


@admin_router.get("/workflow-templates")
async def admin_list_workflow_templates(
    project_type_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    return ok(await service.list_workflow_templates(db, developer_id=None, project_type_id=project_type_id))


@admin_router.post("/workflow-templates", status_code=201)
async def admin_create_workflow_template(
    req: WorkflowTemplateCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    pt = (await db.execute(select(ProjectType).where(ProjectType.id == req.project_type_id))).scalar_one_or_none()
    if not pt:
        raise NotFoundError("Project type not found")
    now = datetime.now(timezone.utc)
    tmpl = WorkflowTemplate(
        id=new_id(), project_type_id=req.project_type_id, name=req.name,
        description=req.description, is_system=True, is_active=True, developer_id=None,
        created_at=now, updated_at=now,
    )
    db.add(tmpl)
    await db.flush()
    stage_map = await service._create_stages(db, tmpl.id, [s.model_dump() for s in req.stages], now)
    await service._create_transitions(db, tmpl.id, [t.model_dump() for t in req.transitions], stage_map, now)
    await db.commit()
    return ok(await service.get_workflow_template(db, tmpl.id))


@admin_router.patch("/workflow-templates/{template_id}")
async def admin_update_workflow_template(
    template_id: str,
    req: WorkflowTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    return ok(await service.update_workflow_template(
        db, template_id, None, req.name, req.description,
        [s.model_dump() for s in req.stages] if req.stages is not None else None,
        [t.model_dump() for t in req.transitions] if req.transitions is not None else None,
        is_admin=True,
    ))


@admin_router.delete("/workflow-templates/{template_id}", status_code=204)
async def admin_delete_workflow_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    await service.delete_workflow_template(db, template_id, None, is_admin=True)
